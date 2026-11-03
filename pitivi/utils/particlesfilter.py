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
"""The element rendering procedural particle effects over video frames.

Draws snow, confetti, sparkles or smoke directly over the video frame with
smooth alpha blending. Deterministic in time, seekable, and lightweight.
"""
import cairo
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstBase', '1.0')
gi.require_version('GstVideo', '1.0')
from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstBase
from gi.repository import GstVideo

from pitivi.utils.particles import render_particles

ELEMENT_NAME = "splparticles"

CAPS = Gst.Caps.from_string("video/x-raw,format=BGRA")


class ParticlesFilter(GstBase.BaseTransform):
    """Draws animated procedural particles over the frame.

    Attributes:
        effect (str): The particle effect type ("snow", "confetti", "sparkles", "smoke").
        amount (float): Quantity/density multiplier of particles (0.1 to 5.0).
        speed (float): Speed multiplier of the animation (0.1 to 5.0).
        size (float): Size multiplier of particles (0.1 to 5.0).
        opacity (float): Overall opacity of the particles (0.0 to 1.0).
    """

    __gtype_name__ = "SPLParticlesFilter"

    __gstmetadata__ = ("SPL particles", "Filter/Effect/Video",
                       "Renders procedural particles over video frames", "SPL")

    __gsttemplates__ = (
        Gst.PadTemplate.new("sink", Gst.PadDirection.SINK, Gst.PadPresence.ALWAYS, CAPS),
        Gst.PadTemplate.new("src", Gst.PadDirection.SRC, Gst.PadPresence.ALWAYS, CAPS))

    __gproperties__ = {
        "effect": (str, "Effect", "The particle effect to render", "snow",
                   GObject.ParamFlags.READWRITE),
        "amount": (float, "Amount", "Density multiplier of particles", 0.1, 5.0, 1.0,
                   GObject.ParamFlags.READWRITE),
        "speed": (float, "Speed", "Animation speed multiplier", 0.1, 5.0, 1.0,
                  GObject.ParamFlags.READWRITE),
        "size": (float, "Size", "Size multiplier of particles", 0.1, 5.0, 1.0,
                 GObject.ParamFlags.READWRITE),
        "opacity": (float, "Opacity", "Overall opacity of the particles", 0.0, 1.0, 0.85,
                    GObject.ParamFlags.READWRITE),
        "alpha": (float, "Alpha", "Overall opacity/alpha of the particles", 0.0, 1.0, 0.85,
                  GObject.ParamFlags.READWRITE),
    }

    def __init__(self):
        GstBase.BaseTransform.__init__(self)
        self.set_in_place(True)
        self.effect = "snow"
        self.amount = 1.0
        self.speed = 1.0
        self.size = 1.0
        self.opacity = 0.85
        self.video_info = None

    def do_get_property(self, pspec):
        if pspec.name == "effect":
            return self.effect
        if pspec.name == "amount":
            return self.amount
        if pspec.name == "speed":
            return self.speed
        if pspec.name == "size":
            return self.size
        if pspec.name in ("opacity", "alpha"):
            return self.opacity
        raise AttributeError(f"Unknown property: {pspec.name}")

    def do_set_property(self, pspec, value):
        if pspec.name == "effect":
            self.effect = value
        elif pspec.name == "amount":
            self.amount = float(value)
        elif pspec.name == "speed":
            self.speed = float(value)
        elif pspec.name == "size":
            self.size = float(value)
        elif pspec.name in ("opacity", "alpha"):
            self.opacity = float(value)
        else:
            raise AttributeError(f"Unknown property: {pspec.name}")

    def do_set_caps(self, incaps, outcaps):
        self.video_info = GstVideo.VideoInfo.new_from_caps(incaps)
        return True

    def do_transform_meta(self, outbuf, meta, inbuf):
        # Keeps positioning and alpha metas intact across the transform.
        return True

    def do_transform_ip(self, buf):
        width = self.video_info.width
        height = self.video_info.height
        stride = self.video_info.stride[0]

        pts = buf.pts if buf.pts != Gst.CLOCK_TIME_NONE else 0
        stream_time = self.segment.to_stream_time(Gst.Format.TIME, pts) if self.segment else pts
        t = (stream_time if stream_time != Gst.CLOCK_TIME_NONE else pts) / Gst.SECOND

        res, mapinfo = buf.map(Gst.MapFlags.READ | Gst.MapFlags.WRITE)
        if not res:
            return Gst.FlowReturn.ERROR

        try:
            surface = cairo.ImageSurface.create_for_data(
                mapinfo.data, cairo.FORMAT_ARGB32, width, height, stride)
            cr = cairo.Context(surface)
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            render_particles(cr, self.effect, t, width, height,
                             self.amount, self.speed, self.size, self.opacity)
            surface.flush()
            del cr
            surface.finish()
            del surface
        finally:
            buf.unmap(mapinfo)

        return Gst.FlowReturn.OK


GObject.type_register(ParticlesFilter)


def register() -> bool:
    """Registers the element for this process, returns whether it worked."""
    if Gst.ElementFactory.find(ELEMENT_NAME):
        return True
    return Gst.Element.register(None, ELEMENT_NAME, Gst.Rank.NONE, ParticlesFilter)
