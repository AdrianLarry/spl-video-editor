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
"""The element drawing a shape over the video, on a transparent frame.

The shape is drawn once, when its properties or the size of the frame
change, and copied in every frame. Knowing the size of the frame, the
element gives only the part of the frame where the shape is, the clip
being placed there: mixing a whole transparent frame takes long.
"""
import math
from typing import Optional
from typing import Tuple

import cairo
import numpy
from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstBase
from gi.repository import GstVideo

from pitivi.utils.shapes import REFERENCE_SIZE
from pitivi.utils.shapes import SHAPES
from pitivi.utils.shapes import Style

ELEMENT_NAME = "splshape"

# cairo draws in ARGB32, which is BGRA in the memory of little endian
# machines.
CAPS = Gst.Caps.from_string("video/x-raw,format=BGRA")

DEFAULT_COLOR = 0xFFD9531E


def color_to_rgba(color: int):
    """Returns the red, green, blue and alpha of an ARGB color, from 0 to 1."""
    return (((color >> 16) & 0xFF) / 255, ((color >> 8) & 0xFF) / 255,
            (color & 0xFF) / 255, ((color >> 24) & 0xFF) / 255)


def _style(values, frame_size) -> Style:
    scale = min(frame_size) / REFERENCE_SIZE
    return Style(color_to_rgba(values["color"]),
                 max(1.0, values["line-width"] * scale),
                 values["corner-radius"] * scale)


