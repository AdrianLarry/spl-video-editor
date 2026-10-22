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
"""Widgets for the transitions where two clips of a layer meet."""
import locale
import math
from gettext import gettext as _

import cairo
from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gst
from gi.repository import Gtk
from gi.repository import Pango

from pitivi.undo.timeline import CommitTimelineFinalizingAction
from pitivi.utils.loggable import Loggable
from pitivi.utils.misc import filename_from_uri
from pitivi.utils.transitions import BLUR
from pitivi.utils.transitions import BOTTOM
from pitivi.utils.transitions import Contact
from pitivi.utils.transitions import DEFAULT_DURATION
from pitivi.utils.transitions import DISSOLVE
from pitivi.utils.transitions import FADE_TO_BLACK
from pitivi.utils.transitions import FADE_TO_WHITE
from pitivi.utils.transitions import find_contact_for_transition
from pitivi.utils.transitions import LEFT
from pitivi.utils.transitions import MIN_DURATION
from pitivi.utils.transitions import OVERLAPPING_KINDS
from pitivi.utils.transitions import PUSH
from pitivi.utils.transitions import RIGHT
from pitivi.utils.transitions import SOFT_WIPE
from pitivi.utils.transitions import TOP
from pitivi.utils.transitions import get_max_duration
from pitivi.utils.transitions import remove_transition
from pitivi.utils.transitions import set_transition
from pitivi.utils.transitions import wipes_work
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING

# The kinds offered, as in the mockup.
KINDS = ((DISSOLVE, _("Dissolve")),
         (SOFT_WIPE, _("Soft wipe")),
         (FADE_TO_BLACK, _("Fade to black")),
         (FADE_TO_WHITE, _("Fade to white")),
         (PUSH, _("Slide")),
         (BLUR, _("Blur")))

# The sides the second clip appears from, with their icons.
DIRECTIONS = ((LEFT, _("Left"), "go-next-symbolic"),
              (RIGHT, _("Right"), "go-previous-symbolic"),
              (TOP, _("Top"), "go-down-symbolic"),
              (BOTTOM, _("Bottom"), "go-up-symbolic"))
# The kinds which have a direction.
DIRECTED_KINDS = (SOFT_WIPE, PUSH)


def get_kind_name(kind):
    """Returns the name of a kind of transition."""
    for other_kind, name in KINDS:
        if other_kind == kind:
            return name
    return ""


def format_seconds(duration):
    """Returns a duration in seconds, as "1,5 s"."""
    return locale.format_string("%.1f s", duration / Gst.SECOND)


# The angle turning the icons drawn for a clip coming from the right.
ICON_ANGLES = {RIGHT: 0, LEFT: math.pi, TOP: -math.pi / 2, BOTTOM: math.pi / 2}
ICON_SIZE = 14


