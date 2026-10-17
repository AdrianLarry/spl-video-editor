# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2013, Alex Băluț <alexandru.balut@gmail.com>
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
from unittest import mock

from gi.repository import GES
from gi.repository import Gst

from pitivi.utils.timeline import EditingContext
from pitivi.utils.timeline import SELECT
from pitivi.utils.timeline import SELECT_ADD
from pitivi.utils.timeline import Selected
from pitivi.utils.timeline import Selection
from pitivi.utils.timeline import UNSELECT
from tests import common


class TestSelected(common.TestCase):

    def test_bool_evaluation(self):
        selected = Selected()
        self.assertFalse(selected)

        selected.selected = True
        self.assertTrue(selected)

        selected.selected = False
        self.assertFalse(selected)


class TestSelection(common.TestCase):

    def test_bool_evaluation(self):
        clip1 = mock.MagicMock()
        selection = Selection()
        self.assertFalse(selection)
        selection.set_selection([clip1], SELECT)
        self.assertTrue(selection)
        selection.set_selection([clip1], SELECT_ADD)
        self.assertTrue(selection)
        selection.set_selection([clip1], UNSELECT)
        self.assertFalse(selection)

    def test_get_single_clip(self):
        selection = Selection()
        clip1 = common.create_test_clip(GES.UriClip)
        clip2 = common.create_test_clip(GES.TitleClip)

        # Selection empty.
        self.assertIsNone(selection.get_single_clip())
        self.assertIsNone(selection.get_single_clip(GES.UriClip))
        self.assertIsNone(selection.get_single_clip(GES.TitleClip))

        selection.set_selection([clip1], SELECT)
        self.assertEqual(selection.get_single_clip(), clip1)
        self.assertEqual(selection.get_single_clip(GES.UriClip), clip1)
        self.assertIsNone(selection.get_single_clip(GES.TitleClip))

        selection.set_selection([clip2], SELECT)
        self.assertEqual(selection.get_single_clip(), clip2)
        self.assertIsNone(selection.get_single_clip(GES.UriClip))
        self.assertEqual(selection.get_single_clip(GES.TitleClip), clip2)

        selection.set_selection([clip1, clip2], SELECT)
        self.assertIsNone(selection.get_single_clip())
        self.assertIsNone(selection.get_single_clip(GES.UriClip))
        self.assertIsNone(selection.get_single_clip(GES.TitleClip))

    def test_can_group_ungroup(self):
        timeline_container = common.create_timeline_container()
        timeline = timeline_container.timeline
        clip1, clip2 = self.add_clips_simple(timeline, 2)

        selection = Selection()
        self.assertFalse(selection.can_group)
        self.assertFalse(selection.can_ungroup)

        selection.set_selection([clip1], SELECT)
        self.assertFalse(selection.can_group)
        self.assertTrue(selection.can_ungroup)

        selection.set_selection([clip2], SELECT_ADD)
        self.assertTrue(selection.can_group)
        self.assertFalse(selection.can_ungroup)

        selection.set_selection([], SELECT)
        self.assertFalse(selection.can_group)
        self.assertFalse(selection.can_ungroup)

    def test_toplevels(self):
        timeline_container = common.create_timeline_container()
        timeline = timeline_container.timeline
        clip1, clip2, clip3, clip4 = self.add_clips_simple(timeline, 4)

        selection = Selection()

        selection.set_selection([clip1, clip2, clip3, clip4], SELECT)
        self.assertSetEqual(selection.toplevels(), {clip1, clip2, clip3, clip4})

        group1 = GES.Container.group([clip1, clip2])
        group1.props.serialize = True
        self.assertSetEqual(selection.toplevels(), {group1, clip3, clip4})

        group2 = GES.Container.group([group1, clip3])
        group2.props.serialize = True
        self.assertSetEqual(selection.toplevels(), {group2, clip4})

        group1.props.serialize = True
        group1.props.serialize = False
        self.assertSetEqual(selection.toplevels(), {group2, clip4})

        group1.props.serialize = False
        group2.props.serialize = False
        self.assertSetEqual(selection.toplevels(), {clip1, clip2, clip3, clip4})

        group1.props.serialize = True
        group2.props.serialize = False
        self.assertSetEqual(selection.toplevels(), {group1, clip3, clip4})


