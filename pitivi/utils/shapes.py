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
"""The shapes drawn over the video, as for tutorials.

Each shape is a small class registered by its name: it says how it is
shown to the user and draws itself with cairo. A shape is a box, placed
by two corners, or a line, placed by its two ends.

Adding a shape is writing its class and registering it::

    class Star(Shape):
        name = "star"
        ...

    register_shape(Star())
"""
import math
from gettext import gettext as _
from typing import Dict
from typing import NamedTuple
from typing import Tuple

import cairo

# The sizes of the style, as line widths, are in pixels of a frame whose
# shorter side is this long, so they look the same in any frame.
REFERENCE_SIZE = 1080

BOX = "box"
LINE = "line"


class Style(NamedTuple):
    """How a shape is drawn.

    Attributes:
        color (Tuple[float, float, float, float]): The red, green, blue and
            alpha, from 0 to 1.
        line_width (float): The width of the line, in pixels of the frame.
        corner_radius (float): The radius of the corners of the boxes, in
            pixels of the frame.
        text (str): The text or number to draw on shapes supporting text.
    """

    color: Tuple[float, float, float, float]
    line_width: float
    corner_radius: float
    text: str = "1"


class Shape:
    """A shape drawn over the video.

    Attributes:
        name (str): The name saved in the project.
        label (str): The name shown to the user.
        kind (str): BOX or LINE.
        has_corners (bool): Whether the corners can be rounded.
    """

    name = ""
    label = ""
    kind = BOX
    has_corners = False

    def draw(self, cr: cairo.Context, start: Tuple[float, float], end: Tuple[float, float],
             style: Style) -> None:
        """Draws the shape, placed by two points in pixels of the frame.

        For a box, they are opposite corners, in any order. For a line,
        they are its ends.
        """
        raise NotImplementedError()

    def margin(self, style: Style) -> float:
        """Returns how far out of the box of its points the shape is drawn."""
        return style.line_width


def _box(start, end):
    """Returns the x, y, width and height of the box between the points."""
    (x1, y1), (x2, y2) = start, end
    return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)


def _set_line(cr, style):
    cr.set_source_rgba(*style.color)
    cr.set_line_width(style.line_width)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)


class Frame(Shape):
    """A rectangle with rounded corners, around what is to be seen."""

    name = "frame"
    label = _("Frame")
    has_corners = True

    def draw(self, cr, start, end, style):
        x, y, width, height = _box(start, end)
        # The line is inside the box, as seen while editing.
        inset = style.line_width / 2
        x, y = x + inset, y + inset
        width, height = max(0.0, width - style.line_width), max(0.0, height - style.line_width)
        radius = max(0.0, min(style.corner_radius - inset, width / 2, height / 2))
        if radius:
            cr.new_sub_path()
            cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
            cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
            cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
            cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
            cr.close_path()
        else:
            cr.rectangle(x, y, width, height)
        _set_line(cr, style)
        cr.stroke()

    def margin(self, style):
        return 0.0


class Fill(Shape):
    """A translucent filled box with rounded corners."""

    name = "fill"
    label = _("Filled")
    has_corners = True

    def draw(self, cr, start, end, style):
        x, y, width, height = _box(start, end)
        inset = style.line_width / 2 if style.line_width else 0.0
        x, y = x + inset, y + inset
        width, height = max(0.0, width - style.line_width), max(0.0, height - style.line_width)
        radius = max(0.0, min(style.corner_radius - inset, width / 2, height / 2)) if style.corner_radius > inset else 0.0
        if radius:
            cr.new_sub_path()
            cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
            cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
            cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
            cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
            cr.close_path()
        else:
            cr.rectangle(x, y, width, height)
        r, g, b, a = style.color
        cr.set_source_rgba(r, g, b, a * 0.45)
        cr.fill_preserve()
        if style.line_width > 0:
            _set_line(cr, style)
            cr.stroke()
        else:
            cr.new_path()

    def margin(self, style):
        return 0.0


class Spotlight(Shape):
    """Darkens the frame outside the box, keeping the inside clear."""

    name = "spotlight"
    label = _("Spotlight")
    has_corners = True

    def draw(self, cr, start, end, style):
        x_min, y_min, x_max, y_max = cr.clip_extents()
        cr.save()
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        # Outer boundary covering the whole area
        cr.rectangle(x_min, y_min, x_max - x_min, y_max - y_min)

        # Inner cutout
        x, y, width, height = _box(start, end)
        radius = max(0.0, min(style.corner_radius, width / 2, height / 2))
        if radius:
            cr.new_sub_path()
            cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
            cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
            cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
            cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
            cr.close_path()
        else:
            cr.rectangle(x, y, width, height)

        cr.set_source_rgba(0.0, 0.0, 0.0, 0.65 * style.color[3])
        cr.fill()
        cr.restore()

        # Border around the spotlight opening
        if style.line_width > 0:
            inset = style.line_width / 2
            bx, by = x + inset, y + inset
            bw, bh = max(0.0, width - style.line_width), max(0.0, height - style.line_width)
            bradius = max(0.0, min(style.corner_radius - inset, bw / 2, bh / 2)) if style.corner_radius > inset else 0.0
            if bradius:
                cr.new_sub_path()
                cr.arc(bx + bw - bradius, by + bradius, bradius, -math.pi / 2, 0)
                cr.arc(bx + bw - bradius, by + bh - bradius, bradius, 0, math.pi / 2)
                cr.arc(bx + bradius, by + bh - bradius, bradius, math.pi / 2, math.pi)
                cr.arc(bx + bradius, by + bradius, bradius, math.pi, 3 * math.pi / 2)
                cr.close_path()
            else:
                cr.rectangle(bx, by, bw, bh)
            _set_line(cr, style)
            cr.stroke()

    def margin(self, style):
        # The darkened backdrop covers the entire frame
        return 100000.0