class TransitionIcon(Gtk.DrawingArea):
    """A small icon of a kind of transition, or a plus for adding one."""

    def __init__(self, kind, direction=None):
        Gtk.DrawingArea.__init__(self)
        self.kind = kind
        self.direction = direction or RIGHT
        self.set_size_request(ICON_SIZE, ICON_SIZE)
        self.props.halign = Gtk.Align.CENTER
        self.props.valign = Gtk.Align.CENTER
        self.connect("draw", self.__draw_cb)

    def __draw_cb(self, unused_widget, cr):
        size = ICON_SIZE
        cr.translate(size / 2, size / 2)
        if self.kind in (SOFT_WIPE, PUSH):
            cr.rotate(ICON_ANGLES[self.direction])
        cr.set_line_width(1.5)
        cr.set_source_rgb(1, 1, 1)
        draw = {DISSOLVE: self._draw_dissolve,
                SOFT_WIPE: self._draw_soft_wipe,
                FADE_TO_BLACK: self._draw_fade_to_black,
                FADE_TO_WHITE: self._draw_fade_to_white,
                PUSH: self._draw_push,
                BLUR: self._draw_blur}.get(self.kind, self._draw_add)
        draw(cr)
        return False

    @staticmethod
    def _draw_dissolve(cr):
        # Two images, one appearing over the other.
        cr.arc(-2, 0, 4.25, 0, 2 * math.pi)
        cr.stroke()
        cr.arc(2, 0, 4.25, 0, 2 * math.pi)
        cr.set_source_rgba(1, 1, 1, 0.6)
        cr.fill()

    @staticmethod
    def _draw_soft_wipe(cr):
        # A frame uncovered from a side, with a soft edge.
        cr.rectangle(-5.5, -4.5, 11, 9)
        gradient = cairo.LinearGradient(-3, 0, 4, 0)
        gradient.add_color_stop_rgba(0, 1, 1, 1, 0)
        gradient.add_color_stop_rgba(1, 1, 1, 1, 1)
        cr.set_source(gradient)
        cr.fill_preserve()
        cr.set_source_rgb(1, 1, 1)
        cr.stroke()

    @staticmethod
    def _draw_fade_to_black(cr):
        # An image going dark.
        cr.arc(0, 0, 5, 0, 2 * math.pi)
        gradient = cairo.LinearGradient(-5, 0, 5, 0)
        gradient.add_color_stop_rgba(0, 1, 1, 1, 1)
        gradient.add_color_stop_rgba(1, 0, 0, 0, 1)
        cr.set_source(gradient)
        cr.fill_preserve()
        cr.set_source_rgb(1, 1, 1)
        cr.stroke()

    @staticmethod
    def _draw_fade_to_white(cr):
        # An image turning into light.
        cr.arc(0, 0, 3.5, 0, 2 * math.pi)
        cr.fill()
        for index in range(8):
            angle = index * math.pi / 4
            cr.move_to(5 * math.cos(angle), 5 * math.sin(angle))
            cr.line_to(6.5 * math.cos(angle), 6.5 * math.sin(angle))
        cr.set_line_width(1.2)
        cr.stroke()

    @staticmethod
    def _draw_push(cr):
        # The second image pushing the first one out.
        cr.rectangle(-6, -3.5, 5, 7)
        cr.stroke()
        cr.rectangle(1, -4.25, 5.75, 8.5)
        cr.fill()

    @staticmethod
    def _draw_blur(cr):
        # An image going out of focus.
        for radius, alpha in ((6, 0.25), (4.5, 0.5), (3, 1)):
            cr.arc(0, 0, radius, 0, 2 * math.pi)
            cr.set_source_rgba(1, 1, 1, alpha)
            cr.fill()

    @staticmethod
    def _draw_add(cr):
        cr.move_to(-4.5, 0)
        cr.line_to(4.5, 0)
        cr.move_to(0, -4.5)
        cr.line_to(0, 4.5)
        cr.set_line_width(1.75)
        cr.stroke()


def create_transition_button(contact: Contact) -> Gtk.Button:
    """Creates the round button showing the transition, or for adding one.

    It shows an icon of the kind, its name is in the tooltip.
    """
    button = Gtk.Button()
    style = button.get_style_context()
    style.add_class("TransitionButton")
    style.add_class("spl-trans-chip")
    button.props.focus_on_click = False
    button.add(TransitionIcon(contact.kind, contact.direction))
    if contact.kind:
        button.set_tooltip_text(_("%s, %s. Click to change or remove it.") %
                                (get_kind_name(contact.kind), format_seconds(contact.duration)))
    else:
        style.add_class("spl-trans-chip-add")
        button.set_tooltip_text(_("Add a transition"))
    return button


