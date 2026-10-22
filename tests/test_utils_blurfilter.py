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
"""Tests for the pitivi.utils.blurfilter module."""
from gi.repository import Gst

from pitivi.utils.blurfilter import ELEMENT_NAME
from pitivi.utils.blurfilter import register
from tests import common


class BlurFilterTest(common.TestCase):
    """Tests for the element blurring the clips of the blur transitions."""

    def _render(self, sigma):
        """Returns the rows of a frame of 64x64, black with a white square."""
        self.assertTrue(register())
        pipeline = Gst.parse_launch(
            "appsrc name=src caps=video/x-raw,format=BGRA,width=64,height=64,framerate=10/1 format=time ! "
            "%s name=blur ! appsink name=sink" % ELEMENT_NAME)
        pipeline.get_by_name("blur").props.sigma = sigma
        pixels = bytearray(b"\x00\x00\x00\xff" * 64 * 64)
        for y in range(24, 40):
            for x in range(24, 40):
                pixels[(y * 64 + x) * 4:(y * 64 + x) * 4 + 3] = b"\xff\xff\xff"
        buffer = Gst.Buffer.new_wrapped(bytes(pixels))
        buffer.pts = 0
        buffer.duration = Gst.SECOND // 10
        pipeline.set_state(Gst.State.PLAYING)
        try:
            pipeline.get_by_name("src").emit("push-buffer", buffer)
            sample = pipeline.get_by_name("sink").emit("pull-sample")
            data = sample.get_buffer().extract_dup(0, 64 * 64 * 4)
        finally:
            pipeline.set_state(Gst.State.NULL)
        return data, bytes(pixels)

    def test_untouched_without_blur(self):
        data, original = self._render(0.0)
        self.assertEqual(data, original)

    def test_blur(self):
        # A radius of 6 pixels of this small frame, see REFERENCE_SIZE.
        data, unused_original = self._render(60.0)
        center = data[(32 * 64 + 32) * 4]
        edge = data[(32 * 64 + 24) * 4]
        outside = data[(32 * 64 + 20) * 4]
        # The square is spread: its edge is grayer, the black next to it too.
        self.assertGreater(center, edge)
        self.assertGreater(edge, 0)
        self.assertGreater(outside, 0)
        self.assertLess(center, 255)
