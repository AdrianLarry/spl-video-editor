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
"""Tests for the pitivi.utils.fades module."""
from gi.repository import GES
from gi.repository import Gst
from gi.repository import GstController

from pitivi.utils.fades import Fades
from pitivi.utils.fades import fades_keyframes
from pitivi.utils.fades import get_keyframes
from pitivi.utils.fades import read_fades
from pitivi.utils.timeline import EditingContext
from tests import common

SECOND = Gst.SECOND


class FadesTest(common.TestCase):
    """Tests for converting fades to and from keyframes."""

    def test_round_trip(self):
        for fades in (Fades(1.0, 0, 0),
                      Fades(0.5, 2 * SECOND, 0),
                      Fades(0.2, 0, 3 * SECOND),
                      Fades(1.0, SECOND, SECOND),
                      Fades(0.0, 0, 0)):
            keyframes = fades_keyframes(fades, 10 * SECOND, 20 * SECOND)
            self.assertEqual(read_fades(keyframes), fades)

    def test_fades_shortened(self):
        keyframes = fades_keyframes(Fades(1.0, 3 * SECOND, 3 * SECOND), 0, 4 * SECOND)
        self.assertEqual(keyframes, [(0, 0.0), (3 * SECOND, 1.0), (4 * SECOND, 0.0)])

    def test_free_keyframes(self):
        self.assertIsNone(read_fades([(0, 0.0), (SECOND, 1.0), (2 * SECOND, 0.5), (3 * SECOND, 0.0)]))
        self.assertIsNone(read_fades([(0, 1.0)]))


