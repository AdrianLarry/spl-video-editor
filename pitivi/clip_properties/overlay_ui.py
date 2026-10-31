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
"""The widgets for adding the overlays and changing their shapes."""
import math
from gettext import gettext as _
from typing import Callable
from typing import Optional

import cairo
from gi.repository import GES
from gi.repository import Gtk

from pitivi.clip_properties.overlay import get_shape_effect
from pitivi.clip_properties.overlay import get_shape_name
from pitivi.clip_properties.overlay import get_values
from pitivi.clip_properties.overlay import set_values
from pitivi.undo.timeline import CommitTimelineFinalizingAction
from pitivi.utils.loggable import Loggable
from pitivi.utils.shapes import BOX
from pitivi.utils.shapes import SHAPES
from pitivi.utils.shapes import Style
from pitivi.utils.ui import argb_to_gdk_rgba
from pitivi.utils.ui import gdk_rgba_to_argb
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING

# The colors offered, the first ones seen in tutorials.
SHAPE_COLORS = (0xFFD9531E, 0xFFFF3B30, 0xFFFFD166, 0xFF7EE0C3, 0xFF8EC5FF, 0xFFFFFFFF, 0xFF141414)
MIN_LINE_WIDTH = 2
MAX_LINE_WIDTH = 40
MAX_CORNER_RADIUS = 120


def draw_shape_icon(cr, shape, width, height, color=(1, 1, 1, 1), line_width=2.0):
    """Draws a small picture of the shape, filling the area."""
    margin = line_width + 2
    if shape.kind == BOX:
        start, end = (margin - 1, margin + height * 0.08), (width - margin + 1, height - margin - height * 0.08)
    else:
        start, end = (margin, height - margin), (width - margin, margin)
    # Slightly rounded: small, a rounder frame would look as a circle.
    shape.draw(cr, start, end, Style(color, line_width, line_width * 1.5))


def _shape_image(shape, size=16):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    draw_shape_icon(cr, shape, size, size, color=(0.85, 0.85, 0.87, 1), line_width=1.6)
    return Gtk.Image.new_from_surface(surface)


class ShapeMenuButton(Gtk.MenuButton):
    """A button offering the shapes, to add one as an overlay.

    Attributes:
        callback (Callable[[str], None]): Called with the name of the shape chosen.
    """

    def __init__(self, callback: Callable[[str], None]):
        Gtk.MenuButton.__init__(self)
        self.callback = callback
        box = Gtk.Box(spacing=PADDING)
        box.pack_start(_shape_image(SHAPES["frame"]), False, False, 0)
        box.pack_start(Gtk.Label(label=_("Shape")), False, False, 0)
        box.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU),
                       False, False, 0)
        self.add(box)
        self.set_tooltip_text(_("Add a frame, a circle or an arrow over the video"))

        popover = Gtk.Popover()
        shapes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        shapes_box.props.margin = PADDING
        for shape in SHAPES.values():
            button = Gtk.Button()
            button.set_relief(Gtk.ReliefStyle.NONE)
            row = Gtk.Box(spacing=SPACING)
            row.pack_start(_shape_image(shape, 20), False, False, 0)
            row.pack_start(Gtk.Label(label=shape.label, xalign=0), True, True, 0)
            button.add(row)
            button.connect("clicked", self.__shape_clicked_cb, shape.name)
            shapes_box.pack_start(button, False, False, 0)
        shapes_box.show_all()
        popover.add(shapes_box)
        self.set_popover(popover)
        box.show_all()

    def __shape_clicked_cb(self, unused_button, shape_name):
        self.get_popover().popdown()
        self.callback(shape_name)


