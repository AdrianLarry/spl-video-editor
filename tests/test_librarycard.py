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
"""Tests for the pitivi.librarycard module."""
from gi.repository import GES
from gi.repository import Gst

from pitivi.librarycard import AUDIO
from pitivi.librarycard import format_duration
from pitivi.librarycard import get_kind
from pitivi.librarycard import get_waveform
from pitivi.librarycard import IMAGE
from pitivi.librarycard import VIDEO
from tests import common


class LibraryCardTest(common.TestCase):
    """Tests for the cards of the files."""

    def test_kind(self):
        for sample, kind in (("flat_colour1_640x480.png", IMAGE),
                             ("mp3_sample.mp3", AUDIO),
                             ("one_fps_numeroted_blue.mkv", VIDEO)):
            asset = GES.UriClipAsset.request_sync(common.get_sample_uri(sample))
            self.assertEqual(get_kind(asset), kind, sample)

    def test_format_duration(self):
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(14 * Gst.SECOND + 400 * Gst.MSECOND), "0:14")
        self.assertEqual(format_duration(75 * Gst.SECOND), "1:15")
        self.assertEqual(format_duration(52 * 60 * Gst.SECOND), "52:00")

    def test_waveform(self):
        waveform = get_waveform("file:///música.mp3", 40)
        self.assertEqual(len(waveform), 40)
        self.assertTrue(all(0 < height <= 1 for height in waveform))
        # The same file always has the same waveform, others another one.
        self.assertEqual(get_waveform("file:///música.mp3", 40), waveform)
        self.assertNotEqual(get_waveform("file:///otra.mp3", 40), waveform)
