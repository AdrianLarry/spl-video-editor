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
"""Tests for the pitivi.utils.kenburns module."""
from gi.repository import Gst
from gi.repository import GstController

from pitivi.utils.kenburns import ELEMENT_NAME
from pitivi.utils.kenburns import register
from tests import common


class ZoomFilterTest(common.TestCase):
    """Tests for the element zooming with sub-pixel precision."""

    def _render(self, **props):
        """Returns the alpha of the frame made from a white image of 40x30."""
        self.assertTrue(register())
        pipeline = Gst.parse_launch(
            "videotestsrc pattern=white num-buffers=1 ! video/x-raw,format=BGRA,width=40,height=30 ! "
            "%s name=zoom ! video/x-raw,width=100,height=50 ! appsink name=sink" % ELEMENT_NAME)
        zoom = pipeline.get_by_name("zoom")
        for name, value in props.items():
            zoom.set_property(name.replace("_", "-"), value)
        pipeline.set_state(Gst.State.PLAYING)
        try:
            sample = pipeline.get_by_name("sink").emit("pull-sample")
            structure = sample.get_caps().get_structure(0)
            self.assertEqual((structure.get_int("width")[1], structure.get_int("height")[1]), (100, 50))
            data = sample.get_buffer().extract_dup(0, 100 * 50 * 4)
        finally:
            pipeline.set_state(Gst.State.NULL)
        # BGRA: the alpha of each pixel, by rows.
        return [[data[(y * 100 + x) * 4 + 3] for x in range(100)] for y in range(50)]

    @staticmethod
    def _covered(alpha):
        """Returns the rectangle of the opaque pixels: left, top, right, bottom."""
        rows = [y for y in range(50) if any(value > 128 for value in alpha[y])]
        columns = [x for x in range(100) if any(alpha[y][x] > 128 for y in range(50))]
        return columns[0], rows[0], columns[-1] + 1, rows[-1] + 1

    def test_rectangle(self):
        # The image is placed in its rectangle of the frame, the rest is
        # transparent.
        alpha = self._render(rect_x=10.0, rect_y=5.0, rect_width=40.0, rect_height=30.0)
        self.assertEqual(self._covered(alpha), (10, 5, 50, 35))

    def test_zoom_around_the_anchor(self):
        # Twice as big around the top left corner of the frame.
        alpha = self._render(rect_x=10.0, rect_y=5.0, rect_width=40.0, rect_height=30.0,
                             zoom=2.0, anchor_x=0.0, anchor_y=0.0, max_zoom=2.0)
        self.assertEqual(self._covered(alpha), (20, 10, 100, 50))

    def test_offset(self):
        alpha = self._render(rect_x=10.0, rect_y=5.0, rect_width=40.0, rect_height=30.0,
                             offset_x=25.0, offset_y=-5.0)
        self.assertEqual(self._covered(alpha), (35, 0, 75, 30))

    def test_sub_pixel(self):
        # Half a pixel to the right: the edges are half covered.
        alpha = self._render(rect_x=10.5, rect_y=5.0, rect_width=40.0, rect_height=30.0)
        self.assertTrue(100 < alpha[20][10] < 155, alpha[20][10])
        self.assertTrue(100 < alpha[20][50] < 155, alpha[20][50])
        self.assertEqual(alpha[20][30], 255)

    def test_photo_changed(self):
        """Checks a still image is made smaller again when it changes."""
        self.assertTrue(register())
        pipeline = Gst.parse_launch(
            "appsrc name=src caps=video/x-raw,format=BGRA,width=4,height=4,framerate=10/1 format=time ! "
            "%s static=true ! video/x-raw,width=4,height=4 ! appsink name=sink" % ELEMENT_NAME)
        src = pipeline.get_by_name("src")
        sink = pipeline.get_by_name("sink")
        pipeline.set_state(Gst.State.PLAYING)
        try:
            colors = []
            for index, pixel in enumerate((b"\x00\x00\xff\xff", b"\x00\x00\xff\xff", b"\xff\x00\x00\xff")):
                buffer = Gst.Buffer.new_wrapped(pixel * 16)
                buffer.pts = index * Gst.SECOND // 10
                buffer.duration = Gst.SECOND // 10
                src.emit("push-buffer", buffer)
                sample = sink.emit("pull-sample")
                colors.append(sample.get_buffer().extract_dup(0, 4))
        finally:
            pipeline.set_state(Gst.State.NULL)
        # Red twice, kept, then blue, made again.
        self.assertEqual(colors, [b"\x00\x00\xff\xff", b"\x00\x00\xff\xff", b"\xff\x00\x00\xff"])

    def test_video_frames_and_subpixel_motion(self):
        """Every decoded frame changes while the rectangle moves smoothly."""
        self.assertTrue(register())
        pipeline = Gst.parse_launch(
            "appsrc name=src caps=video/x-raw,format=BGRA,width=40,height=30,framerate=30/1 format=time ! "
            "%s name=zoom static=false rect-x=10 rect-y=5 rect-width=40 rect-height=30 ! "
            "video/x-raw,width=100,height=50 ! appsink name=sink" % ELEMENT_NAME)
        zoom = pipeline.get_by_name("zoom")
        control = GstController.InterpolationControlSource()
        control.props.mode = GstController.InterpolationMode.LINEAR
        control.set(0, 1.0)
        control.set(10 * Gst.SECOND // 30, 1.02)
        binding = GstController.DirectControlBinding.new_absolute(zoom, "zoom", control)
        zoom.add_control_binding(binding)
        src = pipeline.get_by_name("src")
        sink = pipeline.get_by_name("sink")
        pipeline.set_state(Gst.State.PLAYING)
        edges = []
        colors = []
        try:
            for index in range(11):
                red = 20 + 20 * index
                buffer = Gst.Buffer.new_wrapped(bytes((0, 0, red, 255)) * 40 * 30)
                buffer.pts = index * Gst.SECOND // 30
                buffer.duration = Gst.SECOND // 30
                self.assertEqual(src.emit("push-buffer", buffer), Gst.FlowReturn.OK)
                sample = sink.emit("try-pull-sample", 5 * Gst.SECOND)
                self.assertIsNotNone(sample)
                data = sample.get_buffer().extract_dup(0, 100 * 50 * 4)
                colors.append(data[(20 * 100 + 25) * 4 + 2])
                edge = 30 - sum(data[(20 * 100 + x) * 4 + 3] / 255 for x in range(30))
                expected = 50 + (10 - 50) * (1 + 0.002 * index)
                self.assertAlmostEqual(edge, expected, delta=0.02)
                edges.append(edge)
        finally:
            pipeline.set_state(Gst.State.NULL)
        self.assertEqual(colors, [20 + 20 * index for index in range(11)])
        for before, after in zip(edges, edges[1:]):
            self.assertAlmostEqual(before - after, 0.08, delta=0.02)