class TestEditingContext(common.TestCase):
    """Tests for the EditingContext class."""

    def test_with_video(self):
        """Checks the value of the with_video field."""
        audio_clip = GES.UriClipAsset.request_sync(common.get_sample_uri("mp3_sample.mp3")).extract()
        video_clip = GES.UriClipAsset.request_sync(common.get_sample_uri("one_fps_numeroted_blue.mkv")).extract()
        audio_video_clip = GES.UriClipAsset.request_sync(common.get_sample_uri("tears_of_steel.webm")).extract()

        # Add the clips to a layer so they have TrackElements.
        project = common.create_project()
        layer = project.ges_timeline.append_layer()
        self.assertTrue(layer.add_clip(audio_clip))
        self.assertTrue(layer.add_clip(video_clip))
        audio_video_clip.props.start = video_clip.props.duration
        self.assertTrue(layer.add_clip(audio_video_clip))

        self.__check_with_video(audio_clip, False)
        self.__check_with_video(video_clip, True)
        self.__check_with_video(audio_video_clip, True)

        # Check the track elements of a clip with audio only.
        audio_track_element = audio_clip.find_track_element(None, GES.AudioSource)
        self.__check_with_video(audio_track_element, False)

        # Check the track elements of a clip with video only.
        video_track_element = video_clip.find_track_element(None, GES.VideoSource)
        self.__check_with_video(video_track_element, True)

        # Check the track elements of a clip with both audio and video.
        audio_track_element = audio_video_clip.find_track_element(None, GES.AudioSource)
        video_track_element = audio_video_clip.find_track_element(None, GES.VideoSource)
        self.__check_with_video(audio_track_element, True)
        self.__check_with_video(video_track_element, True)

    def __check_with_video(self, clip, expected):
        context = EditingContext(clip, None, None, None, None, None)
        if expected:
            self.assertTrue(context.with_video)
        else:
            self.assertFalse(context.with_video)


class TestTrimmingRules(common.TestCase):
    """Tests for the clips of a layer never overlapping when trimming."""

    def _add_clip(self, layer, start, duration):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("one_fps_numeroted_blue.mkv"))
        clip = layer.add_asset(asset, start * Gst.SECOND, 0, duration * Gst.SECOND,
                               GES.TrackType.UNKNOWN)
        self.assertIsNotNone(clip)
        return clip

    def _trim(self, clip, edge, *positions):
        with self.action_log.started("trim"):
            context = EditingContext(clip, self.timeline, GES.EditMode.EDIT_TRIM, edge, self.app)
            for position in positions:
                context.edit_to(position * Gst.SECOND, clip.get_layer())
            context.finish()

    @staticmethod
    def _get_ranges(*clips):
        return [(clip.props.start / Gst.SECOND, clip.props.duration / Gst.SECOND)
                for clip in clips]

    @common.setup_timeline
    def test_extending_the_end_pushes_the_following_clips(self):
        clip1 = self._add_clip(self.layer, 0, 2)
        clip2 = self._add_clip(self.layer, 2, 2)
        clip3 = self._add_clip(self.layer, 6, 2)
        # A clip in another layer is not moved.
        other_layer = self.timeline.append_layer()
        other_clip = self._add_clip(other_layer, 3, 2)

        # The positions while dragging go back and forth.
        self._trim(clip1, GES.Edge.EDGE_END, 4, 5, 3)
        self.assertEqual(self._get_ranges(clip1, clip2, clip3, other_clip),
                         [(0, 3), (3, 2), (7, 2), (3, 2)])

        # Shortening leaves a gap.
        self._trim(clip1, GES.Edge.EDGE_END, 1)
        self.assertEqual(self._get_ranges(clip1, clip2, clip3),
                         [(0, 1), (3, 2), (7, 2)])

        self.action_log.undo()
        self.action_log.undo()
        self.assertEqual(self._get_ranges(clip1, clip2, clip3, other_clip),
                         [(0, 2), (2, 2), (6, 2), (3, 2)])

        self.action_log.redo()
        self.assertEqual(self._get_ranges(clip1, clip2, clip3),
                         [(0, 3), (3, 2), (7, 2)])

    @common.setup_timeline
    def test_extending_the_end_fills_the_gap_first(self):
        clip1 = self._add_clip(self.layer, 0, 2)
        clip2 = self._add_clip(self.layer, 4, 2)
        clip3 = self._add_clip(self.layer, 7, 2)

        # The next clip is pushed only once reached.
        self._trim(clip1, GES.Edge.EDGE_END, 3)
        self.assertEqual(self._get_ranges(clip1, clip2, clip3), [(0, 3), (4, 2), (7, 2)])

        self._trim(clip1, GES.Edge.EDGE_END, 5, 4)
        self.assertEqual(self._get_ranges(clip1, clip2, clip3), [(0, 4), (4, 2), (7, 2)])

        self._trim(clip1, GES.Edge.EDGE_END, 6)
        self.assertEqual(self._get_ranges(clip1, clip2, clip3), [(0, 6), (6, 2), (9, 2)])

    @common.setup_timeline
    def test_extending_the_start_stops_at_the_previous_clip(self):
        clip1 = self._add_clip(self.layer, 0, 2)
        clip2 = self._add_clip(self.layer, 4, 2)
        clip2.set_inpoint(4 * Gst.SECOND)

        self._trim(clip2, GES.Edge.EDGE_START, 1)
        self.assertEqual(self._get_ranges(clip1, clip2), [(0, 2), (2, 4)])