class TransitionPreview(Gtk.DrawingArea):
    """Draws an animated or static preview of a transition between Clip A and Clip B."""

    def __init__(self, kind: str, direction: str = RIGHT):
        super().__init__()
        self.kind = kind
        self.direction = direction
        self.is_hovered = False
        self.is_selected = False
        self.tick_id = 0
        self.start_time = 0
        self.connect("draw", self._draw_cb)

    def set_hovered(self, hovered: bool):
        if self.is_hovered != hovered:
            self.is_hovered = hovered
            self._update_animation()

    def set_selected(self, selected: bool):
        if self.is_selected != selected:
            self.is_selected = selected
            self._update_animation()

    def set_direction(self, direction: str):
        if self.direction != direction:
            self.direction = direction
            self.queue_draw()

    def _update_animation(self):
        should_animate = self.is_hovered or self.is_selected
        if should_animate and not self.tick_id:
            self.start_time = GLib.get_monotonic_time()
            self.tick_id = self.add_tick_callback(self._on_tick)
        elif not should_animate and self.tick_id:
            self.remove_tick_callback(self.tick_id)
            self.tick_id = 0
            self.queue_draw()

    def stop_animation(self):
        if self.tick_id:
            self.remove_tick_callback(self.tick_id)
            self.tick_id = 0

    def _on_tick(self, widget, frame_clock):
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    @staticmethod
    def _rounded_rectangle(cr, x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    @staticmethod
    def _draw_clip_a(cr, x, y, width, height, alpha=1.0):
        if alpha <= 0 or width <= 0 or height <= 0:
            return
        cr.save()
        cr.rectangle(x, y, width, height)
        cr.clip()
        pat = cairo.LinearGradient(x, y, x + width, y + height)
        pat.add_color_stop_rgba(0.0, 0.298, 0.525, 0.769, alpha)
        pat.add_color_stop_rgba(1.0, 0.165, 0.310, 0.502, alpha)
        cr.set_source(pat)
        cr.paint()
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11.0)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.85 * alpha)
        cr.move_to(x + 7, y + 15)
        cr.show_text("A")
        cr.restore()

    @staticmethod
    def _draw_clip_b(cr, x, y, width, height, alpha=1.0):
        if alpha <= 0 or width <= 0 or height <= 0:
            return
        cr.save()
        cr.rectangle(x, y, width, height)
        cr.clip()
        pat = cairo.LinearGradient(x, y, x + width, y + height)
        pat.add_color_stop_rgba(0.0, 1.000, 0.639, 0.416, alpha)
        pat.add_color_stop_rgba(1.0, 0.831, 0.345, 0.235, alpha)
        cr.set_source(pat)
        cr.paint()
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11.0)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.85 * alpha)
        cr.move_to(x + width - 16, y + 15)
        cr.show_text("B")
        cr.restore()

    @staticmethod
    def _draw_blurred(cr, draw_clip, w, h, blur_amt, alpha):
        """Draws a clip blurred by copies around it."""
        draw_clip(cr, 0, 0, w, h, alpha=alpha)
        if blur_amt <= 0.05:
            return
        radius = blur_amt * 7.0
        for dx, dy in ((-radius, 0), (radius, 0), (0, -radius), (0, radius),
                       (-radius * 0.7, -radius * 0.7), (radius * 0.7, radius * 0.7)):
            draw_clip(cr, dx, dy, w, h, alpha=0.15 * blur_amt * alpha)

    def _draw_cb(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        if w <= 0 or h <= 0:
            return False

        # Outer clipping to rounded corners
        self._rounded_rectangle(cr, 0, 0, w, h, 6.0)
        cr.clip()

        # If not animating, draw static split view (A | B)
        if not (self.is_hovered or self.is_selected):
            half = w / 2.0
            self._draw_clip_a(cr, 0, 0, half, h)
            self._draw_clip_b(cr, half, 0, w - half, h)
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.4)
            cr.set_line_width(2.0)
            cr.move_to(half, 0)
            cr.line_to(half, h)
            cr.stroke()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.35)
            cr.set_line_width(1.0)
            cr.move_to(half, 0)
            cr.line_to(half, h)
            cr.stroke()
            return False

        # Compute animation progress (0.0 to 1.0) over a 2.4s cycle
        now = GLib.get_monotonic_time()
        cycle_us = 2400000.0
        phase = ((now - self.start_time) % cycle_us) / cycle_us

        if phase < 0.20:
            t = 0.0
        elif phase > 0.70:
            t = 1.0
        else:
            p = (phase - 0.20) / 0.50
            t = 0.5 * (1.0 - math.cos(math.pi * p))

        direction = self.direction or RIGHT

        if self.kind == DISSOLVE:
            self._draw_clip_a(cr, 0, 0, w, h)
            self._draw_clip_b(cr, 0, 0, w, h, alpha=t)

        elif self.kind == FADE_TO_BLACK:
            cr.set_source_rgb(0, 0, 0)
            cr.paint()
            if t < 0.5:
                p = t / 0.5
                self._draw_clip_a(cr, 0, 0, w, h, alpha=1.0 - p)
            else:
                p = (t - 0.5) / 0.5
                self._draw_clip_b(cr, 0, 0, w, h, alpha=p)

        elif self.kind == FADE_TO_WHITE:
            if t < 0.5:
                p = t / 0.5
                self._draw_clip_a(cr, 0, 0, w, h)
                cr.set_source_rgba(1.0, 1.0, 1.0, p)
                cr.paint()
            else:
                p = (t - 0.5) / 0.5
                self._draw_clip_b(cr, 0, 0, w, h)
                cr.set_source_rgba(1.0, 1.0, 1.0, 1.0 - p)
                cr.paint()

        elif self.kind == PUSH:
            if direction == RIGHT:
                xa = -t * w
                xb = (1.0 - t) * w
                self._draw_clip_a(cr, xa, 0, w, h)
                self._draw_clip_b(cr, xb, 0, w, h)
                seam_x = xb
                cr.set_source_rgba(0, 0, 0, 0.35)
                cr.set_line_width(1.0)
                cr.move_to(seam_x, 0)
                cr.line_to(seam_x, h)
                cr.stroke()
            elif direction == LEFT:
                xa = t * w
                xb = -(1.0 - t) * w
                self._draw_clip_a(cr, xa, 0, w, h)
                self._draw_clip_b(cr, xb, 0, w, h)
                seam_x = xb + w
                cr.set_source_rgba(0, 0, 0, 0.35)
                cr.set_line_width(1.0)
                cr.move_to(seam_x, 0)
                cr.line_to(seam_x, h)
                cr.stroke()
            elif direction == TOP:
                ya = t * h
                yb = -(1.0 - t) * h
                self._draw_clip_a(cr, 0, ya, w, h)
                self._draw_clip_b(cr, 0, yb, w, h)
                seam_y = yb + h
                cr.set_source_rgba(0, 0, 0, 0.35)
                cr.set_line_width(1.0)
                cr.move_to(0, seam_y)
                cr.line_to(w, seam_y)
                cr.stroke()
            else:  # BOTTOM
                ya = -t * h
                yb = (1.0 - t) * h
                self._draw_clip_a(cr, 0, ya, w, h)
                self._draw_clip_b(cr, 0, yb, w, h)
                seam_y = yb
                cr.set_source_rgba(0, 0, 0, 0.35)
                cr.set_line_width(1.0)
                cr.move_to(0, seam_y)
                cr.line_to(w, seam_y)
                cr.stroke()

        elif self.kind == SOFT_WIPE:
            self._draw_clip_a(cr, 0, 0, w, h)
            cr.push_group()
            self._draw_clip_b(cr, 0, 0, w, h)
            group = cr.pop_group()

            f = 24.0  # feather width in pixels
            if direction == RIGHT:
                pos = (w + f) - t * (w + 2 * f)
                mask = cairo.LinearGradient(pos, 0, pos + f, 0)
                mask.add_color_stop_rgba(0.0, 1, 1, 1, 0.0)
                mask.add_color_stop_rgba(1.0, 1, 1, 1, 1.0)
            elif direction == LEFT:
                pos = -f + t * (w + 2 * f)
                mask = cairo.LinearGradient(pos - f, 0, pos, 0)
                mask.add_color_stop_rgba(0.0, 1, 1, 1, 1.0)
                mask.add_color_stop_rgba(1.0, 1, 1, 1, 0.0)
            elif direction == TOP:
                pos = -f + t * (h + 2 * f)
                mask = cairo.LinearGradient(0, pos - f, 0, pos)
                mask.add_color_stop_rgba(0.0, 1, 1, 1, 1.0)
                mask.add_color_stop_rgba(1.0, 1, 1, 1, 0.0)
            else:  # BOTTOM
                pos = (h + f) - t * (h + 2 * f)
                mask = cairo.LinearGradient(0, pos, 0, pos + f)
                mask.add_color_stop_rgba(0.0, 1, 1, 1, 0.0)
                mask.add_color_stop_rgba(1.0, 1, 1, 1, 1.0)

            cr.set_source(group)
            cr.mask(mask)

        elif self.kind == BLUR:
            # Both clips mixed as in a dissolve, the most blurred in the
            # middle: the first one from the middle, the second one until it.
            self._draw_blurred(cr, self._draw_clip_a, w, h, min(1.0, t * 2), 1.0)
            self._draw_blurred(cr, self._draw_clip_b, w, h, min(1.0, (1.0 - t) * 2), t)

        else:
            self._draw_clip_a(cr, 0, 0, w, h)

        return False


