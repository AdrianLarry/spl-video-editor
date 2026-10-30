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
"""A small toolbar floating over the viewer for the selected clip."""
from gettext import gettext as _

from gi.repository import GES
from gi.repository import Gtk

from pitivi.clip_properties.crop import Crop
from pitivi.clip_properties.crop import get_crop
from pitivi.clip_properties.crop import apply_crop
from pitivi.undo.timeline import CommitTimelineFinalizingAction
from pitivi.utils.ui import SPACING


def _button(icon_name, label, tooltip):
    button = Gtk.Button()
    box = Gtk.Box(spacing=SPACING // 2)
    box.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON), False, False, 0)
    if label:
        box.pack_start(Gtk.Label(label=label), False, False, 0)
    button.add(box)
    button.set_tooltip_text(tooltip)
    button.set_relief(Gtk.ReliefStyle.NONE)
    return button


class ClipToolbar(Gtk.Box):
    """Crop, fit and turn the selected clip, from the viewer.

    Attributes:
        crop_overlay (CropOverlay): The overlay for cropping.
    """

    def __init__(self, app, crop_overlay):
        Gtk.Box.__init__(self, spacing=2)
        self.app = app
        self.crop_overlay = crop_overlay
        self.crop_overlay.connect("finished", self.__crop_finished_cb)
        self.clip = None
        self.get_style_context().add_class("spl-clip-toolbar")
        self.props.halign = Gtk.Align.CENTER
        self.props.valign = Gtk.Align.START
        self.props.margin_top = SPACING

        self.tools = Gtk.Box(spacing=2)
        self.crop_button = _button("image-crop-symbolic", _("Crop"),
                                   _("Crop the sides of the image"))
        self.crop_button.connect("clicked", self.__crop_clicked_cb)
        self.tools.pack_start(self.crop_button, False, False, 0)
        self.fit_button = _button("zoom-fit-best-symbolic", _("Fit"),
                                  _("Show the whole image. There can be bars on the sides."))
        self.fit_button.connect("clicked", self.__fit_clicked_cb)
        self.tools.pack_start(self.fit_button, False, False, 0)
        self.more_button = Gtk.MenuButton()
        self.more_button.add(Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.BUTTON))
        self.more_button.set_tooltip_text(_("More"))
        self.more_button.set_relief(Gtk.ReliefStyle.NONE)
        self.more_button.set_popover(self.__create_more_popover())
        self.tools.pack_start(self.more_button, False, False, 0)
        self.pack_start(self.tools, False, False, 0)

        self.cropping = Gtk.Box(spacing=2)
        self.done_button = _button("object-select-symbolic", _("Done"), _("Crop the image"))
        self.done_button.get_style_context().add_class("spl-accent")
        self.done_button.connect("clicked", lambda unused_button: self.__finish_crop(True))
        self.cropping.pack_start(self.done_button, False, False, 0)
        self.cancel_button = _button("window-close-symbolic", _("Cancel"), _("Leave the image as it was"))
        self.cancel_button.connect("clicked", lambda unused_button: self.__finish_crop(False))
        self.cropping.pack_start(self.cancel_button, False, False, 0)
        self.pack_start(self.cropping, False, False, 0)

        self.show_all()
        self.cropping.hide()
        self.set_no_show_all(True)
        self.hide()

    def __create_more_popover(self):
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.props.margin = SPACING // 2
        self.rotate_button = Gtk.ModelButton(text=_("Rotate right"))
        self.rotate_button.connect("clicked", self.__transformation_clicked_cb, "rotate_right_button")
        box.pack_start(self.rotate_button, False, False, 0)
        self.mirror_button = Gtk.ModelButton(text=_("Mirror horizontally"))
        self.mirror_button.connect("clicked", self.__transformation_clicked_cb,
                                   "mirror_horizontally_button")
        box.pack_start(self.mirror_button, False, False, 0)
        self.uncrop_button = Gtk.ModelButton(text=_("Remove the crop"))
        self.uncrop_button.connect("clicked", self.__uncrop_clicked_cb)
        box.pack_start(self.uncrop_button, False, False, 0)
        box.show_all()
        popover.add(box)
        return popover

    def set_clip(self, clip):
        """Shows the tools for the clip, or hides them for None."""
        if self.crop_overlay.active and self.crop_overlay.clip != clip:
            self.__finish_crop(False)
        source = clip.find_track_element(None, GES.VideoSource) if clip else None
        # Titles and colors are not cropped.
        self.clip = clip if isinstance(source, GES.VideoUriSource) else None
        self.set_visible(self.clip is not None)
        if self.clip:
            self.uncrop_button.set_sensitive(not get_crop(self.clip).is_empty())

    def stop_cropping(self):
        """Leaves the crop as it was, if cropping."""
        if self.crop_overlay.active:
            self.__finish_crop(False)

    def __crop_clicked_cb(self, unused_button):
        if not self.clip:
            return
        self.crop_overlay.start(self.clip)
        self.tools.hide()
        self.cropping.show()

    def __finish_crop(self, apply):
        if apply:
            self.crop_overlay.apply()
        else:
            self.crop_overlay.cancel()

    def __crop_finished_cb(self, unused_crop_overlay):
        # Also when undoing while cropping.
        self.cropping.hide()
        self.tools.show()
        if self.clip:
            self.uncrop_button.set_sensitive(not get_crop(self.clip).is_empty())

    def __transformation_properties(self):
        return self.app.gui.editor.clipconfig.transformation_expander

    def __fit_clicked_cb(self, unused_button):
        self.__transformation_properties().fit_button.clicked()

    def __transformation_clicked_cb(self, unused_button, name):
        getattr(self.__transformation_properties(), name).clicked()

    def __uncrop_clicked_cb(self, unused_button):
        if not self.clip:
            return
        pipeline = self.app.project_manager.current_project.pipeline
        with self.app.action_log.started("crop",
                                         finalizing_action=CommitTimelineFinalizingAction(pipeline),
                                         toplevel=True):
            apply_crop(self.clip, Crop())
        self.uncrop_button.set_sensitive(False)
