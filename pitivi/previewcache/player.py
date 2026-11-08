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
"""Plays the prepared pieces in the viewer, one after the other."""
from typing import Callable
from typing import List
from typing import Optional

from gi.repository import Gst

from pitivi.utils.loggable import Loggable


class PreparedPlayer(Loggable):
    """Plays files of consecutive pieces as one stream.

    splitmuxsrc plays them without gaps, the time starting at zero at the
    start of the first one.

    Attributes:
        widget: The widget showing the frames, made once.
    """

    def __init__(self, on_eos: Callable[[], None], on_error: Callable[[], None]):
        Loggable.__init__(self)
        self.on_eos = on_eos
        self.on_error = on_error
        self.pipeline = None
        self.files = []
        self.offset = 0
        self.sink = Gst.ElementFactory.make("gtksink", "spl-prepared-sink")
        self.sink.props.sync = True
        self.widget = self.sink.props.widget
        # The frames are made as big as shown before the sink, which draws
        # them in the main thread, as the viewer of the timeline does.
        self.size = None
        self.size_caps = None
        self.widget.connect("size-allocate", self.__size_allocate_cb)

    def start(self, files: List[str], offset: int, position: int) -> bool:
        """Plays the files, the first starting at offset, from the position."""
        self.stop()
        self.files = files
        self.offset = offset
        pipeline = Gst.parse_launch(
            "splitmuxsrc name=source "
            "source.video_0 ! queue ! decodebin ! videoconvert ! videoscale ! capsfilter name=size "
            "source.audio_0 ! queue ! decodebin ! audioconvert ! audioresample ! autoaudiosink")
        pipeline.get_by_name("source").connect("format-location", lambda unused: self.files)
        self.size = pipeline.get_by_name("size")
        if self.size_caps:
            self.size.props.caps = self.size_caps
        pipeline.add(self.sink)
        self.size.link(self.sink)
        self.pipeline = pipeline
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.__bus_message_cb)

        pipeline.set_state(Gst.State.PAUSED)
        res, state, unused_pending = pipeline.get_state(5 * Gst.SECOND)
        if res == Gst.StateChangeReturn.FAILURE or state != Gst.State.PAUSED:
            self.warning("The prepared pieces do not play")
            self.stop()
            return False
        if position > offset:
            pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                                 position - offset)
            pipeline.get_state(5 * Gst.SECOND)
        pipeline.set_state(Gst.State.PLAYING)
        return True

    def set_frame_size(self, width: int, height: int):
        """Sets the size of the frames of the pieces."""
        self.frame_size = (width, height)
        self.__size_allocate_cb(self.widget, self.widget.get_allocation())

    def __size_allocate_cb(self, widget, allocation):
        frame = getattr(self, "frame_size", None)
        if not frame or allocation.width < 2 or allocation.height < 2:
            return
        scale = widget.get_scale_factor()
        fit = min(allocation.width * scale / frame[0], allocation.height * scale / frame[1], 1)
        width = max(2, round(frame[0] * fit / 2) * 2)
        height = max(2, round(frame[1] * fit / 2) * 2)
        caps = Gst.Caps.from_string("video/x-raw,width=%d,height=%d,pixel-aspect-ratio=1/1" % (width, height))
        if self.size_caps and self.size_caps.is_equal(caps):
            return
        self.size_caps = caps
        if self.size:
            self.size.props.caps = caps

    def __bus_message_cb(self, unused_bus, message):
        if message.type == Gst.MessageType.EOS:
            self.on_eos()
        elif message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            self.warning("Error playing the prepared pieces: %s %s", error, debug)
            self.on_error()

    def get_position(self) -> Optional[int]:
        """Returns the position in the timeline, or None."""
        if not self.pipeline:
            return None
        res, position = self.pipeline.query_position(Gst.Format.TIME)
        if not res:
            return None
        return self.offset + position

    def stop(self):
        if not self.pipeline:
            return
        pipeline = self.pipeline
        self.pipeline = None
        pipeline.get_bus().remove_signal_watch()
        pipeline.set_state(Gst.State.NULL)
        # The sink is used again by the next pipeline.
        pipeline.remove(self.sink)
        self.size = None
