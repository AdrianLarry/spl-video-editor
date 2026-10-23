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
"""The split of the frames in two, for the blurred fill.

GES copies the properties of the elements of an effect when splitting,
copying or pasting a clip, also to and from copies of its own, and the
"alloc-pad" of a tee crashes when set to none. This element sends the
frames to its two pads as a tee, without properties.
"""
from gi.repository import GObject
from gi.repository import Gst

ELEMENT_NAME = "splsplit"


class SplitTee(Gst.Element):
    """Sends the buffers and the events to its two source pads."""

    __gstmetadata__ = ("SPL split", "Generic",
                       "Sends the stream to two pads, without properties", "SPL")

    __gsttemplates__ = (
        Gst.PadTemplate.new("sink", Gst.PadDirection.SINK, Gst.PadPresence.ALWAYS, Gst.Caps.new_any()),
        Gst.PadTemplate.new("src_0", Gst.PadDirection.SRC, Gst.PadPresence.ALWAYS, Gst.Caps.new_any()),
        Gst.PadTemplate.new("src_1", Gst.PadDirection.SRC, Gst.PadPresence.ALWAYS, Gst.Caps.new_any()))

    def __init__(self):
        Gst.Element.__init__(self)
        self.sinkpad = Gst.Pad.new_from_template(self.get_pad_template("sink"), "sink")
        self.sinkpad.set_chain_function_full(self.__chain)
        self.sinkpad.set_event_function_full(self.__sink_event)
        self.sinkpad.set_query_function_full(self.__sink_query)
        self.add_pad(self.sinkpad)
        self.srcpads_ = []
        for name in ("src_0", "src_1"):
            pad = Gst.Pad.new_from_template(self.get_pad_template(name), name)
            pad.set_query_function_full(self.__src_query)
            self.add_pad(pad)
            self.srcpads_.append(pad)

    def __sink_event(self, pad, parent, event):
        if event.type == Gst.EventType.CAPS:
            # Not forwarded by the default handler, the pad not proxying the
            # caps, flag not settable from Python.
            results = [srcpad.push_event(event) for srcpad in self.srcpads_]
            return all(results)
        # The others go to both pads.
        return pad.event_default(parent, event)

    def __sink_query(self, pad, parent, query):
        if query.type == Gst.QueryType.CAPS:
            # The caps both branches accept.
            caps = query.parse_caps()
            result = caps if caps else Gst.Caps.new_any()
            for srcpad in self.srcpads_:
                peer_caps = srcpad.peer_query_caps(caps)
                result = result.intersect(peer_caps)
            query.set_caps_result(result)
            return True
        if query.type == Gst.QueryType.ALLOCATION:
            # Each branch allocates its own buffers.
            return False
        return pad.query_default(parent, query)

    def __src_query(self, pad, parent, query):
        if query.type == Gst.QueryType.CAPS:
            # The caps asked downstream are the ones of upstream.
            query.set_caps_result(self.sinkpad.peer_query_caps(query.parse_caps()))
            return True
        return pad.query_default(parent, query)

    def __chain(self, pad, parent, buffer):
        results = [srcpad.push(buffer) for srcpad in self.srcpads_]
        for result in results:
            if result not in (Gst.FlowReturn.OK, Gst.FlowReturn.NOT_LINKED):
                return result
        if all(result == Gst.FlowReturn.NOT_LINKED for result in results):
            return Gst.FlowReturn.NOT_LINKED
        return Gst.FlowReturn.OK


GObject.type_register(SplitTee)


def register() -> bool:
    """Registers the element for this process, returns whether it worked."""
    if Gst.ElementFactory.find(ELEMENT_NAME):
        return True
    return Gst.Element.register(None, ELEMENT_NAME, Gst.Rank.NONE, SplitTee)
