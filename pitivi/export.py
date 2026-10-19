# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2026, AdrianLarry <familystyle@outlook.es>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, see <http://www.gnu.org/licenses/>.
"""Exporting the video, as in the mockup.

The user chooses the name, the folder and the quality. The video is an
MP4 file, which can be played and shared anywhere, or a WebM file if the
MP4 encoders are not installed. The render dialog of Pitivi does the
work, without being shown.
"""
import os
import time
from gettext import gettext as _

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gst
from gi.repository import Gtk
from gi.repository import Pango

from pitivi.render import Quality
from pitivi.render import RenderDialog
from pitivi.utils.formats import get_format
from pitivi.utils.ui import beautify_eta
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import set_combo_value
from pitivi.utils.ui import SPACING
from pitivi.viewer.viewer import FORMAT_NAMES

# The muxer, the video encoder and the audio encoder, the first available.
MP4 = ("mp4", "mp4mux", "x264enc", "voaacenc")
WEBM = ("webm", "webmmux", "vp8enc", "opusenc")

STANDARD = Quality.MEDIUM
HIGH = Quality.HIGH

# Bits per pixel of the video, for estimating the size of the file.
BITS_PER_PIXEL = {STANDARD: 0.1, HIGH: 0.16}
AUDIO_BITRATE = 128000


def get_file_format():
    """Returns the format of the exported files: MP4 if possible, else WebM."""
    for file_format in (MP4, WEBM):
        if all(Gst.ElementFactory.find(name) for name in file_format[1:]):
            return file_format
    return None


def estimate_size(width, height, framerate, duration, quality):
    """Returns the approximate size of the file in bytes."""
    seconds = duration / Gst.SECOND
    video_bitrate = width * height * framerate * BITS_PER_PIXEL[quality]
    return int(seconds * (video_bitrate + AUDIO_BITRATE) / 8)


def format_size(size):
    """Returns a size in megabytes, as "60 MB"."""
    megabytes = size / 1000000
    if megabytes < 1:
        return _("less than 1 MB")
    return "%d MB" % round(megabytes)


def format_duration(duration):
    """Returns a duration as minutes and seconds, as "0:48"."""
    seconds = round(duration / Gst.SECOND)
    return "%d:%02d" % divmod(seconds, 60)


def get_unique_path(folder, name, extension):
    """Returns a path for the file which does not exist yet."""
    path = os.path.join(folder, "%s.%s" % (name, extension))
    number = 2
    while os.path.exists(path):
        path = os.path.join(folder, "%s (%d).%s" % (name, number, extension))
        number += 1
    return path


def get_default_folder(app):
    folder = app.settings.lastExportFolder
    if folder and os.path.isdir(folder):
        return folder
    videos = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS)
    if videos and os.path.isdir(videos):
        return videos
    return GLib.get_home_dir()


class RenderEngine(RenderDialog):
    """Pitivi's render dialog, not shown, reporting to the export dialog."""

    def __init__(self, app, project, file_format, quality, listener):
        RenderDialog.__init__(self, app, project)
        self.listener = listener
        unused_extension, muxer, vencoder, aencoder = file_format
        set_combo_value(self.muxer_combo, Gst.ElementFactory.find(muxer))
        set_combo_value(self.video_encoder_combo, Gst.ElementFactory.find(vencoder))
        set_combo_value(self.audio_encoder_combo, Gst.ElementFactory.find(aencoder))
        # After choosing the encoders, which reset the quality.
        self.apply_vcodecsettings_quality(quality)

    def start(self, path):
        """Starts rendering, returns whether it started."""
        # pylint: disable=protected-access
        self._RenderDialog__replace_proxies()
        self._RenderDialog__unset_effect_preview_props()
        self.outfile = Gst.filename_to_uri(path)
        self.app.settings.lastExportFolder = os.path.dirname(path)
        self.app.settings.store_settings()
        self.project.set_rendering(True)
        self._pipeline.set_render_settings(self.outfile, self.project.container_profile)
        if not self.start_action():
            self._shut_down()
            return False
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        self._gst_signal_handlers_ids[bus] = bus.connect("message", self._bus_message_cb)
        self.project.pipeline.connect("position", self._update_position_cb)
        return True

    def destroy(self):
        self.project.disconnect_by_func(self._project_video_size_changed_cb)
        RenderDialog.destroy(self)

    def cancel(self):
        if self._is_rendering:
            self._shut_down()
        self.app.simple_uninhibit(RenderDialog.INHIBIT_REASON)

    def _bus_message_cb(self, unused_bus, message):
        if message.type == Gst.MessageType.EOS:
            self._shut_down()
            self.app.simple_uninhibit(RenderDialog.INHIBIT_REASON)
            self._maybe_play_finished_sound()
            self.listener.render_done()
        elif message.type == Gst.MessageType.ERROR:
            error, details = message.parse_error()
            self.cancel()
            self.listener.render_failed(error, details)
        elif message.type == Gst.MessageType.STATE_CHANGED and message.src == self._pipeline:
            unused_prev, state, pending = message.parse_state_changed()
            if pending == Gst.State.VOID_PENDING:
                if state == Gst.State.PLAYING:
                    self.app.simple_inhibit(RenderDialog.INHIBIT_REASON,
                                            Gtk.ApplicationInhibitFlags.SUSPEND)

    def _update_position_cb(self, unused_pipeline, position):
        self.current_position = position
        length = self.project.ges_timeline.props.duration
        if not length or not position:
            return
        fraction = min(position, length) / length
        remaining = None
        spent = time.time() - self._time_started
        # Enough time for a meaningful estimate.
        if spent > 3 and fraction > 0.02:
            remaining = int(spent * (1 - fraction) / fraction * Gst.SECOND)
        self.listener.render_progress(fraction, remaining)


