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
"""Widget to control the volume and the sound fades of a clip."""
from gettext import gettext as _
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Tuple

from gi.repository import GES
from gi.repository import GLib
from gi.repository import Gst
from gi.repository import GstController
from gi.repository import Gtk

from pitivi.undo.timeline import CommitTimelineFinalizingAction
from pitivi.utils.loggable import Loggable
from pitivi.utils.ui import format_fade_duration
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING

# The volume property of the audio sources goes from 0 to 10. The control
# source of its "direct" binding holds the volume divided by this.
VOLUME_RANGE = 10.0
# The highest volume offered, in percents.
MAX_VOLUME_PERCENT = 200
# The longest fade offered, in seconds.
MAX_FADE_SECONDS = 10
# Values closer than this are considered equal.
EPSILON = 1e-6


class Envelope(NamedTuple):
    """A volume which rises from silence and falls back to silence.

    Attributes:
        volume (float): The volume, 1.0 being the original volume.
        fade_in (int): The duration of the rise from silence, in nanoseconds.
        fade_out (int): The duration of the fall to silence, in nanoseconds.
    """

    volume: float
    fade_in: int
    fade_out: int


def envelope_keyframes(envelope: Envelope, start: int, end: int) -> List[Tuple[int, float]]:
    """Returns the keyframes of the volume control source for the envelope.

    Args:
        envelope: The volume and the fades.
        start: The timestamp where the envelope starts, the inpoint of the source.
        end: The timestamp where the envelope ends.
    """
    value = envelope.volume / VOLUME_RANGE
    duration = end - start
    fade_in = max(0, min(envelope.fade_in, duration))
    fade_out = max(0, min(envelope.fade_out, duration - fade_in))

    keyframes = []
    if fade_in:
        keyframes.append((start, 0.0))
    keyframes.append((start + fade_in, value))
    keyframes.append((end - fade_out, value))
    if fade_out:
        keyframes.append((end, 0.0))
    # Without fades the volume is constant and the duplicates are dropped.
    return sorted(dict(keyframes).items())


def read_envelope(keyframes: List[Tuple[int, float]]) -> Optional[Envelope]:
    """Returns the envelope described by the keyframes, if any.

    The first and last keyframes are taken as the ends of the envelope, so
    the envelope is still found after the clip has been trimmed.

    Args:
        keyframes: The timestamps and values of the volume control source,
            sorted by timestamp.

    Returns:
        The envelope, or None if the keyframes have been edited freely.
    """
    if len(keyframes) < 2:
        return None

    values = [value for unused_timestamp, value in keyframes]
    first, last = 0, len(keyframes) - 1
    if values[first] < EPSILON:
        first = 1
    if values[last] < EPSILON and last > first:
        last -= 1
    plateau = values[first:last + 1]
    if not plateau or any(abs(value - plateau[0]) > EPSILON for value in plateau):
        return None

    if plateau[0] < EPSILON:
        # Silent all along.
        return Envelope(0.0, 0, 0)

    fade_in = keyframes[first][0] - keyframes[0][0]
    fade_out = keyframes[-1][0] - keyframes[last][0]
    # The values can be stored with a single precision.
    volume = round(plateau[0] * VOLUME_RANGE, 6)
    return Envelope(volume, fade_in, fade_out)


