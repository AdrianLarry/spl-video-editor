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
"""Light copies of the videos, for a fluid preview.

The videos of the phones are big and every frame needs the ones before:
at each edge of a clip NLE seeks the sources again and the decoder goes
through up to a second of frames. The preview uses instead a copy of each
video at most 960 pixels wide or high, where every frame stands alone. They
are the scaled proxies of Pitivi, made automatically for every video and
encoded with H.264: the JPEG ones are about four times bigger. The export
uses the original videos.
"""
import os

from gi.repository import Gst
from gi.repository import GstPbutils

# The copies fit in a square of this side, horizontal or vertical.
BOX = 960
# The share of the processor for making them, 100 for no limit: with a
# limit the jobs started after others ended never went on. Pitivi uses 10.
CPU_USAGE = 100
# kbit/s, enough for the viewer.
BITRATE = 3000


def enabled() -> bool:
    """Whether the copies are made. SPL_COPIAS_LIVIANAS=0 turns them off."""
    if os.environ.get("SPL_COPIAS_LIVIANAS", "1") == "0":
        return False
    return all(Gst.ElementFactory.find(name) for name in ("x264enc", "qtmux"))


def encoding_profile(width: int, height: int):
    """Returns the profile of a copy of the given size, or None."""
    if not enabled():
        return None
    container = GstPbutils.EncodingContainerProfile.new(
        "spl-light-copy", None, Gst.Caps.from_string("video/quicktime,variant=apple"), None)
    video = GstPbutils.EncodingVideoProfile.new(
        Gst.Caps.from_string("video/x-h264"), None,
        Gst.Caps.from_string("video/x-raw,width=%d,height=%d" % (width, height)), 0)
    # Not the encoder of the graphics card: its frames depend on the others.
    video.set_preset_name("x264enc")
    video.set_element_properties(Gst.Structure.from_string(
        "element-properties-map, map={ [x264enc, key-int-max=(uint)1, speed-preset=(int)1,"
        " bitrate=(uint)%d] }" % BITRATE)[0])
    container.add_profile(video)
    container.add_profile(GstPbutils.EncodingAudioProfile.new(Gst.Caps.from_string("audio/x-raw"), None, None, 0))
    return container
