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
"""Moving and resizing the shape of an overlay in the viewer.

A box has handles on its corners and sides, a line on its ends. Dragging
the shape moves it.
"""
import numpy
from gi.repository import GES

from pitivi.clip_properties.overlay import get_shape_name
from pitivi.clip_properties.overlay import get_values
from pitivi.clip_properties.overlay import set_values
from pitivi.undo.timeline import FlushSeekFinalizingAction
from pitivi.utils.motion import get_frame_size
from pitivi.utils.shapes import BOX
from pitivi.utils.shapes import REFERENCE_SIZE
from pitivi.utils.shapes import SHAPES
from pitivi.viewer.crop_overlay import HANDLE_COLOR
from pitivi.viewer.crop_overlay import HOVERED_HANDLE_COLOR
from pitivi.viewer.overlay import Overlay

# How close to a handle or a line the pointer grabs it, in pixels of the viewer.
GRAB_DISTANCE = 12
HANDLE_RADIUS = 6
# The smallest box, as a fraction of the frame.
MIN_SIZE = 0.02

# The handles of a box: the sides of the box they move.
BOX_HANDLES = {
    ("x1", "y1"): "nw-resize", ("x2", "y1"): "ne-resize",
    ("x1", "y2"): "sw-resize", ("x2", "y2"): "se-resize",
    ("y1",): "n-resize", ("y2",): "s-resize",
    ("x1",): "w-resize", ("x2",): "e-resize",
}
LINE_HANDLES = {("x1", "y1"): "crosshair", ("x2", "y2"): "crosshair"}


