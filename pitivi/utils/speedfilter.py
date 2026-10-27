# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Video speed with absolute media timestamps across GES segment boundaries.

videorate 1.24 anchors its frame selection to each new segment, which causes
freezes or skips when a transition splits a time effect into segments. Map
absolute timestamps first, then let a rate-1 videorate handle frame cadence.
"""
from gi.repository import GES
from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstBase

ELEMENT_NAME = "splspeed"
CAPS = Gst.Caps.from_string("video/x-raw(ANY)")


class SpeedFilter(GstBase.BaseTransform):
    """Changes timestamps without changing pixels or composition metadata."""

    __gtype_name__ = "SPLSpeedFilter"

    __gstmetadata__ = ("SPL video speed", "Filter/Effect/Video",
                       "Maps absolute media timestamps", "SPL")
    __gsttemplates__ = tuple(
        Gst.PadTemplate.new(name, direction, Gst.PadPresence.ALWAYS, CAPS)
        for name, direction in (("sink", Gst.PadDirection.SINK),
                                ("src", Gst.PadDirection.SRC)))
    __gproperties__ = {
        "rate": (float, "Rate", "Playback speed", 0.01, 100.0, 1.0,
                 GObject.ParamFlags.READWRITE),
    }

    def __init__(self):
        super().__init__()
        self.rate = 1.0
        self._segment_base = 0
        self.set_in_place(True)

    def do_get_property(self, unused_pspec):
        return self.rate

    def do_set_property(self, unused_pspec, value):
        self.rate = value
        self.reconfigure_src()

    def _scale(self, timestamp, factor):
        if timestamp == Gst.CLOCK_TIME_NONE or timestamp < 0:
            return timestamp
        return round(timestamp * factor)

    def do_transform_ip(self, buffer):
        buffer.pts = self._scale(buffer.pts, 1 / self.rate)
        buffer.dts = self._scale(buffer.dts, 1 / self.rate)
        buffer.duration = self._scale(buffer.duration, 1 / self.rate)
        return Gst.FlowReturn.OK

    def do_sink_event(self, event):
        if event.type == Gst.EventType.SEGMENT:
            segment = event.parse_segment().copy()
            if segment.format == Gst.Format.TIME:
                self._segment_base = segment.base
                for prop in ("start", "stop", "time", "position", "duration"):
                    setattr(segment, prop, self._scale(getattr(segment, prop), 1 / self.rate))
                replacement = Gst.Event.new_segment(segment)
                replacement.set_seqnum(event.get_seqnum())
                event = replacement
        return GstBase.BaseTransform.do_sink_event(self, event)

    def do_src_event(self, event):
        if event.type == Gst.EventType.QOS:
            kind, proportion, diff, timestamp = event.parse_qos()
            timestamp = max(0, round((timestamp - self._segment_base) * self.rate) + self._segment_base)
            diff = max(-timestamp, round(diff * self.rate))
            replacement = Gst.Event.new_qos(kind, proportion, diff, timestamp)
            replacement.set_seqnum(event.get_seqnum())
            event = replacement
        if event.type == Gst.EventType.SEEK:
            rate, fmt, flags, start_type, start, stop_type, stop = event.parse_seek()
            if fmt == Gst.Format.TIME:
                replacement = Gst.Event.new_seek(
                    rate, fmt, flags, start_type, self._scale(start, self.rate),
                    stop_type, self._scale(stop, self.rate))
                replacement.set_seqnum(event.get_seqnum())
                event = replacement
        return GstBase.BaseTransform.do_src_event(self, event)


GObject.type_register(SpeedFilter)


def register():
    """Registers the element and its GES time translation property."""
    if Gst.ElementFactory.find(ELEMENT_NAME):
        return True
    if not Gst.Element.register(None, ELEMENT_NAME, Gst.Rank.NONE, SpeedFilter):
        return False
    return GES.Effect.register_rate_property(ELEMENT_NAME, "rate")