def shape_box(values, frame_size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """Returns the part of the frame where the shape is drawn: x, y, width, height.

    Args:
        values (dict): The properties of the element.
        frame_size (Tuple[int, int]): The width and height of the frame.
    """
    frame_width, frame_height = frame_size
    shape = SHAPES.get(values["shape"])
    # A pixel more on each side, for the smoothed edges.
    margin = (shape.margin(_style(values, frame_size)) if shape else 0) + 1
    xs = values["x1"] * frame_width, values["x2"] * frame_width
    ys = values["y1"] * frame_height, values["y2"] * frame_height
    # Out of the frame nothing is seen.
    left = min(max(0, math.floor(min(xs) - margin)), frame_width - 1)
    top = min(max(0, math.floor(min(ys) - margin)), frame_height - 1)
    right = max(min(frame_width, math.ceil(max(xs) + margin)), left + 1)
    bottom = max(min(frame_height, math.ceil(max(ys) + margin)), top + 1)
    return left, top, right - left, bottom - top


def render_shape(values, width: int, height: int, stride: int,
                 frame_size: Optional[Tuple[int, int]] = None,
                 offset: Tuple[int, int] = (0, 0)) -> numpy.ndarray:
    """Returns the BGRA pixels with the shape, rows of stride bytes.

    Args:
        values (dict): The properties of the element.
        frame_size (Optional[Tuple[int, int]]): The size of the frame, if the
            pixels are only a part of it.
        offset (Tuple[int, int]): Where the pixels are in the frame.
    """
    frame_width, frame_height = frame_size or (width, height)
    pixels = numpy.zeros((height, stride), dtype=numpy.uint8)
    shape = SHAPES.get(values["shape"])
    if not shape:
        return pixels
    surface = cairo.ImageSurface.create_for_data(
        memoryview(pixels).cast("B"), cairo.FORMAT_ARGB32, width, height, stride)
    cr = cairo.Context(surface)
    cr.translate(-offset[0], -offset[1])
    shape.draw(cr, (values["x1"] * frame_width, values["y1"] * frame_height),
               (values["x2"] * frame_width, values["y2"] * frame_height),
               _style(values, (frame_width, frame_height)))
    surface.flush()
    del cr
    surface.finish()

    # cairo multiplies the colors by the alpha, GStreamer does not.
    rows = pixels[:, :width * 4].reshape(height, width, 4)
    alpha = rows[:, :, 3:4].astype(numpy.uint16)
    partial = (alpha > 0) & (alpha < 255)
    if partial.any():
        colors = rows[:, :, :3].astype(numpy.uint16) * 255 // numpy.maximum(alpha, 1)
        rows[:, :, :3] = numpy.where(partial, numpy.minimum(colors, 255), rows[:, :, :3])
    return pixels


class ShapeFilter(GstBase.BaseTransform):
    """Draws a shape on a transparent frame.

    Attributes:
        shape (str): The name of the shape, in the shapes module.
        x1, y1, x2, y2 (float): The points placing the shape, as fractions
            of the size of the frame.
        color (int): The ARGB color.
        line-width (float): The width of the line, in pixels of a frame
            whose shorter side is 1080 pixels long.
        corner-radius (float): The radius of the corners, as the line.
        frame-width, frame-height (int): The size of the frame. When set,
            the element gives the part of the frame where the shape is, as
            told by shape_box, else a frame as the one it gets.
    """

    __gtype_name__ = "SPLShapeFilter"

    __gstmetadata__ = ("SPL shape", "Filter/Effect/Video",
                       "Draws a shape on a transparent frame", "SPL")

    __gsttemplates__ = (
        Gst.PadTemplate.new("sink", Gst.PadDirection.SINK, Gst.PadPresence.ALWAYS, CAPS),
        Gst.PadTemplate.new("src", Gst.PadDirection.SRC, Gst.PadPresence.ALWAYS, CAPS))

    __gproperties__ = {
        "shape": (str, "Shape", "The name of the shape", "frame", GObject.ParamFlags.READWRITE),
        "x1": (float, "X1", "The first point, horizontally", -10.0, 10.0, 0.3,
               GObject.ParamFlags.READWRITE),
        "y1": (float, "Y1", "The first point, vertically", -10.0, 10.0, 0.4,
               GObject.ParamFlags.READWRITE),
        "x2": (float, "X2", "The second point, horizontally", -10.0, 10.0, 0.7,
               GObject.ParamFlags.READWRITE),
        "y2": (float, "Y2", "The second point, vertically", -10.0, 10.0, 0.6,
               GObject.ParamFlags.READWRITE),
        "color": (GObject.TYPE_UINT, "Color", "The ARGB color", 0, 0xFFFFFFFF, DEFAULT_COLOR,
                  GObject.ParamFlags.READWRITE),
        "line-width": (float, "Line width", "The width of the line", 0.0, 500.0, 10.0,
                       GObject.ParamFlags.READWRITE),
        "corner-radius": (float, "Corner radius", "The radius of the corners", 0.0, 2000.0, 28.0,
                          GObject.ParamFlags.READWRITE),
        "frame-width": (int, "Frame width", "The width of the frame, 0 for the one received",
                        0, 32768, 0, GObject.ParamFlags.READWRITE),
        "frame-height": (int, "Frame height", "The height of the frame, 0 for the one received",
                         0, 32768, 0, GObject.ParamFlags.READWRITE),
    }

    def __init__(self):
        GstBase.BaseTransform.__init__(self)
        self.props_values = {"shape": "frame", "x1": 0.3, "y1": 0.4, "x2": 0.7, "y2": 0.6,
                             "color": DEFAULT_COLOR, "line-width": 10.0, "corner-radius": 28.0,
                             "frame-width": 0, "frame-height": 0}
        self.in_info = None
        self.out_info = None
        self.__pixels = None
        self.__returned_caps = []

    def do_get_property(self, pspec):
        return self.props_values[pspec.name]

    def do_set_property(self, pspec, value):
        if self.props_values.get(pspec.name) == value:
            return
        self.props_values[pspec.name] = value
        self.__pixels = None
        if self.out_info and self.__box()[2:] != (self.out_info.width, self.out_info.height):
            self.reconfigure_src()

    def __box(self, size=None):
        """Returns where the frame given is in the frame: x, y, width, height."""
        values = self.props_values
        if not values["frame-width"] or not values["frame-height"]:
            if size is None:
                size = (self.in_info.width, self.in_info.height) if self.in_info else (0, 0)
            return (0, 0) + tuple(size)
        return shape_box(values, (values["frame-width"], values["frame-height"]))

    def do_transform_caps(self, direction, caps, filter_caps):
        other = Gst.Caps.new_empty()
        for index in range(caps.get_size()):
            structure = caps.get_structure(index).copy()
            res_width, width = structure.get_int("width")
            res_height, height = structure.get_int("height")
            if direction == Gst.PadDirection.SINK and res_width and res_height:
                # The size given, with the frame received.
                unused_x, unused_y, width, height = self.__box((width, height))
                structure.set_value("width", width)
                structure.set_value("height", height)
                other.append_structure(structure)
            else:
                # Any size received, nothing of it is seen.
                structure.remove_field("width")
                structure.remove_field("height")
                other = other.merge(Gst.Caps.from_string(
                    structure.to_string().replace(
                        "video/x-raw", "video/x-raw, width=(int)[ 1, 32768 ], height=(int)[ 1, 32768 ]",
                        1)))
        if filter_caps:
            other = filter_caps.intersect_full(other, Gst.CapsIntersectMode.FIRST)
        # PyGObject gives its reference to GStreamer and drops it again when
        # the wrapper goes away, so the wrappers are kept.
        self.__returned_caps.append(other)
        return other

    def do_set_caps(self, incaps, outcaps):
        self.in_info = GstVideo.VideoInfo.new_from_caps(incaps)
        self.out_info = GstVideo.VideoInfo.new_from_caps(outcaps)
        self.__pixels = None
        return True

    def do_transform_size(self, direction, caps, size, othercaps):
        info = GstVideo.VideoInfo.new_from_caps(othercaps)
        return True, info.size

    def do_transform_meta(self, outbuf, meta, inbuf):
        # GES keeps the alpha and the position of the clip in a meta of the
        # buffers, the fades need it.
        return True

    def do_transform(self, inbuf, outbuf):
        pixels = self.__pixels
        width, height = self.out_info.width, self.out_info.height
        if pixels is None:
            values = dict(self.props_values)
            x, y, unused_width, unused_height = self.__box()
            frame_size = (values["frame-width"], values["frame-height"])
            pixels = render_shape(values, width, height, self.out_info.stride[0],
                                  frame_size if all(frame_size) else None, (x, y))
            self.__pixels = pixels
        res, mapinfo = outbuf.map(Gst.MapFlags.WRITE)
        if not res:
            return Gst.FlowReturn.ERROR
        try:
            frame = numpy.frombuffer(mapinfo.data, dtype=numpy.uint8, count=pixels.size)
            frame[:] = pixels.reshape(-1)
        finally:
            outbuf.unmap(mapinfo)
        return Gst.FlowReturn.OK


GObject.type_register(ShapeFilter)


def register() -> bool:
    """Registers the element for this process, returns whether it worked."""
    if Gst.ElementFactory.find(ELEMENT_NAME):
        return True
    return Gst.Element.register(None, ELEMENT_NAME, Gst.Rank.NONE, ShapeFilter)