class ShapeOverlay(Overlay):
    """Edits the place of the shape of an overlay clip.

    Attributes:
        hovered_handle (tuple): The properties moved by the handle under
            the pointer, if any.
    """

    def __init__(self, stack, action_log, source: GES.VideoTestSource):
        Overlay.__init__(self, stack, source)
        self.__action_log = action_log
        self.clip = source.get_parent()
        self.hovered_handle = None
        self.__grabbed = None
        self.__click = None
        self.__click_values = None
        self.__recording = False

    def __is_box(self):
        shape = SHAPES.get(get_shape_name(self.clip))
        return shape is None or shape.kind == BOX

    # Geometry: the points of the shape in pixels of the viewer.

    def __canvas(self):
        """Returns where the frame is shown in the viewer: offset and size."""
        frame_size = numpy.array(get_frame_size(self._source), dtype=float)
        window_size = numpy.array(self.stack.window_size, dtype=float)
        scale = min(window_size / frame_size)
        return (window_size - frame_size * scale) / 2, frame_size * scale

    def __to_window(self, x, y):
        offset, size = self.__canvas()
        return offset + numpy.array([x, y]) * size

    def __points(self, values=None):
        values = values or get_values(self.clip)
        if "x1" not in values:
            return None
        return (self.__to_window(values["x1"], values["y1"]),
                self.__to_window(values["x2"], values["y2"]))

    def __handles(self):
        """Returns the handles and where they are, in pixels of the viewer."""
        points = self.__points()
        if not points:
            return {}
        (x1, y1), (x2, y2) = points
        if not self.__is_box():
            return {("x1", "y1"): (x1, y1), ("x2", "y2"): (x2, y2)}
        coords = {"x1": x1, "x2": x2, "y1": y1, "y2": y2}
        handles = {}
        for props in BOX_HANDLES:
            x = coords[props[0]] if props[0].startswith("x") else (x1 + x2) / 2
            y = coords[props[-1]] if props[-1].startswith("y") else (y1 + y2) / 2
            handles[props] = (x, y)
        return handles

    def __line_width(self):
        """Returns the width of the line of the shape, in pixels of the viewer."""
        unused_offset, size = self.__canvas()
        values = get_values(self.clip)
        return values.get("line-width", 0) * min(size) / REFERENCE_SIZE

    def __is_over_shape(self, cursor):
        points = self.__points()
        if not points:
            return False
        start, end = points
        if self.__is_box():
            low, high = numpy.minimum(start, end), numpy.maximum(start, end)
            return bool((low - GRAB_DISTANCE <= cursor).all() and (cursor <= high + GRAB_DISTANCE).all())
        # Close to the line.
        segment = end - start
        length = numpy.dot(segment, segment)
        along = 0.0 if not length else max(0.0, min(1.0, numpy.dot(cursor - start, segment) / length))
        distance = numpy.linalg.norm(cursor - (start + along * segment))
        return distance <= max(GRAB_DISTANCE, self.__line_width() / 2 + 4)

    # Events, as sent by the stack.

    def on_hover(self, cursor_pos):
        if not self.is_visible():
            return False
        cursor = numpy.array(cursor_pos, dtype=float)
        hovered_handle = None
        if self._is_selected():
            for props, position in self.__handles().items():
                if numpy.linalg.norm(cursor - numpy.array(position)) <= GRAB_DISTANCE:
                    hovered_handle = props
                    break
        if hovered_handle != self.hovered_handle:
            self.hovered_handle = hovered_handle
            self.queue_draw()
        if hovered_handle:
            cursors = BOX_HANDLES if self.__is_box() else LINE_HANDLES
            self.stack.set_cursor(cursors[hovered_handle])
            self._hover()
            return True
        if self.__is_over_shape(cursor):
            self.stack.set_cursor("grab")
            self._hover()
            self.queue_draw()
            return True
        if self._is_hovered():
            self.unhover()
        return False

    def on_button_press(self):
        hovered = self._is_hovered()
        if not self.hovered_handle and not hovered:
            if self._is_selected():
                self._deselect()
            return
        if not self._is_selected():
            self._select()
        self.__grabbed = self.hovered_handle
        self.__click = None
        self.__click_values = get_values(self.clip)
        project = self.stack.app.project_manager.current_project
        pipeline = project.pipeline if project else None
        self.__action_log.begin("overlay change",
                                finalizing_action=FlushSeekFinalizingAction(pipeline),
                                toplevel=True)
        self.__recording = True
        if not self.__grabbed:
            self.stack.set_cursor("grabbing")

    def on_motion_notify(self, cursor_pos):
        if not self.__recording:
            return
        unused_offset, size = self.__canvas()
        delta = self.stack.get_drag_distance(numpy.array(cursor_pos, dtype=float)) / size
        values = {prop: self.__click_values[prop] for prop in ("x1", "y1", "x2", "y2")}
        if self.__grabbed:
            for prop in self.__grabbed:
                values[prop] += delta[0] if prop.startswith("x") else delta[1]
            if self.__is_box():
                self.__keep_min_size(values)
        else:
            for prop in values:
                values[prop] += delta[0] if prop.startswith("x") else delta[1]
        set_values(self.clip, values)
        self.queue_draw()
        self._commit()

    def __keep_min_size(self, values):
        """Keeps the side grabbed from going past the other one."""
        for low, high in (("x1", "x2"), ("y1", "y2")):
            if low in self.__grabbed:
                values[low] = min(values[low], values[high] - MIN_SIZE)
            if high in self.__grabbed:
                values[high] = max(values[high], values[low] + MIN_SIZE)

    def on_button_release(self, cursor_position):
        if self.__recording:
            self.__recording = False
            self.__action_log.commit("overlay change")
        self.__grabbed = None
        self.__click_values = None
        self.on_hover(cursor_position)
        self.queue_draw()

    def update_from_source(self):
        self.queue_draw()

    def do_draw(self, cr):
        selected = self._is_selected()
        if not selected and not self._is_hovered():
            return
        points = self.__points()
        if not points:
            return
        (x1, y1), (x2, y2) = points

        # The box of the shape, or its line, thin and dashed.
        cr.set_line_width(1)
        cr.set_dash([5, 4])
        if self.__is_box():
            cr.rectangle(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        else:
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
        cr.set_source_rgba(0, 0, 0, 0.6)
        cr.stroke_preserve()
        cr.set_dash([5, 4], 5)
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.stroke()
        cr.set_dash([])
        if not selected:
            return

        # The handles, round and in the orange of the actions.
        active = self.__grabbed or self.hovered_handle
        for props, (x, y) in self.__handles().items():
            cr.arc(x, y, HANDLE_RADIUS, 0, 2 * numpy.pi)
            cr.set_source_rgb(*(HOVERED_HANDLE_COLOR if props == active else HANDLE_COLOR))
            cr.fill_preserve()
            cr.set_line_width(2)
            cr.set_source_rgb(1, 1, 1)
            cr.stroke()