class OverlayProperties(Gtk.Expander, Loggable):
    """Changes the shape of an overlay: its kind, color and line."""

    def __init__(self, app):
        Gtk.Expander.__init__(self)
        Loggable.__init__(self)
        self.app = app
        self.clip: Optional[GES.Clip] = None
        self.__effect = None
        self.__updating = False
        self.set_label(_("Shape"))
        self.set_expanded(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PADDING)
        box.props.margin = SPACING
        self.add(box)

        self.shape_buttons = {}
        shapes_box = Gtk.Box(spacing=2)
        shapes_box.get_style_context().add_class("linked")
        group = None
        for shape in SHAPES.values():
            button = Gtk.RadioButton.new_from_widget(group)
            group = group or button
            button.set_mode(False)
            row = Gtk.Box(spacing=PADDING)
            row.pack_start(_shape_image(shape), False, False, 0)
            row.pack_start(Gtk.Label(label=shape.label), False, False, 0)
            button.add(row)
            button.set_tooltip_text(shape.label)
            button.connect("toggled", self.__shape_toggled_cb, shape.name)
            shapes_box.pack_start(button, False, False, 0)
            self.shape_buttons[shape.name] = button
        box.pack_start(shapes_box, False, False, 0)

        color_label = Gtk.Label(label=_("Color"), xalign=0)
        color_label.props.margin_top = SPACING
        box.pack_start(color_label, False, False, 0)
        colors_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                                 homogeneous=False, column_spacing=0, row_spacing=0)
        colors_box.set_max_children_per_line(len(SHAPE_COLORS) + 1)
        self.color_buttons = {}
        for argb in SHAPE_COLORS:
            button = self.__create_color_button(argb)
            colors_box.add(button)
            self.color_buttons[argb] = button
        self.other_color_button = Gtk.ColorButton(use_alpha=False)
        self.other_color_button.set_title(_("Choose a color"))
        self.other_color_button.set_tooltip_text(_("Choose another color"))
        self.other_color_button.connect("color-set", self.__other_color_set_cb)
        other_color_box = Gtk.Box(spacing=PADDING)
        other_color_box.pack_start(self.other_color_button, False, False, 0)
        other_color_box.pack_start(Gtk.Label(label=_("Other")), False, False, 0)
        colors_box.add(other_color_box)
        box.pack_start(colors_box, False, False, 0)

        self.line_width_scale, line_width_box = self.__create_scale(
            _("Line width"), MIN_LINE_WIDTH, MAX_LINE_WIDTH, "line-width")
        box.pack_start(line_width_box, False, False, 0)
        box.pack_start(self.line_width_scale, False, False, 0)
        self.corner_scale, self.corner_box = self.__create_scale(
            _("Rounded corners"), 0, MAX_CORNER_RADIUS, "corner-radius")
        box.pack_start(self.corner_box, False, False, 0)
        box.pack_start(self.corner_scale, False, False, 0)

        hint = Gtk.Label(label=_("Drag the shape in the viewer to place it, its handles to resize it."),
                         xalign=0, wrap=True)
        hint.get_style_context().add_class("dim-label")
        hint.props.margin_top = SPACING
        box.pack_start(hint, False, False, 0)
        box.show_all()
        self.set_no_show_all(True)
        self.hide()

    def __create_color_button(self, argb):
        drawing_area = Gtk.DrawingArea()
        drawing_area.set_size_request(22, 22)
        drawing_area.connect("draw", self.__draw_color_cb, argb)
        button = Gtk.ToggleButton()
        button.props.relief = Gtk.ReliefStyle.NONE
        button.add(drawing_area)
        button.set_tooltip_text(_("Use this color"))
        button.connect("toggled", self.__color_toggled_cb, argb)
        return button

    @staticmethod
    def __draw_color_cb(drawing_area, cr, argb):
        width = drawing_area.get_allocated_width()
        height = drawing_area.get_allocated_height()
        cr.arc(width / 2, height / 2, min(width, height) / 2 - 1, 0, 2 * math.pi)
        rgba = argb_to_gdk_rgba(argb)
        cr.set_source_rgb(rgba.red, rgba.green, rgba.blue)
        cr.fill_preserve()
        # A border, so that the colors close to the background are seen.
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.8)
        cr.set_line_width(1)
        cr.stroke()

    def __create_scale(self, title, lower, upper, prop):
        label = Gtk.Label(label=title, xalign=0, hexpand=True)
        value_label = Gtk.Label()
        header = Gtk.Box()
        header.props.margin_top = SPACING
        header.pack_start(label, True, True, 0)
        header.pack_start(value_label, False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lower, upper, 1)
        scale.set_draw_value(False)
        scale.value_label = value_label
        scale.connect("value-changed", self.__scale_changed_cb, prop)
        return scale, header

    def set_clip(self, clip: Optional[GES.Clip]) -> None:
        """Shows the properties of the overlay, or hides them for None."""
        if self.__effect:
            self.__effect.disconnect_by_func(self.__effect_changed_cb)
            self.__effect = None
        self.clip = clip
        if clip:
            self.__effect = get_shape_effect(clip)
            if self.__effect:
                self.__effect.connect("deep-notify", self.__effect_changed_cb)
            self.__update()
        self.set_visible(clip is not None)

    def __effect_changed_cb(self, unused_effect, unused_element, unused_pspec):
        self.__update()

    def __update(self):
        if not self.clip or not self.clip.get_layer():
            # Removed, as when undoing.
            return
        values = get_values(self.clip)
        if "color" not in values:
            return
        self.__updating = True
        try:
            button = self.shape_buttons.get(values["shape"])
            if button:
                button.set_active(True)
            for argb, color_button in self.color_buttons.items():
                color_button.set_active(argb == values["color"])
            self.other_color_button.set_rgba(argb_to_gdk_rgba(values["color"]))
            for scale, prop in ((self.line_width_scale, "line-width"),
                                (self.corner_scale, "corner-radius")):
                scale.set_value(values[prop])
                scale.value_label.set_text("%d" % round(values[prop]))
            shape = SHAPES.get(values["shape"])
            has_corners = bool(shape and shape.has_corners)
            self.corner_box.set_visible(has_corners)
            self.corner_scale.set_visible(has_corners)
        finally:
            self.__updating = False

    def __change(self, values, mergeable=False):
        if self.__updating or not self.clip:
            return
        pipeline = self.app.project_manager.current_project.pipeline
        with self.app.action_log.started("overlay change", toplevel=True, mergeable=mergeable,
                                         finalizing_action=CommitTimelineFinalizingAction(pipeline)):
            if "shape" in values:
                get_shape_effect(self.clip).set_child_property("shape", values["shape"])
            set_values(self.clip, values)

    def __shape_toggled_cb(self, button, shape_name):
        if button.get_active() and shape_name != get_shape_name(self.clip):
            self.__change({"shape": shape_name})

    def __color_toggled_cb(self, button, argb):
        if self.__updating:
            return
        if button.get_active():
            self.__change({"color": argb})
        else:
            # A color stays chosen until another one is.
            self.__updating = True
            button.set_active(get_values(self.clip).get("color") == argb)
            self.__updating = False

    def __other_color_set_cb(self, button):
        self.__change({"color": gdk_rgba_to_argb(button.get_rgba()) | 0xFF000000})

    def __scale_changed_cb(self, scale, prop):
        scale.value_label.set_text("%d" % round(scale.get_value()))
        self.__change({prop: float(scale.get_value())}, mergeable=True)
