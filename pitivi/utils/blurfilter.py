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
"""The blur of the blur transitions, cheap and only where it blurs.

gaussianblur blurs every frame, so the effect made the image small and big
again during the whole clip, losing its details also where it was not
blurred, and blurring an image of the size of a frame is slow. This element
lets the frames pass untouched where the blur is zero. Elsewhere it makes
the frame smaller for the blur asked, softens it and makes it big again
with cairo.
"""
import cairo
from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstBase
from gi.repository import GstVideo

ELEMENT_NAME = "splblur"

# The sigma is in pixels of an image whose bigger side is this long, as for
# gaussianblur on the small image made by the effect before.
REFERENCE_SIZE = 640

CAPS = Gst.Caps.from_string("video/x-raw,format=BGRA")


class BlurFilter(GstBase.BaseTransform):
    """Blurs the frames, letting them pass untouched when not blurring.

    Attributes:
        sigma (float): How much it blurs, see REFERENCE_SIZE. Animated by
            the controller of GStreamer.
    """

    __gstmetadata__ = ("SPL blur", "Filter/Effect/Video",
                       "Blurs the frames cheaply, passing them when not blurring", "SPL")

    __gsttemplates__ = (
        Gst.PadTemplate.new("sink", Gst.PadDirection.SINK, Gst.PadPresence.ALWAYS, CAPS),
        Gst.PadTemplate.new("src", Gst.PadDirection.SRC, Gst.PadPresence.ALWAYS, CAPS))

    __gproperties__ = {
        "sigma": (float, "Sigma", "How much it blurs", 0.0, 100.0, 0.0,
                  GObject.ParamFlags.READWRITE | Gst.PARAM_CONTROLLABLE),
    }

    def __init__(self):
        GstBase.BaseTransform.__init__(self)
        self.sigma = 0.0
        self.video_info = None
        self.set_passthrough(True)

    def do_get_property(self, pspec):
        return self.sigma

    def do_set_property(self, pspec, value):
        self.sigma = value

    def do_set_caps(self, incaps, outcaps):
        self.video_info = GstVideo.VideoInfo.new_from_caps(incaps)
        return True

    def do_transform_meta(self, outbuf, meta, inbuf):
        # GES keeps the alpha and the position of the clip in a meta of the
        # buffers, the fades and the transitions need it.
        return True

    def do_before_transform(self, buffer):
        stream_time = self.segment.to_stream_time(Gst.Format.TIME, buffer.pts)
        if stream_time != Gst.CLOCK_TIME_NONE:
            self.sync_values(stream_time)
        # Not blurring, the frame passes untouched and for free.
        self.set_passthrough(self.sigma < 0.05)

    def do_transform(self, inbuf, outbuf):
        width, height = self.video_info.width, self.video_info.height
        stride = self.video_info.stride[0]
        # The radius in pixels of this frame.
        radius = self.sigma * max(width, height) / REFERENCE_SIZE
        # Made smaller, averaging the pixels, and big again smoothly: the
        # stronger the blur, the smaller and the cheaper.
        scale = 1 / (1 + radius / 0.75)
        small_width = max(2, round(width * scale))
        small_height = max(2, round(height * scale))

        res, mapinfo = inbuf.map(Gst.MapFlags.READ)
        assert res
        try:
            image = cairo.ImageSurface.create_for_data(
                bytearray(mapinfo.data), cairo.FORMAT_ARGB32, width, height, stride)
        finally:
            inbuf.unmap(mapinfo)

        small = cairo.ImageSurface(cairo.FORMAT_ARGB32, small_width, small_height)
        cr = cairo.Context(small)
        cr.scale(small_width / width, small_height / height)
        cr.set_source_surface(image, 0, 0)
        # The good filter averages the pixels when making smaller.
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        small.flush()

        res, mapinfo = outbuf.map(Gst.MapFlags.WRITE)
        assert res
        try:
            frame = cairo.ImageSurface.create_for_data(mapinfo.data, cairo.FORMAT_ARGB32, width, height, stride)
            cr = cairo.Context(frame)
            cr.scale(width / small_width, height / small_height)
            cr.set_source_surface(small, 0, 0)
            # Made big again smoothly, the edge pixels going on outside.
            cr.get_source().set_filter(cairo.FILTER_BILINEAR)
            cr.get_source().set_extend(cairo.EXTEND_PAD)
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.paint()
            frame.flush()
            # The surface uses the memory of the buffer until it is freed.
            del cr
            frame.finish()
            del frame
        finally:
            outbuf.unmap(mapinfo)
        return Gst.FlowReturn.OK


GObject.type_register(BlurFilter)


def register() -> bool:
    """Registers the element for this process, returns whether it worked."""
    if Gst.ElementFactory.find(ELEMENT_NAME):
        return True
    return Gst.Element.register(None, ELEMENT_NAME, Gst.Rank.NONE, BlurFilter)