class Circle(Shape):
    """An ellipse inside the box."""

    name = "circle"
    label = _("Circle")

    def draw(self, cr, start, end, style):
        x, y, width, height = _box(start, end)
        inset = style.line_width / 2
        radius_x, radius_y = width / 2 - inset, height / 2 - inset
        if radius_x <= 0 or radius_y <= 0:
            return
        cr.save()
        cr.translate(x + width / 2, y + height / 2)
        cr.scale(radius_x, radius_y)
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.restore()
        # Stroked after restoring, the line keeps its width all around.
        _set_line(cr, style)
        cr.stroke()

    def margin(self, style):
        return 0.0


class NumberCircle(Shape):
    """A circular badge with a step number (e.g. 1) centered inside."""

    name = "number"
    label = _("Number")
    has_corners = False

    def draw(self, cr, start, end, style):
        x, y, width, height = _box(start, end)
        radius = min(width, height) / 2
        if radius <= 0:
            return
        cx, cy = x + width / 2, y + height / 2
        inset = style.line_width / 2 if style.line_width else 0.0
        draw_radius = max(1.0, radius - inset)

        cr.arc(cx, cy, draw_radius, 0, 2 * math.pi)
        cr.set_source_rgba(*style.color)
        cr.fill_preserve()

        if style.line_width > 0:
            _set_line(cr, style)
            cr.stroke()
        else:
            cr.new_path()

        r, g, b, a = style.color
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        text_color = (0.08, 0.08, 0.08, a) if lum > 0.55 else (0.95, 0.95, 0.95, a)

        cr.save()
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        text = str(style.text or "1")
        # Scale font so text fits nicely inside the circle
        max_w = draw_radius * 1.45
        max_h = draw_radius * 1.3
        base_size = max(7.0, draw_radius * 1.25)
        cr.set_font_size(base_size)
        extents = cr.text_extents(text)
        scale_w = max_w / extents.width if extents.width > max_w else 1.0
        scale_h = max_h / extents.height if extents.height > max_h else 1.0
        scale = min(scale_w, scale_h)
        font_size = max(5.0, base_size * scale)
        cr.set_font_size(font_size)
        extents = cr.text_extents(text)
        tx = cx - (extents.width / 2 + extents.x_bearing)
        ty = cy - (extents.height / 2 + extents.y_bearing)
        cr.set_source_rgba(*text_color)
        cr.move_to(tx, ty)
        cr.show_text(text)
        cr.restore()

    def margin(self, style):
        return 0.0


class Arrow(Shape):
    """A line from the start, with a head at the end, pointing at something."""

    name = "arrow"
    label = _("Arrow")
    kind = LINE

    @staticmethod
    def __head(style):
        # The head grows with the line, but stays shorter than half of it.
        return style.line_width * 3.5 + 6

    def margin(self, style):
        return self.__head(style) + style.line_width

    def draw(self, cr, start, end, style):
        (x1, y1), (x2, y2) = start, end
        length = math.hypot(x2 - x1, y2 - y1)
        if not length:
            return
        head = min(self.__head(style), length / 2)
        angle = math.atan2(y2 - y1, x2 - x1)
        spread = math.radians(28)
        # The line stops inside the head, so its round end is not seen.
        back = head * math.cos(spread) * 0.6
        _set_line(cr, style)
        cr.move_to(x1, y1)
        cr.line_to(x2 - back * math.cos(angle), y2 - back * math.sin(angle))
        cr.stroke()
        cr.move_to(x2, y2)
        cr.line_to(x2 - head * math.cos(angle - spread), y2 - head * math.sin(angle - spread))
        cr.line_to(x2 - head * math.cos(angle + spread), y2 - head * math.sin(angle + spread))
        cr.close_path()
        cr.fill_preserve()
        # The corners of the head rounded as the line.
        cr.set_line_width(max(1.0, style.line_width / 2))
        cr.stroke()


class Underline(Shape):
    """A straight horizontal line under text or elements."""

    name = "underline"
    label = _("Underline")
    kind = LINE

    def draw(self, cr, start, end, style):
        (x1, y1), (x2, y2) = start, end
        _set_line(cr, style)
        cr.move_to(x1, y1)
        cr.line_to(x2, y2)
        cr.stroke()

    def margin(self, style):
        return style.line_width


SHAPES: Dict[str, Shape] = {}


def register_shape(shape: Shape) -> None:
    """Makes the shape available, by its name."""
    SHAPES[shape.name] = shape


for _shape in (Frame(), Fill(), Spotlight(), Circle(), NumberCircle(), Arrow(), Underline()):
    register_shape(_shape)