class SoundProperties(Gtk.Expander, Loggable):
    """Widget for configuring the volume and the sound fades of a clip.

    Attributes:
        app (Pitivi): The app.
        source (Optional[GES.AudioSource]): The source being configured.
    """

    def __init__(self, app):
        Gtk.Expander.__init__(self)
        Loggable.__init__(self)
        self.app = app
        self.source: Optional[GES.AudioSource] = None
        self._updating_ui = False
        self._writing = False
        self._control_source = None
        self._handler_ids = []

        self.set_label(_("Sound"))
        self.set_expanded(True)

        grid = Gtk.Grid(row_spacing=PADDING, column_spacing=PADDING)
        grid.props.border_width = SPACING

        # As in the approved mockup: each label with its value on the
        # right, and the slider below.
        self.volume_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, MAX_VOLUME_PERCENT, 1)
        self.volume_scale.add_mark(100, Gtk.PositionType.BOTTOM, None)
        self.fade_in_scale = self.__create_fade_scale()
        self.fade_out_scale = self.__create_fade_scale()
        rows = ((_("Volume:"), self.volume_scale, self.__format_volume),
                (_("Fade in from silence:"), self.fade_in_scale, format_fade_duration),
                (_("Fade out to silence:"), self.fade_out_scale, format_fade_duration))
        row = 0
        for text, scale, format_value in rows:
            scale.set_draw_value(False)
            scale.set_hexpand(True)
            value_label = Gtk.Label(halign=Gtk.Align.END)
            scale.connect("value-changed", self.__update_value_label, value_label, format_value)
            scale.connect("value-changed", self.__envelope_widget_changed_cb)
            self.__update_value_label(scale, value_label, format_value)
            grid.attach(Gtk.Label(label=text, xalign=0), 0, row, 1, 1)
            grid.attach(value_label, 1, row, 1, 1)
            grid.attach(scale, 0, row + 1, 2, 1)
            row += 2
            if scale is self.volume_scale:
                self.mute_button = Gtk.ToggleButton(label=_("Mute"))
                self.mute_button.set_image(Gtk.Image.new_from_icon_name(
                    "audio-volume-muted-symbolic", Gtk.IconSize.BUTTON))
                self.mute_button.set_always_show_image(True)
                self.mute_button.props.halign = Gtk.Align.START
                self.mute_button.connect("toggled", self.__mute_toggled_cb)
                grid.attach(self.mute_button, 0, row, 2, 1)
                row += 1

        self.custom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PADDING)
        custom_label = Gtk.Label(
            label=_("The volume has been edited on the timeline."), xalign=0)
        custom_label.set_line_wrap(True)
        reset_button = Gtk.Button(label=_("Use a simple volume"))
        reset_button.props.halign = Gtk.Align.START
        reset_button.connect("clicked", self.__reset_clicked_cb)
        self.custom_box.pack_start(custom_label, False, False, 0)
        self.custom_box.pack_start(reset_button, False, False, 0)
        grid.attach(self.custom_box, 0, row, 2, 1)

        self.add(grid)
        self.show_all()
        self.custom_box.set_no_show_all(True)
        self.custom_box.hide()
        self.hide()

    @staticmethod
    def __create_fade_scale():
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, MAX_FADE_SECONDS, 0.1)
        scale.set_digits(1)
        return scale

    @staticmethod
    def __format_volume(value):
        return "%d %%" % round(value)

    @staticmethod
    def __update_value_label(scale, label, format_value):
        label.set_markup("<b>%s</b>" % GLib.markup_escape_text(format_value(scale.get_value())))

    def set_source(self, source: Optional[GES.AudioSource]):
        """Sets the audio source to be configured, or None to hide."""
        if self.source:
            for obj, handler_id in self._handler_ids:
                obj.disconnect(handler_id)
        self._handler_ids = []
        self._control_source = None
        self.source = source
        if not source:
            self.hide()
            return

        self._handler_ids.append((source, source.connect("deep-notify", self.__deep_notify_cb)))
        for signal in ("notify::duration", "notify::in-point"):
            self._handler_ids.append((source, source.connect(signal, self.__source_changed_cb)))
        self._handler_ids.append((source, source.connect(
            "control-binding-added", self.__binding_changed_cb)))
        self.__watch_control_source()
        self.update()
        self.show()

    def __watch_control_source(self):
        binding = self.source.get_control_binding("volume")
        self._control_source = binding.props.control_source if binding else None
        if self._control_source:
            for signal in ("value-added", "value-changed", "value-removed"):
                self._handler_ids.append((self._control_source, self._control_source.connect(
                    signal, self.__source_changed_cb)))

    def __binding_changed_cb(self, unused_source, unused_binding):
        if not self._control_source:
            self.__watch_control_source()
            self.update()

    def __deep_notify_cb(self, unused_source, unused_element, pspec):
        # The volume changes all the time while playing, if it has keyframes.
        if pspec.name == "mute" and not self._writing:
            self.update()

    def __source_changed_cb(self, *unused_args):
        if not self._writing:
            self.update()

    def _get_keyframes(self):
        if not self._control_source:
            return []
        return [(keyframe.timestamp, keyframe.value)
                for keyframe in self._control_source.get_all()]

    def _get_range(self):
        start = self.source.props.in_point
        return start, start + self.source.props.duration

    def get_envelope(self) -> Optional[Envelope]:
        """Returns the envelope of the volume, or None if edited freely."""
        keyframes = self._get_keyframes()
        if not keyframes:
            res, volume = self.source.get_child_property("volume")
            assert res
            return Envelope(volume, 0, 0)
        return read_envelope(keyframes)

    def update(self):
        """Shows the current volume, fades and mute state of the source."""
        envelope = self.get_envelope()
        start, end = self._get_range()
        max_fade = (end - start) / Gst.SECOND
        res, muted = self.source.get_child_property("mute")
        assert res

        self._updating_ui = True
        try:
            self.mute_button.set_active(muted)
            for scale in (self.fade_in_scale, self.fade_out_scale):
                scale.set_range(0, min(max_fade, MAX_FADE_SECONDS))
            if envelope:
                self.volume_scale.set_value(round(envelope.volume * 100))
                self.fade_in_scale.set_value(envelope.fade_in / Gst.SECOND)
                self.fade_out_scale.set_value(envelope.fade_out / Gst.SECOND)
        finally:
            self._updating_ui = False

        for widget in (self.volume_scale, self.fade_in_scale, self.fade_out_scale):
            widget.set_sensitive(envelope is not None)
        self.custom_box.set_visible(envelope is None)

    def set_envelope(self, envelope: Envelope, action_name: str = "Sound volume",
                     mergeable: bool = False):
        """Changes the volume keyframes of the source to the envelope."""
        pipeline = self.app.project_manager.current_project.pipeline
        with self.app.action_log.started(action_name,
                                         finalizing_action=CommitTimelineFinalizingAction(pipeline),
                                         mergeable=mergeable,
                                         toplevel=True):
            self._writing = True
            try:
                if not self._control_source:
                    control_source = GstController.InterpolationControlSource()
                    control_source.props.mode = GstController.InterpolationMode.LINEAR
                    self.source.set_control_source(control_source, "volume", "direct")
                    self.__watch_control_source()
                start, end = self._get_range()
                wanted = dict(envelope_keyframes(envelope, start, end))
                # Remove and set the keyframes one by one, so that the undo
                # system records the changes.
                for timestamp, unused_value in self._get_keyframes():
                    if timestamp not in wanted:
                        self._control_source.unset(timestamp)
                for timestamp, value in wanted.items():
                    self._control_source.set(timestamp, value)
            finally:
                self._writing = False
        self.update()

    def __envelope_widget_changed_cb(self, widget):
        if self._updating_ui:
            return
        envelope = Envelope(self.volume_scale.get_value() / 100,
                            round(self.fade_in_scale.get_value() * Gst.SECOND),
                            round(self.fade_out_scale.get_value() * Gst.SECOND))
        # Consecutive changes of the same widget are undone together.
        action_name = "Sound volume" if widget is self.volume_scale else "Sound fades"
        self.set_envelope(envelope, action_name, mergeable=True)

    def __reset_clicked_cb(self, unused_button):
        # Keep the loudest volume of the curve.
        loudest = max(value for unused_timestamp, value in self._get_keyframes())
        self.set_envelope(Envelope(loudest * VOLUME_RANGE, 0, 0))

    def __mute_toggled_cb(self, button):
        if self._updating_ui:
            return
        pipeline = self.app.project_manager.current_project.pipeline
        with self.app.action_log.started("Sound mute",
                                         finalizing_action=CommitTimelineFinalizingAction(pipeline),
                                         toplevel=True):
            self._writing = True
            try:
                self.source.set_child_property("mute", button.get_active())
            finally:
                self._writing = False
