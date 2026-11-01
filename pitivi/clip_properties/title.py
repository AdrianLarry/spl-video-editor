# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2012, Matas Brazdeikis <matas@brazdeikis.lt>
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
"""Widgets to control title clip properties."""
import html
import os
import time
from gettext import gettext as _
from typing import Optional
from typing import Union

from gi.repository import GES
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Pango

from pitivi.configure import get_ui_dir
from pitivi.dialogs.prefs import PreferencesDialog
from pitivi.settings import GlobalSettings
from pitivi.undo.timeline import FlushSeekFinalizingAction
from pitivi.utils.loggable import Loggable
from pitivi.utils.ui import argb_to_gdk_rgba
from pitivi.utils.ui import gdk_rgba_to_argb
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING
from pitivi.utils.widgets import ColorPickerButton


# The fonts offered: a name and the families, the first one installed being
# used, and the weight.
FONTS = (
    (_("Clear"), "Inter,Cantarell,Ubuntu Sans,Ubuntu,Sans", Pango.Weight.BOLD),
    (_("Classic"), "Georgia,DejaVu Serif,Liberation Serif,Serif", Pango.Weight.BOLD),
    (_("Rounded"), "Nunito,Comfortaa,Varela Round,URW Gothic,Ubuntu,Sans", Pango.Weight.BOLD),
    (_("Handwritten"), "Comic Neue,Purisa,Comic Sans MS,Z003,Serif", Pango.Weight.NORMAL),
    (_("Headline"), "Impact,Anton,Oswald,Nimbus Sans Narrow,Liberation Sans Narrow,Sans",
     Pango.Weight.BOLD),
)
# The text sizes offered, relative to a frame of the reference height,
# so that a text keeps its proportion in any frame.
MIN_TEXT_SIZE = 24
MAX_TEXT_SIZE = 160
DEFAULT_TEXT_SIZE = 72
REFERENCE_FRAME_HEIGHT = 1080
# The text colors offered, as ARGB.
TEXT_COLORS = (0xFFFFFFFF, 0xFFFFD166, 0xFFFF8A5B, 0xFF7EE0C3, 0xFF8EC5FF, 0xFF141414)
BLACK_TEXT_COLOR = 0xFF141414

# Shadow and outline styles for text: (id, label, tooltip, draw_shadow, outline_color)
SHADOW_STYLES = (
    ("flat", _("Flat"), _("Without shadow or outline"), False, 0x00000000),
    ("shadow", _("Shadow"), _("Soft drop shadow"), True, 0x00000000),
    ("outline", _("Outline"), _("Sharp dark outline for high contrast"), False, 0xFF000000),
    ("emboss", _("Relief"), _("Outline with drop shadow"), True, 0xFF000000),
)


def get_font_description(font_index: int, points: float) -> str:
    """Returns the font description of one of the offered fonts."""
    unused_name, families, weight = FONTS[font_index]
    font_desc = Pango.FontDescription()
    font_desc.set_family(families)
    font_desc.set_weight(weight)
    font_desc.set_size(round(points * Pango.SCALE))
    return font_desc.to_string()


def text_size_to_points(size: float, frame_height: int) -> float:
    """Returns the font size for showing a text size in a frame."""
    return size * frame_height / REFERENCE_FRAME_HEIGHT


def points_to_text_size(points: float, frame_height: int) -> float:
    """Returns the text size shown by a font size in a frame."""
    return points * REFERENCE_FRAME_HEIGHT / frame_height


def get_default_font_description(frame_height: int) -> str:
    """Returns the font description for new texts."""
    return get_font_description(0, text_size_to_points(DEFAULT_TEXT_SIZE, frame_height))


def find_font(font_desc: Pango.FontDescription) -> int:
    """Returns the index of the offered font described, or -1."""
    for index, (unused_name, families, unused_weight) in enumerate(FONTS):
        if font_desc.get_family() == families:
            return index
    return -1



