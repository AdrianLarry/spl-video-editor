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
    """

    color: Tuple[float, float, float, float]
    line_width: float
    corner_radius: float


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


SHAPES: Dict[str, Shape] = {}


def register_shape(shape: Shape) -> None:
    """Makes the shape available, by its name."""
    SHAPES[shape.name] = shape


for _shape in (Frame(), Circle(), Arrow()):
    register_shape(_shape)