class TestMovingRules(common.TestCase):
    """Tests for the clips of a layer never overlapping when moving clips."""

    def _add_clip(self, start, duration=2, layer=None):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("one_fps_numeroted_blue.mkv"))
        clip = (layer or self.layer).add_asset(asset, start * Gst.SECOND, 0, duration * Gst.SECOND,
                                               GES.TrackType.UNKNOWN)
        self.assertIsNotNone(clip)
        return clip

    def _move(self, clip, *positions, log_actions=True):
        context = EditingContext(clip, self.timeline, GES.EditMode.EDIT_NORMAL,
                                 GES.Edge.EDGE_NONE, self.app, log_actions)
        for position in positions:
            context.edit_to(position * Gst.SECOND, self.layer)
        context.finish()

    @staticmethod
    def _get_starts(*clips):
        return [clip.props.start / Gst.SECOND for clip in clips]

    @common.setup_timeline
    def test_moving_onto_clips_inserts_and_pushes(self):
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(2)
        clip_c = self._add_clip(4)
        clip_d = self._add_clip(8)
        other_layer = self.timeline.append_layer()
        other_clip = self._add_clip(4, layer=other_layer)

        # Dropped on the second half of B, A goes after B. The positions while
        # dragging go back and forth, only the last one counts.
        self._move(clip_a, 5, 9, 3.5)
        self.assertEqual(self._get_starts(clip_a, clip_b, clip_c, clip_d, other_clip),
                         [4, 2, 6, 10, 4])

        self.action_log.undo()
        self.assertEqual(self._get_starts(clip_a, clip_b, clip_c, clip_d), [0, 2, 4, 8])

        # Dropped on the first half of C, B goes before C. The following
        # clips are pushed together, keeping the gaps between them.
        self._move(clip_b, 4.5)
        self.assertEqual(self._get_starts(clip_a, clip_b, clip_c, clip_d), [0, 4, 6, 10])

    @common.setup_timeline
    def test_no_room_made_when_creating_a_layer(self):
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)

        context = EditingContext(clip_b, self.timeline, GES.EditMode.EDIT_NORMAL,
                                 GES.Edge.EDGE_NONE, self.app, True)
        # Passing over the clips of the layer pushes them.
        context.edit_to(0, self.layer)
        self.assertEqual(self._get_starts(clip_b, clip_a), [0, 2])
        # Dropping would create a new layer, the clips are put back.
        context.set_making_room(False)
        self.assertEqual(clip_a.props.start, 0)
        new_layer = self.timeline.append_layer()
        context.edit_to(0, new_layer)
        context.finish()
        self.assertEqual(self._get_starts(clip_b, clip_a), [0, 0])
        self.assertEqual(clip_b.get_layer(), new_layer)

    @common.setup_timeline
    def test_moving_into_a_gap_which_fits(self):
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(2)
        clip_c = self._add_clip(8)

        self._move(clip_a, 5)
        self.assertEqual(self._get_starts(clip_a, clip_b, clip_c), [5, 2, 8])

    @common.setup_timeline
    def test_dropping_a_new_clip_pushes_undoably(self):
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(2)
        # The clips being dropped are added first, by an operation of their own.
        with self.action_log.started("Add clips"):
            new_clip = self._add_clip(20)

        self._move(new_clip, 0.5, log_actions=False)
        self.assertEqual(self._get_starts(new_clip, clip_a, clip_b), [0, 2, 4])

        self.action_log.undo()
        self.assertNotIn(new_clip, self.layer.get_clips())
        self.assertEqual(self._get_starts(clip_a, clip_b), [0, 2])