class FadesAnchorTest(common.TestCase):
    """Tests for keeping the fades at the ends of the trimmed sources."""

    def _add_clip(self, start, inpoint, duration):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("one_fps_numeroted_blue.mkv"))
        clip = self.layer.add_asset(asset, start, inpoint, duration, GES.TrackType.UNKNOWN)
        self.assertIsNotNone(clip)
        return clip

    def _set_fades(self, source, property_name, keyframes):
        binding = source.get_control_binding(property_name)
        if binding:
            control_source = binding.props.control_source
        else:
            control_source = GstController.InterpolationControlSource()
            control_source.props.mode = GstController.InterpolationMode.LINEAR
            source.set_control_source(control_source, property_name, "direct")
        for timestamp, value in keyframes:
            control_source.set(timestamp, value)
        return control_source

    def _trim(self, clip, edge, position):
        with self.action_log.started("trim"):
            context = EditingContext(clip, self.timeline, GES.EditMode.EDIT_TRIM, edge, self.app)
            context.edit_to(position, self.layer)
            context.finish()

    @common.setup_timeline
    def test_trim_keeps_fades(self):
        # The clip shows the media from 2s to 8s.
        clip = self._add_clip(0, 2 * SECOND, 6 * SECOND)
        source = self.get_clip_element(clip)
        original = [(2 * SECOND, 0.0), (3 * SECOND, 1.0), (6 * SECOND, 1.0), (8 * SECOND, 0.0)]
        control_source = self._set_fades(source, "alpha", original)

        # Trimming the start moves the fade-in.
        self._trim(clip, GES.Edge.EDGE_START, 2 * SECOND)
        self.assertEqual((clip.props.in_point, clip.props.duration), (4 * SECOND, 4 * SECOND))
        self.assertEqual(get_keyframes(control_source),
                         [(4 * SECOND, 0.0), (5 * SECOND, 1.0), (6 * SECOND, 1.0), (8 * SECOND, 0.0)])

        # Extending the end moves the fade-out.
        self._trim(clip, GES.Edge.EDGE_END, 7 * SECOND)
        self.assertEqual(get_keyframes(control_source),
                         [(4 * SECOND, 0.0), (5 * SECOND, 1.0), (7 * SECOND, 1.0), (9 * SECOND, 0.0)])

        # Extending the start beyond the original start.
        self._trim(clip, GES.Edge.EDGE_START, 0)
        self.assertEqual(clip.props.in_point, 2 * SECOND)
        self.assertEqual(get_keyframes(control_source),
                         [(2 * SECOND, 0.0), (3 * SECOND, 1.0), (7 * SECOND, 1.0), (9 * SECOND, 0.0)])

        # Shortening the clip shortens the fades which do not fit.
        self._trim(clip, GES.Edge.EDGE_END, 2 * SECOND)
        self.assertEqual(get_keyframes(control_source),
                         [(2 * SECOND, 0.0), (3 * SECOND, 1.0), (4 * SECOND, 0.0)])

        # Each trim is undone in a single step, with its fades.
        for unused in range(4):
            self.action_log.undo()
        self.assertEqual(clip.props.in_point, 2 * SECOND)
        self.assertEqual(clip.props.duration, 6 * SECOND)
        self.assertEqual(get_keyframes(control_source), original)

        self.action_log.redo()
        self.assertEqual(get_keyframes(control_source),
                         [(4 * SECOND, 0.0), (5 * SECOND, 1.0), (6 * SECOND, 1.0), (8 * SECOND, 0.0)])

    @common.setup_timeline
    def test_trim_keeps_sound_fades(self):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("mp3_sample.mp3"))
        clip = self.layer.add_asset(asset, 0, 0, 6 * SECOND, GES.TrackType.AUDIO)
        source = self.get_clip_element(clip, GES.AudioSource)
        control_source = self._set_fades(source, "volume", [
            (0, 0.0), (SECOND, 0.05), (4 * SECOND, 0.05), (6 * SECOND, 0.0)])

        self._trim(clip, GES.Edge.EDGE_END, 4 * SECOND)
        self.assertEqual(get_keyframes(control_source),
                         [(0, 0.0), (SECOND, 0.05), (2 * SECOND, 0.05), (4 * SECOND, 0.0)])

    @common.setup_timeline
    def test_trim_keeps_free_keyframes(self):
        clip = self._add_clip(0, 0, 6 * SECOND)
        source = self.get_clip_element(clip)
        control_source = self._set_fades(source, "alpha", [
            (0, 0.0), (SECOND, 1.0), (3 * SECOND, 0.5), (6 * SECOND, 0.0)])

        self._trim(clip, GES.Edge.EDGE_END, 4 * SECOND)
        # GES shortens the curve, the fade-out is not recreated.
        keyframes = get_keyframes(control_source)
        self.assertEqual(keyframes[:3], [(0, 0.0), (SECOND, 1.0), (3 * SECOND, 0.5)])
        self.assertEqual(keyframes[-1][0], 4 * SECOND)
        self.assertGreater(keyframes[-1][1], 0.0)

    @common.setup_timeline
    def test_undo_trim_of_clip_using_all_the_media(self):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("tears_of_steel.webm"))
        clip = self.layer.add_asset(asset, 0, 0, 2 * SECOND, GES.TrackType.UNKNOWN)
        source = self.get_clip_element(clip)
        original = [(0, 0.0), (SECOND // 2, 1.0), (3 * SECOND // 2, 1.0), (2 * SECOND, 0.0)]
        control_source = self._set_fades(source, "alpha", original)

        self._trim(clip, GES.Edge.EDGE_START, SECOND // 2)
        trimmed = [(SECOND // 2, 0.0), (SECOND, 1.0), (3 * SECOND // 2, 1.0), (2 * SECOND, 0.0)]
        self.assertEqual(get_keyframes(control_source), trimmed)

        # GES adjusts the keyframes differently while undoing and redoing.
        for unused in range(2):
            self.action_log.undo()
            self.assertEqual((clip.props.in_point, clip.props.duration), (0, 2 * SECOND))
            self.assertEqual(get_keyframes(control_source), original)

            self.action_log.redo()
            self.assertEqual((clip.props.in_point, clip.props.duration), (SECOND // 2, 3 * SECOND // 2))
            self.assertEqual(get_keyframes(control_source), trimmed)