GlobalSettings.add_config_option("titleClipLength",
                                 section="user-interface",
                                 key="title-clip-length",
                                 default=5000,
                                 notify=True)

PreferencesDialog.add_numeric_preference("titleClipLength",
                                         section="timeline",
                                         label=_("Title clip duration"),
                                         description=_(
                                             "Default clip length (in milliseconds) of titles when inserting on the timeline."),
                                         lower=1)


class TitleProperties(Gtk.Expander, Loggable):
    """Widget for configuring a title.

    Attributes:
        app (Pitivi): The app.
    """

    def __init__(self, app):
        Loggable.__init__(self)
        Gtk.Expander.__init__(self)
        self.set_label(_("Text"))
        self.set_expanded(True)
        self.app = app
        self.source: Optional[GES.TitleSource] = None
        # Whether the source's props are being set as a result of UI
        # interactions.
        self._setting_props = False
        # Whether the UI is being updated as a result of the props changes
        # performed not by this class.
        self._setting_ui = False
        self._children_props_handler = None
        self._size_change_timeout_id = None
        self._pending_size = None
        self._dragging = False
        self._last_applied_time = 0
        self.shadow_buttons = {}

        self._create_ui()

    def _create_ui(self):
        builder = Gtk.Builder()
        builder.add_from_file(os.path.join(get_ui_dir(), "titleeditor.ui"))
        builder.connect_signals(self)
        # Create UI
        self.add(builder.get_object("box1"))
        self.editing_box = builder.get_object("base_table")

        self.textarea = builder.get_object("textview")

        self.textbuffer = self.textarea.props.buffer
        self.textbuffer.connect("changed", self._text_changed_cb)

        self.font_button = builder.get_object("fontbutton1")
        self.foreground_color_button = builder.get_object("fore_text_color")
        self.background_color_button = builder.get_object("back_color")
        self.outline_color_button = builder.get_object("outline_color")

        self.color_picker_foreground_widget = ColorPickerButton()
        self.color_picker_foreground_widget.show()
        self.color_picker_foreground = builder.get_object("color_picker_foreground")
        self.color_picker_foreground.add(self.color_picker_foreground_widget)
        self.color_picker_foreground_widget.connect("value-changed", self._color_picker_value_changed_cb, self.foreground_color_button, "color")

        self.color_picker_background_widget = ColorPickerButton()
        self.color_picker_background_widget.show()
        self.background_color_picker = builder.get_object("color_picker_background")
        self.background_color_picker.add(self.color_picker_background_widget)
        self.color_picker_background_widget.connect("value-changed", self._color_picker_value_changed_cb, self.background_color_button, "foreground-color")

        self.color_picker_outline_widget = ColorPickerButton()
        self.color_picker_outline_widget.show()
        self.outline_color_picker = builder.get_object("color_picker_outline")
        self.outline_color_picker.add(self.color_picker_outline_widget)
        self.color_picker_outline_widget.connect("value-changed", self._color_picker_value_changed_cb, self.outline_color_button, "outline-color")

        self.drop_shadow_checkbox = builder.get_object("check_drop_shadow")

        # The font button, the background and outline colors, the color
        # pickers and the shadow are not for beginners. They are kept
        # hidden because they reflect the state of the source.
        for widget in (self.font_button, self.foreground_color_button.get_parent(),
                       self.drop_shadow_checkbox):
            widget.set_no_show_all(True)
            widget.hide()

        self.valignment_combo = builder.get_object("valignment")
        self.halignment_combo = builder.get_object("halignment")
        self.x_absolute_spin = builder.get_object("x-absolute")
        self.y_absolute_spin = builder.get_object("y-absolute")

        # TODO: Remove when we upgrade pylint https://github.com/PyCQA/pylint/issues/4962
        # pylint: disable=superfluous-parens
        for value_id, text in (("absolute", _("Absolute")),
                               ("top", _("Top")),
                               ("center", _("Center")),
                               ("bottom", _("Bottom")),
                               ("baseline", _("Baseline"))):
            self.valignment_combo.append(value_id, text)

        for value_id, text in (("absolute", _("Absolute")),
                               ("left", _("Left")),
                               ("center", _("Center")),
                               ("right", _("Right"))):
            self.halignment_combo.append(value_id, text)

        # The position grid replaces the alignment combos and spin buttons.
        # They are kept hidden because they hold the state of the source.
        for widget in (builder.get_object("label7"), self.halignment_combo.get_parent()):
            widget.set_no_show_all(True)
            widget.hide()

        self._create_content_section()
        self._create_style_section()
        self._create_position_grid()

        self.show_all()

    def _add_heading(self, text, subtitle=None):
        label = Gtk.Label(xalign=0)
        label.set_markup("<b>%s</b>" % GLib.markup_escape_text(text))
        label.props.margin_top = SPACING
        self.editing_box.pack_start(label, False, False, 0)
        if subtitle:
            subtitle_label = Gtk.Label(label=subtitle, xalign=0)
            subtitle_label.set_line_wrap(True)
            subtitle_label.get_style_context().add_class("dim-label")
            self.editing_box.pack_start(subtitle_label, False, False, 0)
        return label

    def _create_content_section(self):
        heading = self._add_heading(_("Content"), _("What you write shows at once in the viewer."))
        heading.props.margin_top = 0
        # The text goes below the heading, framed so that it looks editable.
        self.editing_box.remove(self.textarea)
        self.textarea.props.margin_start = PADDING
        self.textarea.props.margin_end = PADDING
        self.textarea.props.margin_top = PADDING
        self.textarea.props.margin_bottom = PADDING
        self.textarea.set_size_request(-1, 40)
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.props.margin_top = PADDING
        frame.add(self.textarea)
        self.editing_box.pack_start(frame, False, False, 0)

    def _create_style_section(self):
        self._add_heading(_("Style"))

        font_label = Gtk.Label(label=_("Font"), xalign=0)
        self.font_combo = Gtk.ComboBoxText()
        for name, unused_families, unused_weight in FONTS:
            self.font_combo.append_text(name)
        self.font_combo.connect("changed", self._font_combo_changed_cb)

        size_label = Gtk.Label(label=_("Size"), xalign=0, hexpand=True)
        self.size_value_label = Gtk.Label()
        self.size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                                   MIN_TEXT_SIZE, MAX_TEXT_SIZE, 1)
        self.size_scale.set_draw_value(False)
        self.size_scale.connect("button-press-event", self._size_scale_button_press_cb)
        self.size_scale.connect("button-release-event", self._size_scale_button_release_cb)
        self.size_scale.connect("value-changed", self._size_scale_value_changed_cb)
        size_box = Gtk.Box()
        size_box.pack_start(size_label, True, True, 0)
        size_box.pack_start(self.size_value_label, False, False, 0)

        color_label = Gtk.Label(label=_("Color"), xalign=0)
        # The colors go on several lines if they do not fit.
        colors_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                                 homogeneous=False, column_spacing=0, row_spacing=0)
        colors_box.set_max_children_per_line(len(TEXT_COLORS) + 1)
        self.color_buttons = {}
        for argb in TEXT_COLORS:
            button = self._create_color_button(argb)
            colors_box.add(button)
            self.color_buttons[argb] = button
        self.other_color_button = Gtk.ColorButton(use_alpha=False)
        self.other_color_button.set_title(_("Choose a color"))
        self.other_color_button.set_tooltip_text(_("Choose another color"))
        self.other_color_button.connect("color-set", self._other_color_set_cb)
        other_color_box = Gtk.Box(spacing=PADDING)
        other_color_box.pack_start(self.other_color_button, False, False, 0)
        other_color_box.pack_start(Gtk.Label(label=_("Other")), False, False, 0)
        colors_box.add(other_color_box)

        shadow_label = Gtk.Label(label=_("Shadow"), xalign=0)
        shadow_box = Gtk.Box(spacing=2)
        shadow_box.get_style_context().add_class("linked")
        self.shadow_buttons = {}
        group = None
        for style_id, label, tooltip, unused_shadow, unused_outline in SHADOW_STYLES:
            button = Gtk.RadioButton.new_from_widget(group)
            group = group or button
            button.set_mode(False)
            button.set_label(label)
            button.set_tooltip_text(tooltip)
            button.connect("toggled", self._shadow_button_toggled_cb, style_id)
            shadow_box.pack_start(button, True, True, 0)
            self.shadow_buttons[style_id] = button

        for widget, margin_top in ((font_label, PADDING), (self.font_combo, PADDING),
                                   (size_box, SPACING), (self.size_scale, 0),
                                   (color_label, SPACING), (colors_box, PADDING),
                                   (shadow_label, SPACING), (shadow_box, PADDING)):
            widget.props.margin_top = margin_top
            self.editing_box.pack_start(widget, False, False, 0)

    def _create_color_button(self, argb):
        drawing_area = Gtk.DrawingArea()
        drawing_area.set_size_request(22, 22)
        drawing_area.connect("draw", self._draw_color_cb, argb)
        button = Gtk.ToggleButton()
        button.props.relief = Gtk.ReliefStyle.NONE
        button.add(drawing_area)
        button.set_tooltip_text(_("Black") if argb == BLACK_TEXT_COLOR else _("Use this color"))
        button.connect("toggled", self._color_button_toggled_cb, argb)
        return button

    @staticmethod
    def _draw_color_cb(drawing_area, cr, argb):
        width = drawing_area.get_allocated_width()
        height = drawing_area.get_allocated_height()
        radius = min(width, height) / 2 - 1
        cr.arc(width / 2, height / 2, radius, 0, 2 * 3.141592653589793)
        rgba = argb_to_gdk_rgba(argb)
        cr.set_source_rgb(rgba.red, rgba.green, rgba.blue)
        cr.fill_preserve()
        # A border, so that the colors close to the background are seen.
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.8)
        cr.set_line_width(1)
        cr.stroke()

    def _create_position_grid(self):
        """Creates the buttons for placing the title in nine positions."""
        self.position_names = names = {("top", "left"): _("Top left"),
                 ("top", "center"): _("Top center"),
                 ("top", "right"): _("Top right"),
                 ("center", "left"): _("Center left"),
                 ("center", "center"): _("Center"),
                 ("center", "right"): _("Center right"),
                 ("bottom", "left"): _("Bottom left"),
                 ("bottom", "center"): _("Bottom center"),
                 ("bottom", "right"): _("Bottom right")}

        self._add_heading(_("Position"), _("Choose where the text goes in the frame."))
        grid = Gtk.Grid(row_spacing=2, column_spacing=2, halign=Gtk.Align.START)
        grid.props.valign = Gtk.Align.START
        self.position_buttons = {}
        for row, valignment in enumerate(("top", "center", "bottom")):
            for column, halignment in enumerate(("left", "center", "right")):
                button = Gtk.ToggleButton()
                button.set_size_request(36, 22)
                button.set_tooltip_text(names[(valignment, halignment)])
                button.connect("toggled", self._position_button_toggled_cb,
                               valignment, halignment)
                grid.attach(button, column, row, 1, 1)
                self.position_buttons[(valignment, halignment)] = button

        self.position_label = Gtk.Label(xalign=0, yalign=0)
        self.position_label.set_line_wrap(True)
        self.position_label.set_max_width_chars(16)
        self.position_label.get_style_context().add_class("dim-label")
        box = Gtk.Box(spacing=SPACING)
        box.props.margin_top = PADDING
        box.pack_start(grid, False, False, 0)
        box.pack_start(self.position_label, True, True, 0)
        self.editing_box.pack_start(box, False, False, 0)

    def _update_position_buttons(self):
        """Shows the position of the source on the position grid."""
        current = (self.valignment_combo.get_active_id(),
                   self.halignment_combo.get_active_id())
        for position, button in self.position_buttons.items():
            button.set_active(position == current)
        name = self.position_names.get(current)
        self.position_label.set_text(
            "%s.\n%s" % (name, _("It stays in place when changing the format."))
            if name else _("Placed by dragging it in the viewer."))

    def _position_button_toggled_cb(self, button, valignment, halignment):
        if self._setting_ui:
            return

        if not button.get_active():
            # The current position cannot be unset, only replaced.
            self._setting_ui = True
            try:
                button.set_active(True)
            finally:
                self._setting_ui = False
            return

        project = self.app.project_manager.current_project
        pipeline = project.pipeline if project else None
        with self.app.action_log.started("Title change position",
                                         finalizing_action=FlushSeekFinalizingAction(pipeline),
                                         toplevel=True):
            self._setting_props = True
            try:
                for name, value in (("valignment", valignment), ("halignment", halignment)):
                    res = self.source.set_child_property(name, value)
                    assert res
            finally:
                self._setting_props = False

        self._setting_ui = True
        try:
            self.valignment_combo.set_active_id(valignment)
            self.halignment_combo.set_active_id(halignment)
            self._update_absolute_alignment_widgets_visibility()
            self._update_position_buttons()
        finally:
            self._setting_ui = False

    def _set_child_property(self, name, value, mergeable=False):
        project = self.app.project_manager.current_project
        pipeline = project.pipeline if project else None
        with self.app.action_log.started("Title change property %s" % name,
                                         finalizing_action=FlushSeekFinalizingAction(pipeline),
                                         mergeable=mergeable,
                                         toplevel=True):
            self._setting_props = True
            try:
                res = self.source.set_child_property(name, value)
                assert res
            finally:
                self._setting_props = False

    def _drop_shadow_checkbox_cb(self, checkbox):
        if self._setting_ui:
            return

        active = checkbox.get_active()
        self.debug("Setting drop shadow checkbox to %s", active)
        self._set_child_property("draw-shadow", active)

    def _color_picker_value_changed_cb(self, widget, color_button, color_layer):
        if self._setting_ui:
            return

        argb = widget.calculate_argb()
        self.debug("Setting text %s to %x", color_layer, argb)
        self._set_child_property(color_layer, argb)
        rgba = argb_to_gdk_rgba(argb)
        color_button.set_rgba(rgba)

    def _background_color_button_cb(self, widget):
        if self._setting_ui:
            return

        color = gdk_rgba_to_argb(widget.get_rgba())
        self.debug("Setting title background color to %x", color)
        self._set_child_property("foreground-color", color)

    def _front_text_color_button_cb(self, widget):
        if self._setting_ui:
            return

        color = gdk_rgba_to_argb(widget.get_rgba())
        self.debug("Setting title foreground color to %x", color)
        # TODO: Use set_text_color when we work with TitleSources instead of
        # TitleClips
        self._set_child_property("color", color)

    def _front_text_outline_color_button_cb(self, widget):
        if self._setting_ui:
            return

        color = gdk_rgba_to_argb(widget.get_rgba())
        self.debug("Setting title outline color to %x", color)
        self._set_child_property("outline-color", color)

    def _get_font_desc(self) -> Pango.FontDescription:
        res, font = self.source.get_child_property("font-desc")
        assert res
        return Pango.FontDescription.from_string(font)

    def _get_frame_height(self) -> int:
        project = self.app.project_manager.current_project
        return project.videoheight if project else REFERENCE_FRAME_HEIGHT

    def _font_combo_changed_cb(self, combo):
        if self._setting_ui:
            return

        points = self._get_font_desc().get_size() / Pango.SCALE or \
            text_size_to_points(DEFAULT_TEXT_SIZE, self._get_frame_height())
        self._set_child_property("font-desc", get_font_description(combo.get_active(), points))

    def _size_scale_button_press_cb(self, unused_widget, unused_event):
        self._dragging = True
        return False

    def _size_scale_button_release_cb(self, unused_widget, unused_event):
        self._dragging = False
        self.flush_pending_size_change()
        return False

    def flush_pending_size_change(self):
        if self._size_change_timeout_id:
            GLib.source_remove(self._size_change_timeout_id)
            self._size_change_timeout_id = None
        self._apply_size_change(force=True)

    def _size_scale_value_changed_cb(self, scale):
        self._update_size_value_label()
        if self._setting_ui:
            return

        self._pending_size = scale.get_value()

        # If the user is dragging the slider with the mouse, debounce rapid changes
        # so we don't spam GStreamer while seeking/rendering.
        if self._dragging:
            if self._size_change_timeout_id:
                GLib.source_remove(self._size_change_timeout_id)
            self._size_change_timeout_id = GLib.timeout_add(75, self._apply_size_change)
            return

        project = self.app.project_manager.current_project
        pipeline = project.pipeline if project else None

        # If pipeline is not busy rendering, apply immediately.
        if not pipeline or not pipeline._busy_async:
            if self._size_change_timeout_id:
                GLib.source_remove(self._size_change_timeout_id)
                self._size_change_timeout_id = None
            self._apply_size_change()
            return

        # Pipeline is busy rendering a previous seek. Schedule a deferred update
        # so we don't modify Pango font description while GStreamer is actively rendering it.
        if not self._size_change_timeout_id:
            self._size_change_timeout_id = GLib.timeout_add(30, self._apply_size_change)

    def _apply_size_change(self, force=False):
        self._size_change_timeout_id = None
        if self._pending_size is None or not self.source:
            return False

        project = self.app.project_manager.current_project
        pipeline = project.pipeline if project else None
        if not force and pipeline and pipeline._busy_async:
            self._size_change_timeout_id = GLib.timeout_add(30, self._apply_size_change)
            return False

        size = self._pending_size
        self._pending_size = None
        self._last_applied_time = time.time()

        font_desc = self._get_font_desc()
        points = text_size_to_points(size, self._get_frame_height())
        font_desc.set_size(round(points * Pango.SCALE))
        self._set_child_property("font-desc", font_desc.to_string(), mergeable=True)
        return False

    def _update_size_value_label(self):
        self.size_value_label.set_markup("<b>%d</b>" % round(self.size_scale.get_value()))

    def _color_button_toggled_cb(self, button, argb):
        if self._setting_ui:
            return

        if not button.get_active():
            # The current color cannot be unset, only replaced.
            self._setting_ui = True
            try:
                button.set_active(True)
            finally:
                self._setting_ui = False
            return

        self._set_child_property("color", argb)
        self._setting_ui = True
        try:
            self._update_style_widgets()
        finally:
            self._setting_ui = False

    def _other_color_set_cb(self, button):
        self._set_child_property("color", gdk_rgba_to_argb(button.get_rgba()))
        self._setting_ui = True
        try:
            self._update_style_widgets()
        finally:
            self._setting_ui = False

    def _update_style_widgets(self, source=None):
        """Shows the font, size and color of the source."""
        source = source or self.source
        res, font = source.get_child_property("font-desc")
        assert res
        font_desc = Pango.FontDescription.from_string(font)
        self.font_combo.set_active(find_font(font_desc))
        points = font_desc.get_size() / Pango.SCALE
        size = points_to_text_size(points, self._get_frame_height()) if points else DEFAULT_TEXT_SIZE
        self.size_scale.set_value(size)
        self._update_size_value_label()

        res, argb = source.get_child_property("color")
        assert res
        for button_argb, button in self.color_buttons.items():
            button.set_active(button_argb == argb)
        self.other_color_button.set_rgba(argb_to_gdk_rgba(argb))

        res_s, draw_shadow = source.get_child_property("draw-shadow")
        res_o, outline_color = source.get_child_property("outline-color")
        has_shadow = bool(res_s and draw_shadow)
        has_outline = bool(res_o and outline_color and (outline_color >> 24) > 0)

        if has_outline and has_shadow:
            active_style = "emboss"
        elif has_outline and not has_shadow:
            active_style = "outline"
        elif not has_outline and has_shadow:
            active_style = "shadow"
        else:
            active_style = "flat"

        button = self.shadow_buttons.get(active_style)
        if button and not button.get_active():
            button.set_active(True)

    def _shadow_button_toggled_cb(self, button, style_id):
        if self._setting_ui or not button.get_active() or not self.source:
            return

        for sid, unused_label, unused_tip, draw_shadow, outline_color in SHADOW_STYLES:
            if sid == style_id:
                break
        else:
            return

        project = self.app.project_manager.current_project
        pipeline = project.pipeline if project else None
        with self.app.action_log.started("Title change shadow style",
                                         finalizing_action=FlushSeekFinalizingAction(pipeline),
                                         toplevel=True):
            self._setting_props = True
            try:
                self.source.set_child_property("draw-shadow", draw_shadow)
                self.source.set_child_property("outline-color", outline_color)
            finally:
                self._setting_props = False

    def _font_button_cb(self, widget):
        if self._setting_ui:
            return

        font_desc = widget.get_font_desc().to_string()
        self.debug("Setting font desc to %s", font_desc)
        self._set_child_property("font-desc", font_desc)

    def __update_from_source(self, source):
        res, text = source.get_child_property("text")
        assert res
        self.textbuffer.props.text = html.unescape(text or "")

        res, x_absolute = source.get_child_property("x-absolute")
        assert res
        self.x_absolute_spin.set_value(x_absolute)

        res, y_absolute = source.get_child_property("y-absolute")
        assert res
        self.y_absolute_spin.set_value(y_absolute)

        res, valignment = source.get_child_property("valignment")
        assert res
        self.valignment_combo.set_active_id(valignment.value_name)

        res, halignment = source.get_child_property("halignment")
        assert res
        self.halignment_combo.set_active_id(halignment.value_name)

        self._update_absolute_alignment_widgets_visibility()
        self._update_position_buttons()

        res, font = source.get_child_property("font-desc")
        assert res
        font_desc = Pango.FontDescription.from_string(font)
        self.font_button.set_font_desc(font_desc)

        res, argb = source.get_child_property("color")
        assert res
        color = argb_to_gdk_rgba(argb)
        self.foreground_color_button.set_rgba(color)

        res, argb = source.get_child_property("foreground-color")
        assert res
        color = argb_to_gdk_rgba(argb)
        self.background_color_button.set_rgba(color)

        res, draw_shadow = source.get_child_property("draw-shadow")
        assert res
        self.drop_shadow_checkbox.set_active(draw_shadow)

        res, argb = source.get_child_property("outline-color")
        assert res
        color = argb_to_gdk_rgba(argb)
        self.outline_color_button.set_rgba(color)

        self._update_style_widgets(source)

    def _text_changed_cb(self, unused_text_buffer):
        if self._setting_ui:
            return

        escaped_text = html.escape(self.textbuffer.props.text)
        self.log("Source text updated to %s", escaped_text)
        self._set_child_property("text", escaped_text, mergeable=True)

    def _alignment_changed_cb(self, combo):
        """Handles changes in the h/v alignment widgets."""
        if self._setting_ui:
            return

        if combo == self.valignment_combo:
            prop_name = "valignment"
        else:
            prop_name = "halignment"
        value = combo.get_active_id()
        self._set_child_property(prop_name, value)

        self._update_absolute_alignment_widgets_visibility()

    def _absolute_alignment_value_changed_cb(self, spin):
        """Handles changes in the absolute alignment widgets."""
        if self._setting_ui:
            return

        if spin == self.x_absolute_spin:
            prop_name = "x-absolute"
        else:
            prop_name = "y-absolute"
        value = spin.get_value()
        self._set_child_property(prop_name, value, mergeable=True)

    def _update_absolute_alignment_widgets_visibility(self):
        visible = self.valignment_combo.get_active_id() == "absolute"
        self.y_absolute_spin.set_visible(visible)
        visible = self.halignment_combo.get_active_id() == "absolute"
        self.x_absolute_spin.set_visible(visible)

    def set_source(self, source: Optional[Union[GES.TextOverlay, GES.TitleSource]]):
        """Sets the clip to be edited with this editor.

        Args:
            source (GES.TitleSource): The source of the clip.
        """
        self.debug("Setting source to %s", source)
        if self._size_change_timeout_id:
            GLib.source_remove(self._size_change_timeout_id)
            self._size_change_timeout_id = None
        self._pending_size = None
        self._dragging = False

        if self.source:
            self.source.disconnect(self._children_props_handler)
            self._children_props_handler = None

        self.source = None

        if source:
            assert isinstance(source, (GES.TextOverlay, GES.TitleSource))
            self._setting_ui = True
            try:
                self.__update_from_source(source)
            finally:
                self._setting_ui = False
            self._children_props_handler = source.connect("deep-notify",
                                                          self._source_deep_notify_cb)
            self.source = source

        self.set_visible(bool(self.source))

    def _source_deep_notify_cb(self, source, unused_gstelement, pspec):
        """Handles updates in the TitleSource backing the current TitleClip."""
        if self._setting_props:
            return

        control_binding = self.source.get_control_binding(pspec.name)
        if control_binding:
            self.debug("Not handling %s as it is being interpolated",
                       pspec.name)
            return

        self._setting_ui = True
        try:
            self.__update_ui_for_prop(pspec)
        finally:
            self._setting_ui = False

        project = self.app.project_manager.current_project
        if project and project.pipeline:
            project.pipeline.flush_seek()

    def __update_ui_for_prop(self, pspec: GObject.ParamSpec):
        res, value = self.source.get_child_property(pspec.name)
        assert res, pspec.name
        if pspec.name == "text":
            text = html.unescape(value)
            if self.textbuffer.props.text == text:
                return
            self.textbuffer.props.text = text
        elif pspec.name in ["x-absolute", "y-absolute"]:
            if pspec.name == "x-absolute":
                widget = self.x_absolute_spin
            else:
                widget = self.y_absolute_spin
            if widget.get_value() == value:
                return
            widget.set_value(value)
        elif pspec.name in ["valignment", "halignment"]:
            if pspec.name == "valignment":
                widget = self.valignment_combo
            else:
                widget = self.halignment_combo
            value = value.value_name
            if widget.get_active_id() == value:
                return
            widget.set_active_id(value)
            self._update_position_buttons()
        elif pspec.name == "font-desc":
            if self._size_change_timeout_id:
                GLib.source_remove(self._size_change_timeout_id)
                self._size_change_timeout_id = None
            self._pending_size = None
            self._update_style_widgets()
            if self.font_button.get_font_desc() == value:
                return
            font_desc = Pango.FontDescription.from_string(value)
            self.font_button.set_font_desc(font_desc)
        elif pspec.name == "color":
            self._update_style_widgets()
            color = argb_to_gdk_rgba(value)
            if color == self.foreground_color_button.get_rgba():
                return
            self.foreground_color_button.set_rgba(color)
        elif pspec.name == "foreground-color":
            color = argb_to_gdk_rgba(value)
            if color == self.background_color_button.get_rgba():
                return
            self.background_color_button.set_rgba(color)
        elif pspec.name in ["outline-color", "draw-shadow"]:
            self._update_style_widgets()
            if pspec.name == "outline-color":
                color = argb_to_gdk_rgba(value)
                if color != self.outline_color_button.get_rgba():
                    self.outline_color_button.set_rgba(color)
            elif pspec.name == "draw-shadow":
                self.drop_shadow_checkbox.set_active(value)
