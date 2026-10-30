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
"""A speedometer showing how fast the video is exported, as in a car."""
import locale
import math
from gettext import gettext as _

import cairo
from gi.repository import Gtk
from gi.repository import Pango
from gi.repository import PangoCairo

MAX_SPEED = 4.0
# Above it the arc is red, as the red zone of a car.
RED_ZONE = 3.0
# The arc goes from the bottom left to the bottom right, through the top.
START_ANGLE = math.radians(150)
SWEEP = math.radians(240)
ORANGE = (0xD9 / 255, 0x53 / 255, 0x1E / 255)
LIGHT_ORANGE = (0xF4 / 255, 0xA2 / 255, 0x61 / 255)
RED = (0xE0 / 255, 0x2B / 255, 0x2B / 255)
# How fast the needle reaches the speed, per second.
NEEDLE_RATE = 4.0


class Speedometer(Gtk.DrawingArea):
    """Shows a speed between 0 and MAX_SPEED with a moving needle."""

    def __init__(self):
        Gtk.DrawingArea.__init__(self)
        self.set_size_request(200, 180)
        self.set_halign(Gtk.Align.CENTER)
        self.__speed = None
        self.__needle = 0.0
        self.__last_frame_time = None
        self.__tick_id = 0
        self.connect("draw", self.__draw_cb)
        self.connect("unrealize", lambda unused_widget: self.__stop_ticking())

    def set_speed(self, speed):
        """Sets the speed shown, None while it is not known."""
        self.__speed = speed
        if self.__tick_id == 0:
            self.__last_frame_time = None
            self.__tick_id = self.add_tick_callback(self.__tick_cb)
        self.queue_draw()

    def __stop_ticking(self):
        if self.__tick_id:
            self.remove_tick_callback(self.__tick_id)
            self.__tick_id = 0

    def __tick_cb(self, unused_widget, frame_clock):
        now = frame_clock.get_frame_time() / 1e6
        target = min(self.__speed or 0.0, MAX_SPEED)
        if self.__last_frame_time is not None:
            # The needle eases towards the speed, as a real one.
            step = 1 - math.exp(-NEEDLE_RATE * (now - self.__last_frame_time))
            self.__needle += (target - self.__needle) * step
        self.__last_frame_time = now
        self.queue_draw()
        if abs(target - self.__needle) < 0.002:
            self.__needle = target
            self.__tick_id = 0
            return False
        return True

    @staticmethod
    def __angle(speed):
        return START_ANGLE + SWEEP * speed / MAX_SPEED

    def __draw_cb(self, unused_widget, cr):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        fg = self.get_style_context().get_color(self.get_state_flags())
        # The arc ends at half the radius under the center.
        radius = min(width / 2 - 10, (height - 16) / 1.55)
        cx, cy = width / 2, radius + 10
        line = max(6.0, radius / 7)

        # The track.
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(line)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.12)
        cr.arc(cx, cy, radius, self.__angle(0), self.__angle(MAX_SPEED))
        cr.stroke()

        # The red zone, faint until the needle reaches it.
        hot = self.__needle >= RED_ZONE
        cr.set_source_rgba(*RED, 0.9 if hot else 0.3)
        cr.set_line_cap(cairo.LINE_CAP_BUTT)
        cr.arc(cx, cy, radius, self.__angle(RED_ZONE), self.__angle(MAX_SPEED))
        cr.stroke()

        # The speed, from light to deep orange.
        if self.__needle > 0.01:
            start, end = self.__angle(0), self.__angle(min(self.__needle, RED_ZONE))
            gradient = cairo.LinearGradient(cx - radius, cy, cx + radius, cy)
            gradient.add_color_stop_rgb(0, *LIGHT_ORANGE)
            gradient.add_color_stop_rgb(1, *ORANGE)
            cr.set_source(gradient)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.arc(cx, cy, radius, start, end)
            cr.stroke()

        # The marks, one each half, numbered each one.
        layout = PangoCairo.create_layout(cr)
        font = self.get_style_context().get_font(self.get_state_flags()).copy()
        font.set_size(int(font.get_size() * 0.8))
        layout.set_font_description(font)
        steps = int(MAX_SPEED * 2)
        for index in range(steps + 1):
            speed = index / 2
            angle = self.__angle(speed)
            whole = index % 2 == 0
            inner = radius - line / 2 - (9 if whole else 5)
            outer = radius - line / 2 - 2
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.6 if whole else 0.3)
            cr.set_line_width(2 if whole else 1)
            cr.move_to(cx + inner * math.cos(angle), cy + inner * math.sin(angle))
            cr.line_to(cx + outer * math.cos(angle), cy + outer * math.sin(angle))
            cr.stroke()
            if whole:
                layout.set_text("%d" % speed, -1)
                text_width, text_height = layout.get_pixel_size()
                distance = inner - 9
                cr.move_to(cx + distance * math.cos(angle) - text_width / 2,
                           cy + distance * math.sin(angle) - text_height / 2)
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.55)
                PangoCairo.show_layout(cr, layout)

        # The needle.
        angle = self.__angle(self.__needle)
        length = radius - line - 10
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(3)
        cr.set_source_rgb(*(RED if hot else ORANGE))
        cr.move_to(cx - 10 * math.cos(angle), cy - 10 * math.sin(angle))
        cr.line_to(cx + length * math.cos(angle), cy + length * math.sin(angle))
        cr.stroke()
        cr.arc(cx, cy, 6, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 1)
        cr.arc(cx, cy, 2.5, 0, 2 * math.pi)
        cr.fill()

        # The speed as a number, under the needle.
        if self.__speed is None:
            text = "–"
        else:
            text = "%s×" % locale.format_string("%.1f", self.__speed)
        font = self.get_style_context().get_font(self.get_state_flags()).copy()
        font.set_weight(Pango.Weight.BOLD)
        font.set_size(int(font.get_size() * 1.6))
        layout.set_font_description(font)
        layout.set_text(text, -1)
        text_width, text_height = layout.get_pixel_size()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 1)
        cr.move_to(cx - text_width / 2, cy + radius * 0.3)
        PangoCairo.show_layout(cr, layout)
        caption_top = cy + radius * 0.3 + text_height
        font = self.get_style_context().get_font(self.get_state_flags()).copy()
        font.set_size(int(font.get_size() * 0.8))
        layout.set_font_description(font)
        layout.set_text(_("speed"), -1)
        text_width, unused_height = layout.get_pixel_size()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.55)
        cr.move_to(cx - text_width / 2, caption_top)
        PangoCairo.show_layout(cr, layout)
        return False