class TransitionPopover(Gtk.Popover):
    """Popover for choosing the transition where two clips meet.

    Attributes:
        app (Pitivi): The app.
        contact (Contact): The clips and their transition.
    """

    def __init__(self, app, contact: Contact, relative_to: Gtk.Widget):
        Gtk.Popover.__init__(self)
        self.app = app
        self.contact = contact
        self.set_relative_to(relative_to)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        box.props.margin = SPACING
        box.set_size_request(340, -1)

        title = Gtk.Label(xalign=0)
        title.set_markup("<b>%s</b>" % GLib.markup_escape_text(
            _("Change transition") if contact.kind else _("Add transition")))
        box.pack_start(title, False, False, 0)
        names = [filename_from_uri(clip.get_asset().props.id)
                 for clip in (contact.clip_a, contact.clip_b)]
        subtitle = Gtk.Label(label=_("Between «%s» and «%s»") % tuple(names), xalign=0)
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle.set_max_width_chars(36)
        subtitle.get_style_context().add_class("dim-label")
        box.pack_start(subtitle, False, False, 0)

        grid = Gtk.Grid(row_spacing=8, column_spacing=8, column_homogeneous=True)
        self.kind_buttons = {}
        self.previews = {}
        group = None
        for index, (kind, name) in enumerate(KINDS):
            button = Gtk.RadioButton.new_from_widget(group)
            group = group or button
            button.set_mode(False)
            button.get_style_context().add_class("spl-trans-card")
            button.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)

            card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            preview = TransitionPreview(kind, contact.direction or RIGHT)
            preview.set_size_request(-1, 48)
            self.previews[kind] = preview
            card_box.pack_start(preview, True, True, 0)

            label = Gtk.Label(xalign=0)
            label.set_markup("<b>%s</b>" % GLib.markup_escape_text(name))
            label.set_margin_start(2)
            label.set_margin_bottom(2)
            card_box.pack_start(label, False, False, 0)

            button.add(card_box)

            if kind:
                self.kind_buttons[kind] = button
                button.connect("toggled", self.__kind_toggled_cb)
                button.connect("enter-notify-event", self.__card_enter_cb, preview)
                button.connect("leave-notify-event", self.__card_leave_cb, preview)
            else:
                button.set_sensitive(False)
                button.set_tooltip_text(_("Coming soon"))
            grid.attach(button, index % 2, index // 2, 1, 1)

        active_kind = contact.kind or DISSOLVE
        self.kind_buttons[active_kind].set_active(True)
        self.previews[active_kind].set_selected(True)

        if not wipes_work(contact.clip_a, contact.clip_b) and contact.kind != SOFT_WIPE:
            # GES draws the wipes wrong with images.
            soft_wipe_button = self.kind_buttons[SOFT_WIPE]
            soft_wipe_button.set_sensitive(False)
            soft_wipe_button.set_tooltip_text(_("Only between two videos, with photos it is not drawn right."))
        box.pack_start(grid, False, False, 0)

        self.direction_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PADDING)
        self.direction_box.pack_start(Gtk.Label(label=_("From"), xalign=0), False, False, 0)
        directions_grid = Gtk.Grid(column_spacing=PADDING, column_homogeneous=True)
        self.direction_buttons = {}
        group = None
        for index, (direction, name, icon_name) in enumerate(DIRECTIONS):
            button = Gtk.RadioButton.new_with_label_from_widget(group, name)
            group = group or button
            button.set_mode(False)
            button.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU))
            button.set_always_show_image(True)
            button.connect("toggled", self.__direction_toggled_cb)
            directions_grid.attach(button, index, 0, 1, 1)
            self.direction_buttons[direction] = button
        self.direction_buttons[contact.direction or RIGHT].set_active(True)
        self.direction_box.pack_start(directions_grid, False, False, 0)
        box.pack_start(self.direction_box, False, False, 0)

        duration_box = Gtk.Box()
        duration_box.pack_start(Gtk.Label(label=_("Duration")), False, False, 0)
        self.duration_label = Gtk.Label()
        duration_box.pack_end(self.duration_label, False, False, 0)
        box.pack_start(duration_box, False, False, 0)
        self.duration_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                                       MIN_DURATION / Gst.SECOND,
                                                       MIN_DURATION / Gst.SECOND + 0.1, 0.1)
        self.duration_scale.set_draw_value(False)
        self.duration_scale.connect("value-changed", self.__duration_changed_cb)
        self.__update_duration_range()
        duration = contact.duration if contact.kind else DEFAULT_DURATION
        self.duration_scale.set_value(duration / Gst.SECOND)
        self.__duration_changed_cb(self.duration_scale)
        box.pack_start(self.duration_scale, False, False, 0)

        buttons_box = Gtk.Box(spacing=PADDING)
        if contact.kind:
            self.remove_button = Gtk.Button(label=_("Remove transition"))
            self.remove_button.props.relief = Gtk.ReliefStyle.NONE
            self.remove_button.get_style_context().add_class("spl-danger-text")
            self.remove_button.connect("clicked", self.__remove_clicked_cb)
            buttons_box.pack_start(self.remove_button, False, False, 0)
        self.apply_button = Gtk.Button(label=_("Save") if contact.kind else _("Apply"))
        self.apply_button.get_style_context().add_class("suggested-action")
        self.apply_button.get_style_context().add_class("spl-accent")
        self.apply_button.connect("clicked", self.__apply_clicked_cb)
        buttons_box.pack_end(self.apply_button, False, False, 0)
        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", lambda unused_button: self.popdown())
        buttons_box.pack_end(cancel_button, False, False, 0)
        box.pack_start(buttons_box, False, False, 0)

        self.add(box)
        box.show_all()
        self.__update_direction_visibility()
        self.connect("closed", self.__closed_cb)

    def __closed_cb(self, popover):
        for preview in self.previews.values():
            preview.stop_animation()

    def __card_enter_cb(self, button, event, preview):
        preview.set_hovered(True)
        return False

    def __card_leave_cb(self, button, event, preview):
        preview.set_hovered(False)
        return False

    def __direction_toggled_cb(self, button):
        if button.get_active():
            direction = self.get_direction()
            for preview in self.previews.values():
                preview.set_direction(direction)

    def __update_direction_visibility(self):
        self.direction_box.set_visible(self.get_kind() in DIRECTED_KINDS)

    def get_direction(self):
        for direction, button in self.direction_buttons.items():
            if button.get_active():
                return direction
        return None

    def __update_duration_range(self):
        """Sets the durations offered, which depend on the kind."""
        max_duration = get_max_duration(self.contact, self.get_kind()) / Gst.SECOND
        min_duration = min(MIN_DURATION / Gst.SECOND, max_duration)
        self.duration_scale.set_range(min_duration, max(max_duration, min_duration))

    def __kind_toggled_cb(self, button):
        for kind, btn in self.kind_buttons.items():
            preview = self.previews.get(kind)
            if preview:
                preview.set_selected(btn.get_active())
        if button.get_active() and hasattr(self, "duration_scale"):
            self.__update_duration_range()
        if button.get_active() and hasattr(self, "direction_box"):
            self.__update_direction_visibility()

    def __duration_changed_cb(self, scale):
        self.duration_label.set_markup("<b>%s</b>" % GLib.markup_escape_text(
            format_seconds(scale.get_value() * Gst.SECOND)))

    def get_kind(self):
        for kind, button in self.kind_buttons.items():
            if button.get_active():
                return kind
        return None

    def __change(self, change):
        pipeline = self.app.project_manager.current_project.pipeline
        with self.app.action_log.started("transition",
                                         finalizing_action=CommitTimelineFinalizingAction(pipeline),
                                         toplevel=True):
            change()
        self.popdown()
        # Nothing moves for some transitions, the buttons are updated anyway.
        layer = self.get_relative_to().get_parent()
        if hasattr(layer, "schedule_update_gaps"):
            layer.schedule_update_gaps()

    def __apply_clicked_cb(self, unused_button):
        duration = round(self.duration_scale.get_value() * 10) * Gst.SECOND // 10
        self.__change(lambda: set_transition(self.contact, self.get_kind(), duration,
                                             self.get_direction()))

    def __remove_clicked_cb(self, unused_button):
        self.__change(lambda: remove_transition(self.contact))


