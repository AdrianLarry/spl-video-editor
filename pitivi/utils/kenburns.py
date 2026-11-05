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
"""The automatic zoom drawn with sub-pixel precision.

The compositor of GStreamer places and scales the sources in whole
pixels: in a slow zoom the image grows 4, 5, 4 pixels per frame instead of
4.5 and what is inside it moves back and forth, it shakes. The element of
this module draws the image with cairo, which places it with decimals, as
PhotoFilmStrip and MLT do.

The element gets the image and makes the whole frame: the image placed in
a rectangle of the frame, made bigger around an anchor by the zoom.
"""
import cairo
import numpy
from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstBase
from gi.repository import GstVideo

ELEMENT_NAME = "splzoom"

# The blurred fill is made small, the bigger side of the frame being this
# long, as by the blurfill module.
BACKGROUND_SIZE = 480

# How many bytes of the image are compared to know whether it changed.
SAMPLE_SIZE = 4096

# cairo draws in ARGB32, which is BGRA in the memory of little endian
# machines.
CAPS = Gst.Caps.from_string("video/x-raw,format=BGRA")


class ZoomFilter(GstBase.BaseTransform):
    """Places the image in the frame and zooms it, with sub-pixel precision.

    Attributes:
        zoom (float): How much bigger the image is, 1 being its size in the
            rectangle. Animated by the controller of GStreamer.
        anchor-x, anchor-y (float): The point of the frame which stays still
            while zooming, as fractions of its size.
        offset-x, offset-y (float): How much the frame is slid after the
            zoom, for the pushes. Animated by the controller of GStreamer.
        rect-x, rect-y, rect-width, rect-height (float): Where the image is in
            the frame, without zoom.
        max-zoom (float): The biggest zoom, for making the image smaller only
            once, to that size.
        static (bool): Whether the image is the same in all the frames, a
            photo, so that it is made smaller only once.
        fill-sigma (float): When not 0, a blurred copy of the image covers
            the frame behind it, made once for a photo. The blurred fill of
            the photos which zoom, cheaper than its own effect.
    """

    __gstmetadata__ = ("SPL zoom", "Filter/Effect/Video",
                       "Zooms the image with sub-pixel precision", "SPL")

    __gsttemplates__ = (
        Gst.PadTemplate.new("sink", Gst.PadDirection.SINK, Gst.PadPresence.ALWAYS, CAPS),
        Gst.PadTemplate.new("src", Gst.PadDirection.SRC, Gst.PadPresence.ALWAYS, CAPS))

    __gproperties__ = {
        "zoom": (float, "Zoom", "How much bigger the image is", 0.01, 100.0, 1.0,
                 GObject.ParamFlags.READWRITE | Gst.PARAM_CONTROLLABLE),
        "anchor-x": (float, "Anchor X", "The still point, horizontally", -10.0, 10.0, 0.5,
                     GObject.ParamFlags.READWRITE | Gst.PARAM_CONTROLLABLE),
        "anchor-y": (float, "Anchor Y", "The still point, vertically", -10.0, 10.0, 0.5,
                     GObject.ParamFlags.READWRITE | Gst.PARAM_CONTROLLABLE),
        "offset-x": (float, "Offset X", "How much the frame is slid, for the pushes",
                     -100000.0, 100000.0, 0.0, GObject.ParamFlags.READWRITE | Gst.PARAM_CONTROLLABLE),
        "offset-y": (float, "Offset Y", "How much the frame is slid, for the pushes",
                     -100000.0, 100000.0, 0.0, GObject.ParamFlags.READWRITE | Gst.PARAM_CONTROLLABLE),
        "rect-x": (float, "Rect X", "Where the image starts", -100000.0, 100000.0, 0.0,
                   GObject.ParamFlags.READWRITE),
        "rect-y": (float, "Rect Y", "Where the image starts", -100000.0, 100000.0, 0.0,
                   GObject.ParamFlags.READWRITE),
        "rect-width": (float, "Rect width", "The width of the image, 0 for the frame",
                       0.0, 100000.0, 0.0, GObject.ParamFlags.READWRITE),
        "rect-height": (float, "Rect height", "The height of the image, 0 for the frame",
                        0.0, 100000.0, 0.0, GObject.ParamFlags.READWRITE),
        "max-zoom": (float, "Max zoom", "The biggest zoom", 1.0, 100.0, 2.0,
                     GObject.ParamFlags.READWRITE),
        "static": (bool, "Static", "Whether the image is the same in all the frames", False,
                   GObject.ParamFlags.READWRITE),
        "fill-sigma": (float, "Fill sigma", "The blur of the copy filling the frame, 0 for none",
                       0.0, 100.0, 0.0, GObject.ParamFlags.READWRITE),
    }

    def __init__(self):
        GstBase.BaseTransform.__init__(self)
        self.props_values = {"zoom": 1.0, "anchor-x": 0.5, "anchor-y": 0.5,
                             "offset-x": 0.0, "offset-y": 0.0,
                             "rect-x": 0.0, "rect-y": 0.0, "rect-width": 0.0, "rect-height": 0.0,
                             "max-zoom": 2.0, "static": False, "fill-sigma": 0.0}
        self.in_info = None
        self.out_info = None
        # The image made smaller to the biggest size it is shown, and what
        # it was made for.
        self.__base = None
        self.__base_key = None
        self.__base_data = None
        self.__background = None
        self.__background_data = None
        self.__returned_caps = []

    def do_get_property(self, pspec):
        return self.props_values[pspec.name]

    def do_set_property(self, pspec, value):
        if pspec.name in ("rect-width", "rect-height", "max-zoom", "static", "fill-sigma"):
            self.__base = None
        self.props_values[pspec.name] = value

    def do_transform_caps(self, direction, caps, filter_caps):
        # Any size on the other side, the frame is not the image.
        other = Gst.Caps.new_empty()
        for index in range(caps.get_size()):
            structure = caps.get_structure(index).copy()
            structure.remove_field("width")
            structure.remove_field("height")
            structure.remove_field("pixel-aspect-ratio")
            other.append_structure(structure)
        other = Gst.Caps.from_string(
            other.to_string().replace(
                "video/x-raw", "video/x-raw, width=(int)[ 1, 32768 ], height=(int)[ 1, 32768 ]"))
        if filter_caps:
            other = filter_caps.intersect_full(other, Gst.CapsIntersectMode.FIRST)
        # PyGObject gives its reference to GStreamer and drops it again when
        # the wrapper goes away, so the wrappers are kept. The caps are
        # negotiated a few times only.
        self.__returned_caps.append(other)
        return other

    def do_set_caps(self, incaps, outcaps):
        # The image made smaller is kept: the caps are set again when the
        # clips around change, and making it again takes long for a photo.
        self.in_info = GstVideo.VideoInfo.new_from_caps(incaps)
        self.out_info = GstVideo.VideoInfo.new_from_caps(outcaps)
        return True

    def do_transform_size(self, direction, caps, size, othercaps):
        info = GstVideo.VideoInfo.new_from_caps(othercaps)
        return True, info.size

    def do_transform_meta(self, outbuf, meta, inbuf):
        # GES keeps the alpha and the position of the clip in a meta of the
        # buffers, the fades and the transitions need it.
        if meta.info.api == GstVideo.video_meta_api_get_type():
            return False
        return True

    def do_before_transform(self, buffer):
        stream_time = self.segment.to_stream_time(Gst.Format.TIME, buffer.pts)
        if stream_time != Gst.CLOCK_TIME_NONE:
            self.sync_values(stream_time)

    def __get_rect(self):
        frame_width, frame_height = self.out_info.width, self.out_info.height
        width = self.props_values["rect-width"] or frame_width
        height = self.props_values["rect-height"] or frame_height
        return self.props_values["rect-x"], self.props_values["rect-y"], width, height

    def __make_base(self, inbuf):
        """Returns the image as a surface, smaller if it is shown smaller."""
        in_width, in_height = self.in_info.width, self.in_info.height
        unused_x, unused_y, width, height = self.__get_rect()
        max_zoom = self.props_values["max-zoom"]
        # Never bigger than the image: cairo enlarges it when drawing.
        base_width = min(in_width, max(1, round(width * max_zoom)))
        base_height = min(in_height, max(1, round(height * max_zoom)))
        res, mapinfo = inbuf.map(Gst.MapFlags.READ)
        assert res
        try:
            # A photo is made smaller once, but another effect before this
            # one can change it, so a sample of its pixels tells whether it
            # changed.
            key = None
            if self.props_values["static"]:
                step = max(1, mapinfo.size // SAMPLE_SIZE) | 1
                key = (in_width, in_height, base_width, base_height,
                       self.out_info.width, self.out_info.height, self.props_values["fill-sigma"],
                       bytes(mapinfo.data[::step]))
            if self.props_values["static"] and self.__base_key == key and self.__base:
                return self.__base
            data = bytearray(mapinfo.data)
        finally:
            inbuf.unmap(mapinfo)
        image = cairo.ImageSurface.create_for_data(
            data, cairo.FORMAT_ARGB32, in_width, in_height, self.in_info.stride[0])
        if (base_width, base_height) == (in_width, in_height):
            base = image
        else:
            # Made smaller only once, with the good filter which averages
            # the pixels, so that the small details do not flicker.
            base = cairo.ImageSurface(cairo.FORMAT_ARGB32, base_width, base_height)
            cr = cairo.Context(base)
            cr.scale(base_width / in_width, base_height / in_height)
            cr.set_source_surface(image, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.paint()
            base.flush()
        self.__base = base
        self.__base_key = key
        # Keep the data alive as long as the surface which uses it.
        self.__base_data = data
        self.__background = self.__make_background(base) if self.props_values["fill-sigma"] else None
        return base

    def __make_background(self, base):
        """Returns the image covering a small frame, blurred."""
        frame_width, frame_height = self.out_info.width, self.out_info.height
        ratio = BACKGROUND_SIZE / max(frame_width, frame_height)
        small_width = max(2, round(frame_width * ratio))
        small_height = max(2, round(frame_height * ratio))
        small = cairo.ImageSurface(cairo.FORMAT_ARGB32, small_width, small_height)
        cr = cairo.Context(small)
        cover = max(small_width / base.get_width(), small_height / base.get_height())
        cr.translate(small_width / 2, small_height / 2)
        cr.scale(cover, cover)
        cr.translate(-base.get_width() / 2, -base.get_height() / 2)
        cr.set_source_surface(base, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        small.flush()
        pixels = numpy.ndarray((small_height, small.get_stride() // 4, 4), numpy.uint8,
                               small.get_data())[:, :small_width].astype(numpy.float32)
        blurred = blur(pixels, self.props_values["fill-sigma"])
        data = numpy.ascontiguousarray(numpy.clip(blurred + 0.5, 0, 255).astype(numpy.uint8))
        background = cairo.ImageSurface.create_for_data(
            memoryview(data).cast("B"), cairo.FORMAT_ARGB32, small_width, small_height, small_width * 4)
        self.__background_data = data
        return background

    def do_transform(self, inbuf, outbuf):
        base = self.__make_base(inbuf)
        frame_width, frame_height = self.out_info.width, self.out_info.height
        rect_x, rect_y, width, height = self.__get_rect()
        zoom = self.props_values["zoom"]
        anchor_x = self.props_values["anchor-x"] * frame_width
        anchor_y = self.props_values["anchor-y"] * frame_height

        res, mapinfo = outbuf.map(Gst.MapFlags.WRITE)
        assert res
        try:
            # Drawn right into the buffer, with no copy.
            frame = cairo.ImageSurface.create_for_data(
                mapinfo.data, cairo.FORMAT_ARGB32, frame_width, frame_height,
                self.out_info.stride[0])
            cr = cairo.Context(frame)
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            # The frame made bigger around the anchor, and slid for the
            # pushes.
            cr.translate(self.props_values["offset-x"], self.props_values["offset-y"])
            # As a camera: what is zoomed out of the frame is not seen, also
            # when the frame slides.
            cr.rectangle(0, 0, frame_width, frame_height)
            cr.clip()
            cr.translate(anchor_x, anchor_y)
            cr.scale(zoom, zoom)
            cr.translate(-anchor_x, -anchor_y)
            if self.__background:
                cr.save()
                cr.scale(frame_width / self.__background.get_width(),
                         frame_height / self.__background.get_height())
                cr.set_source_surface(self.__background, 0, 0)
                cr.get_source().set_filter(cairo.FILTER_BILINEAR)
                cr.get_source().set_extend(cairo.EXTEND_PAD)
                cr.rectangle(0, 0, self.__background.get_width(), self.__background.get_height())
                cr.fill()
                cr.restore()
            # The image in its rectangle.
            cr.translate(rect_x, rect_y)
            cr.scale(width / base.get_width(), height / base.get_height())
            cr.set_source_surface(base, 0, 0)
            # Close to its size, bilinear is smooth and does not flicker.
            cr.get_source().set_filter(cairo.FILTER_BILINEAR)
            # The edge pixels go on outside, the rectangle alone smooths the
            # edges, else they would be darker.
            cr.get_source().set_extend(cairo.EXTEND_PAD)
            cr.rectangle(0, 0, base.get_width(), base.get_height())
            cr.fill()
            frame.flush()
            # The surface uses the memory of the buffer until it is freed.
            del cr
            frame.finish()
            del frame
        finally:
            outbuf.unmap(mapinfo)
        return Gst.FlowReturn.OK


def blur(pixels: numpy.ndarray, sigma: float) -> numpy.ndarray:
    """Blurs the pixels, rows by columns by channels, almost as a gaussian.

    Three box blurs one after the other, horizontally and vertically.
    """
    # The width of the boxes giving the sigma, for three passes.
    width = max(1, int(round((12 * sigma * sigma / 3 + 1) ** 0.5)))
    if width % 2 == 0:
        width += 1
    for unused in range(3):
        for axis in (0, 1):
            pixels = _box_blur(pixels, width, axis)
    return pixels


def _box_blur(pixels: numpy.ndarray, width: int, axis: int) -> numpy.ndarray:
    """Averages each pixel with its neighbors along the axis, the edges repeated."""
    radius = width // 2
    pad = [(0, 0)] * pixels.ndim
    pad[axis] = (radius + 1, radius)
    padded = numpy.pad(pixels, pad, mode="edge")
    sums = numpy.cumsum(padded, axis=axis)
    size = pixels.shape[axis]
    upper = numpy.take(sums, range(width, width + size), axis=axis)
    lower = numpy.take(sums, range(0, size), axis=axis)
    return (upper - lower) / width


GObject.type_register(ZoomFilter)


def register() -> bool:
    """Registers the element for this process, returns whether it worked."""
    if Gst.ElementFactory.find(ELEMENT_NAME):
        return True
    return Gst.Element.register(None, ELEMENT_NAME, Gst.Rank.NONE, ZoomFilter)