class ExportDialog(Gtk.Dialog):
    """The dialog for exporting the video, as in the mockup.

    Attributes:
        app (Pitivi): The app.
        project (Project): The project to export.
    """

    def __init__(self, app, project):
        Gtk.Dialog.__init__(self, title=_("Export video"), modal=True, use_header_bar=False)
        if isinstance(app.gui, Gtk.Window):
            self.set_transient_for(app.gui)
        self.app = app
        self.project = project
        self.file_format = get_file_format()
        self.engine = None
        self.path = None
        self.set_default_size(460, -1)
        self.set_resizable(False)
        self.get_style_context().add_class("spl-export")

        self.stack = Gtk.Stack()
        # Each page has its own height.
        self.stack.set_vhomogeneous(False)
        self.stack.connect("notify::visible-child", self.__visible_child_changed_cb)
        self.stack.add_named(self.__create_form(), "form")
        self.stack.add_named(self.__create_progress(), "progress")
        self.stack.add_named(self.__create_done(), "done")
        self.get_content_area().pack_start(self.stack, True, True, 0)
        self.get_content_area().props.margin = SPACING * 2
        self.stack.show_all()
        self.__update_summary()
        self.connect("delete-event", self.__delete_event_cb)

    def __visible_child_changed_cb(self, unused_stack, unused_pspec):
        # The window shrinks to the height of the page.
        self.resize(self.get_allocated_width(), 1)

    # The form.

    def __create_form(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)

        title = Gtk.Label(xalign=0)
        title.set_markup("<b><big>%s</big></b>" % GLib.markup_escape_text(_("Export video")))
        box.pack_start(title, False, False, 0)
        explanation = Gtk.Label(
            label=_("Creates the final file for watching and sharing. Your project does not "
                    "change: to keep editing it later, use Save."),
            xalign=0)
        explanation.set_line_wrap(True)
        explanation.set_max_width_chars(50)
        explanation.get_style_context().add_class("dim-label")
        box.pack_start(explanation, False, False, 0)

        box.pack_start(self.__field_label(_("Name of the video")), False, False, PADDING)
        self.name_entry = Gtk.Entry()
        self.name_entry.set_text(self.project.name or _("My video"))
        self.name_entry.set_activates_default(True)
        self.name_entry.connect("changed", lambda unused_entry: self.__update_buttons())
        box.pack_start(self.name_entry, False, False, 0)

        box.pack_start(self.__field_label(_("Save in")), False, False, PADDING)
        self.folder_button = Gtk.FileChooserButton(title=_("Choose the folder"),
                                                   action=Gtk.FileChooserAction.SELECT_FOLDER)
        self.folder_button.set_filename(get_default_folder(self.app))
        box.pack_start(self.folder_button, False, False, 0)

        box.pack_start(self.__field_label(_("Quality")), False, False, PADDING)
        self.quality_buttons = {}
        group = None
        for quality, name, description in (
                (STANDARD, _("Standard"), _("Ideal for social networks and messages. A lighter file.")),
                (HIGH, _("High"), _("The sharpest. A bigger file, and it takes a bit longer."))):
            button = Gtk.RadioButton.new_from_widget(group)
            group = group or button
            label = Gtk.Label(xalign=0)
            label.set_markup("<b>%s</b>\n<span alpha=\"70%%\">%s</span>" % (
                GLib.markup_escape_text(name), GLib.markup_escape_text(description)))
            label.set_line_wrap(True)
            button.add(label)
            button.connect("toggled", lambda unused_button: self.__update_summary())
            box.pack_start(button, False, False, 0)
            self.quality_buttons[quality] = button

        self.summary_label = Gtk.Label(xalign=0)
        self.summary_label.set_line_wrap(True)
        self.summary_label.get_style_context().add_class("dim-label")
        box.pack_start(self.summary_label, False, False, PADDING)

        if self.file_format and self.file_format != MP4:
            note = Gtk.Label(
                label=_("This computer can't create MP4 files, the video will be a WebM file."),
                xalign=0)
            note.set_line_wrap(True)
            box.pack_start(note, False, False, 0)

        buttons = Gtk.Box(spacing=SPACING)
        buttons.props.halign = Gtk.Align.END
        buttons.props.margin_top = SPACING
        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", lambda unused_button: self.destroy())
        buttons.pack_start(cancel_button, False, False, 0)
        self.export_button = Gtk.Button(label=_("Export video"))
        self.export_button.get_style_context().add_class("spl-accent")
        self.export_button.set_can_default(True)
        self.export_button.connect("clicked", self.__export_clicked_cb)
        buttons.pack_start(self.export_button, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        self.__update_buttons()
        return box

    @staticmethod
    def __field_label(text):
        label = Gtk.Label(xalign=0)
        label.set_markup("<b>%s</b>" % GLib.markup_escape_text(text))
        return label

    def get_quality(self):
        for quality, button in self.quality_buttons.items():
            if button.get_active():
                return quality
        return STANDARD

    def __update_buttons(self):
        name = self.name_entry.get_text().strip()
        valid = bool(name) and "/" not in name and bool(self.file_format)
        self.export_button.set_sensitive(valid)

    def __update_summary(self):
        width, height = self.project.videowidth, self.project.videoheight
        kind = get_format(width, height)
        if kind:
            name, ratio, unused_use = FORMAT_NAMES[kind]
            shape = "%s %s" % (name, ratio)
        else:
            shape = "%d × %d" % (width, height)
        duration = self.project.ges_timeline.props.duration
        framerate = self.project.videorate.num / self.project.videorate.denom
        size = estimate_size(width, height, framerate, duration, self.get_quality())
        self.summary_label.set_markup(
            _("Format: <b>%s</b> · Duration: <b>%s</b> · Approx. size: <b>%s</b>") % (
                GLib.markup_escape_text(shape), format_duration(duration),
                GLib.markup_escape_text(format_size(size))))

    def __export_clicked_cb(self, unused_button):
        folder = self.folder_button.get_filename() or get_default_folder(self.app)
        name = self.name_entry.get_text().strip()
        self.path = get_unique_path(folder, name, self.file_format[0])
        self.engine = RenderEngine(self.app, self.project, self.file_format,
                                   self.get_quality(), self)
        self.progress_file_label.set_markup(
            _("Creating <b>%s</b> in %s. Your project does not change.") % (
                GLib.markup_escape_text(os.path.basename(self.path)),
                GLib.markup_escape_text(os.path.basename(folder) or folder)))
        self.progress_bar.set_fraction(0)
        self.progress_percent_label.set_text("0 %")
        self.progress_left_label.set_text(_("Calculating…"))
        self.stack.set_visible_child_name("progress")
        if not self.engine.start(self.path):
            self.render_failed(_("The output file could not be created."), None)

    # The progress.

    def __create_progress(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        title = Gtk.Label(xalign=0)
        title.set_markup("<b><big>%s</big></b>" % GLib.markup_escape_text(_("Exporting your video…")))
        box.pack_start(title, False, False, 0)
        self.progress_file_label = Gtk.Label(xalign=0)
        self.progress_file_label.set_line_wrap(True)
        self.progress_file_label.set_max_width_chars(50)
        self.progress_file_label.get_style_context().add_class("dim-label")
        box.pack_start(self.progress_file_label, False, False, 0)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.get_style_context().add_class("spl-progress")
        box.pack_start(self.progress_bar, False, False, PADDING)
        meta = Gtk.Box()
        self.progress_percent_label = Gtk.Label()
        meta.pack_start(self.progress_percent_label, False, False, 0)
        self.progress_left_label = Gtk.Label()
        self.progress_left_label.get_style_context().add_class("dim-label")
        meta.pack_end(self.progress_left_label, False, False, 0)
        box.pack_start(meta, False, False, 0)
        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.props.halign = Gtk.Align.END
        cancel_button.props.margin_top = SPACING
        cancel_button.connect("clicked", self.__cancel_clicked_cb)
        box.pack_start(cancel_button, False, False, 0)
        return box

    def render_progress(self, fraction, remaining):
        self.progress_bar.set_fraction(fraction)
        self.progress_percent_label.set_text("%d %%" % int(fraction * 100))
        if remaining is not None:
            eta = beautify_eta(remaining)
            self.progress_left_label.set_text(_("About %s left") % eta if eta else _("Almost done"))

    def __cancel_clicked_cb(self, unused_button):
        self.__stop()
        # The unfinished file is useless.
        if self.path and os.path.exists(self.path):
            os.remove(self.path)
        self.stack.set_visible_child_name("form")

    def __stop(self):
        if self.engine:
            self.engine.cancel()
            self.engine.destroy()
            self.engine = None

    # The end.

    def __create_done(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        self.done_icon = Gtk.Image()
        self.done_icon.set_pixel_size(48)
        box.pack_start(self.done_icon, False, False, 0)
        self.done_title = Gtk.Label()
        self.done_title.set_justify(Gtk.Justification.CENTER)
        box.pack_start(self.done_title, False, False, 0)
        self.done_label = Gtk.Label()
        self.done_label.set_line_wrap(True)
        self.done_label.set_max_width_chars(50)
        self.done_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.done_label.set_selectable(True)
        self.done_label.set_justify(Gtk.Justification.CENTER)
        self.done_label.get_style_context().add_class("dim-label")
        box.pack_start(self.done_label, False, False, 0)
        buttons = Gtk.Box(spacing=SPACING)
        buttons.props.halign = Gtk.Align.CENTER
        buttons.props.margin_top = SPACING
        self.open_folder_button = Gtk.Button(label=_("Open folder"))
        self.open_folder_button.connect("clicked", self.__open_folder_clicked_cb)
        buttons.pack_start(self.open_folder_button, False, False, 0)
        done_button = Gtk.Button(label=_("Done"))
        done_button.get_style_context().add_class("spl-accent")
        done_button.connect("clicked", lambda unused_button: self.destroy())
        buttons.pack_start(done_button, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        return box

    def render_done(self):
        self.__stop()
        self.done_icon.set_from_icon_name("object-select-symbolic", Gtk.IconSize.DIALOG)
        self.done_title.set_markup("<b><big>%s</big></b>" % GLib.markup_escape_text(
            _("Your video is ready")))
        self.done_label.set_text(self.path)
        self.open_folder_button.show()
        self.stack.set_visible_child_name("done")
        if not self.is_active():
            self.app.system.desktop_message(_("Your video is ready"), os.path.basename(self.path),
                                            "pitivi")

    def render_failed(self, error, unused_details):
        self.__stop()
        if self.path and os.path.exists(self.path):
            os.remove(self.path)
        self.done_icon.set_from_icon_name("dialog-warning-symbolic", Gtk.IconSize.DIALOG)
        self.done_title.set_markup("<b><big>%s</big></b>" % GLib.markup_escape_text(
            _("The video could not be exported")))
        self.done_label.set_text(str(error))
        self.open_folder_button.hide()
        self.stack.set_visible_child_name("done")

    def __open_folder_clicked_cb(self, unused_button):
        folder_uri = Gst.filename_to_uri(os.path.dirname(self.path))
        Gio.AppInfo.launch_default_for_uri(folder_uri, None)

    def __delete_event_cb(self, unused_dialog, unused_event):
        if self.stack.get_visible_child_name() == "progress":
            # Closing the window while exporting cancels it.
            self.__cancel_clicked_cb(None)
        self.__stop()
        return False