class TransitionPropertiesWidget(Gtk.ScrolledWindow, Loggable):
    """Properties panel widget for configuring the selected transition.

    Attributes:
        app (Pitivi): The app.
        contact (Optional[Contact]): The clips and their transition.
    """

    def __init__(self, app):
        Gtk.ScrolledWindow.__init__(self)
        Loggable.__init__(self)

        self.app = app
        self.contact: Optional[Contact] = None
        self.ges_element = None

        self.props.hscrollbar_policy = Gtk.PolicyType.NEVER
        self.props.vscrollbar_policy = Gtk.PolicyType.AUTOMATIC

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        self.main_box.props.margin = 14

        # Empty state placeholder
        self.empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        self.empty_box.props.valign = Gtk.Align.CENTER
        self.empty_box.props.vexpand = True
        placeholder_title = Gtk.Label(label=_("No transition selected"))
        placeholder_title.get_style_context().add_class("dim-label")
        placeholder_desc = Gtk.Label(label=_("Select a transition on the timeline to configure it."))
        placeholder_desc.get_style_context().add_class("dim-label")
        placeholder_desc.set_line_wrap(True)
        self.empty_box.pack_start(placeholder_title, False, False, 0)
        self.empty_box.pack_start(placeholder_desc, False, False, 0)
        self.main_box.pack_start(self.empty_box, True, True, 0)

        # Content box when a transition is selected
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        self.main_box.pack_start(self.content_box, False, False, 0)

        self.title_label = Gtk.Label(xalign=0)
        self.content_box.pack_start(self.title_label, False, False, 0)

        self.subtitle_label = Gtk.Label(xalign=0)
        self.subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.subtitle_label.set_max_width_chars(36)
        self.subtitle_label.get_style_context().add_class("dim-label")
        self.content_box.pack_start(self.subtitle_label, False, False, 0)

        grid = Gtk.Grid(row_spacing=8, column_spacing=8, column_homogeneous=True)
        self.kind_buttons = {}
        self.previews = {}
        group = None
        for index, (kind, name) in enumerate(KINDS):
            button = Gtk.RadioButton.new_from_widget(group)
            group = group or button
            button.set_mode(False)
            button.get_style_context().add_class("spl-trans-card")
            button.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)

            card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            preview = TransitionPreview(kind, RIGHT)
            preview.set_size_request(-1, 48)
            self.previews[kind] = preview
            card_box.pack_start(preview, True, True, 0)

            label = Gtk.Label(xalign=0)
            label.set_markup("<b>%s</b>" % GLib.markup_escape_text(name))
            label.set_margin_start(2)
            label.set_margin_bottom(2)
            card_box.pack_start(label, False, False, 0)

            button.add(card_box)

            if kind:
                self.kind_buttons[kind] = button
                button.connect("toggled", self.__kind_toggled_cb)
                button.connect("enter-notify-event", self.__card_enter_cb, preview)
                button.connect("leave-notify-event", self.__card_leave_cb, preview)
            else:
                button.set_sensitive(False)
            grid.attach(button, index % 2, index // 2, 1, 1)

        self.content_box.pack_start(grid, False, False, 0)

        self.direction_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PADDING)
        self.direction_box.pack_start(Gtk.Label(label=_("From"), xalign=0), False, False, 0)
        directions_grid = Gtk.Grid(column_spacing=PADDING, column_homogeneous=True)
        self.direction_buttons = {}
        dir_group = None
        for index, (direction, name, icon_name) in enumerate(DIRECTIONS):
            button = Gtk.RadioButton.new_with_label_from_widget(dir_group, name)
            dir_group = dir_group or button
            button.set_mode(False)
            button.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU))
            button.set_always_show_image(True)
            button.connect("toggled", self.__direction_toggled_cb)
            directions_grid.attach(button, index, 0, 1, 1)
            self.direction_buttons[direction] = button
        self.direction_box.pack_start(directions_grid, False, False, 0)
        self.content_box.pack_start(self.direction_box, False, False, 0)

        duration_box = Gtk.Box()
        duration_box.pack_start(Gtk.Label(label=_("Duration")), False, False, 0)
        self.duration_label = Gtk.Label()
        duration_box.pack_end(self.duration_label, False, False, 0)
        self.content_box.pack_start(duration_box, False, False, 0)

        self.duration_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                                       MIN_DURATION / Gst.SECOND,
                                                       MIN_DURATION / Gst.SECOND + 0.1, 0.1)
        self.duration_scale.set_draw_value(False)
        self.duration_scale.connect("value-changed", self.__duration_changed_cb)
        self.content_box.pack_start(self.duration_scale, False, False, 0)

        buttons_box = Gtk.Box(spacing=PADDING)
        buttons_box.props.margin_top = 8
        self.remove_button = Gtk.Button(label=_("Remove transition"))
        self.remove_button.props.relief = Gtk.ReliefStyle.NONE
        self.remove_button.get_style_context().add_class("spl-danger-text")
        self.remove_button.connect("clicked", self.__remove_clicked_cb)
        buttons_box.pack_start(self.remove_button, False, False, 0)

        self.apply_button = Gtk.Button(label=_("Save"))
        self.apply_button.get_style_context().add_class("suggested-action")
        self.apply_button.get_style_context().add_class("spl-accent")
        self.apply_button.connect("clicked", self.__apply_clicked_cb)
        buttons_box.pack_end(self.apply_button, False, False, 0)
        self.content_box.pack_start(buttons_box, False, False, 0)

        self.add(self.main_box)
        self.content_box.hide()
        self.empty_box.show_all()

    def activate(self, ges_timeline_element):
        """Activates and shows properties for the selected transition."""
        self.ges_element = ges_timeline_element
        contact = find_contact_for_transition(ges_timeline_element)
        if not contact:
            self.deactivate()
            return

        self.contact = contact
        self.title_label.set_markup("<b>%s</b>" % GLib.markup_escape_text(
            _("Change transition") if contact.kind else _("Add transition")))
        names = [filename_from_uri(clip.get_asset().props.id)
                 for clip in (contact.clip_a, contact.clip_b)]
        self.subtitle_label.set_text(_("Between «%s» and «%s»") % tuple(names))

        active_kind = contact.kind or DISSOLVE
        if active_kind in self.kind_buttons:
            self.kind_buttons[active_kind].set_active(True)
        for kind, prev in self.previews.items():
            prev.set_selected(kind == active_kind)

        active_dir = contact.direction or RIGHT
        if active_dir in self.direction_buttons:
            self.direction_buttons[active_dir].set_active(True)
        for prev in self.previews.values():
            prev.set_direction(active_dir)

        if not wipes_work(contact.clip_a, contact.clip_b) and contact.kind != SOFT_WIPE:
            self.kind_buttons[SOFT_WIPE].set_sensitive(False)
        else:
            self.kind_buttons[SOFT_WIPE].set_sensitive(True)

        self.__update_duration_range()
        duration = contact.duration if contact.kind else DEFAULT_DURATION
        self.duration_scale.set_value(duration / Gst.SECOND)
        self.__duration_changed_cb(self.duration_scale)

        self.empty_box.hide()
        self.content_box.show_all()
        self.__update_direction_visibility()

    def deactivate(self):
        """Stops animations and displays empty state."""
        for preview in self.previews.values():
            preview.stop_animation()
        self.contact = None
        self.ges_element = None
        self.content_box.hide()
        self.empty_box.show_all()

    def __card_enter_cb(self, button, event, preview):
        preview.set_hovered(True)
        return False

    def __card_leave_cb(self, button, event, preview):
        preview.set_hovered(False)
        return False

    def __direction_toggled_cb(self, button):
        if button.get_active():
            direction = self.get_direction()
            for preview in self.previews.values():
                preview.set_direction(direction)

    def __update_direction_visibility(self):
        self.direction_box.set_visible(self.get_kind() in DIRECTED_KINDS)

    def get_direction(self):
        for direction, button in self.direction_buttons.items():
            if button.get_active():
                return direction
        return None

    def get_kind(self):
        for kind, button in self.kind_buttons.items():
            if button.get_active():
                return kind
        return None

    def __update_duration_range(self):
        if not self.contact:
            return
        max_duration = get_max_duration(self.contact, self.get_kind()) / Gst.SECOND
        min_duration = min(MIN_DURATION / Gst.SECOND, max_duration)
        self.duration_scale.set_range(min_duration, max(max_duration, min_duration))

    def __kind_toggled_cb(self, button):
        for kind, btn in self.kind_buttons.items():
            preview = self.previews.get(kind)
            if preview:
                preview.set_selected(btn.get_active())
        if button.get_active() and hasattr(self, "duration_scale"):
            self.__update_duration_range()
        if button.get_active() and hasattr(self, "direction_box"):
            self.__update_direction_visibility()

    def __duration_changed_cb(self, scale):
        self.duration_label.set_markup("<b>%s</b>" % GLib.markup_escape_text(
            format_seconds(scale.get_value() * Gst.SECOND)))

    def __change(self, change):
        if not self.contact:
            return
        pipeline = self.app.project_manager.current_project.pipeline
        with self.app.action_log.started("transition",
                                         finalizing_action=CommitTimelineFinalizingAction(pipeline),
                                         toplevel=True):
            change()
        layer = self.contact.clip_a.get_layer()
        if layer and hasattr(layer, "schedule_update_gaps"):
            layer.schedule_update_gaps()

    def __apply_clicked_cb(self, unused_button):
        if not self.contact:
            return
        duration = round(self.duration_scale.get_value() * 10) * Gst.SECOND // 10
        kind = self.get_kind()
        direction = self.get_direction()
        self.__change(lambda: set_transition(self.contact, kind, duration, direction))
        if kind not in OVERLAPPING_KINDS:
            self.deactivate()

    def __remove_clicked_cb(self, unused_button):
        if not self.contact:
            return
        self.__change(lambda: remove_transition(self.contact))
        self.deactivate()
