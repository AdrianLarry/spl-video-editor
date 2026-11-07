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
"""Tests for the pitivi.utils.layeractive module."""
from gi.repository import GES
from gi.repository import Gst

from pitivi.utils.layeractive import watch_timeline
from tests import common


def video_states(clip):
    """Returns (element active, NLE object active) of the video elements."""
    return [(element.props.active, element.get_nleobject().props.active)
            for element in clip.get_children(True)
            if element.get_track_type() == GES.TrackType.VIDEO]


class LayerActiveTest(common.TestCase):
    """Tests for the effects of the hidden tracks."""

    def setUp(self):
        super().setUp()
        self.timeline = GES.Timeline.new_audio_video()
        self.layer = self.timeline.append_layer()
        self.video_tracks = [track for track in self.timeline.get_tracks()
                             if track.props.track_type == GES.TrackType.VIDEO]
        asset = GES.Asset.request(GES.TestClip, None)
        self.clip = self.layer.add_asset(asset, 0, 0, Gst.SECOND, GES.TrackType.UNKNOWN)

    def test_effect_added_to_hidden_track(self):
        self.layer.set_active_for_tracks(False, self.video_tracks)
        watch_timeline(self.timeline)

        effect = GES.Effect.new("videobalance")
        self.clip.add(effect)
        # GES alone leaves the NLE object of the effect active.
        self.assertEqual(video_states(self.clip), [(True, False), (True, False)])

        # The effect is not shown while its track is hidden.
        effect.props.active = False
        effect.props.active = True
        self.assertEqual(video_states(self.clip), [(True, False), (True, False)])

        # Shown again with its track.
        self.layer.set_active_for_tracks(True, self.video_tracks)
        self.assertEqual(video_states(self.clip), [(True, True), (True, True)])

    def test_effect_of_loaded_project(self):
        # As loading a project: the effect is there before watching.
        self.layer.set_active_for_tracks(False, self.video_tracks)
        self.clip.add(GES.Effect.new("videobalance"))
        self.assertEqual(video_states(self.clip), [(True, True), (True, False)])

        watch_timeline(self.timeline)
        self.assertEqual(video_states(self.clip), [(True, False), (True, False)])

    def test_active_layer_untouched(self):
        watch_timeline(self.timeline)
        effect = GES.Effect.new("videobalance")
        self.clip.add(effect)
        self.assertEqual(video_states(self.clip), [(True, True), (True, True)])

        effect.props.active = False
        self.assertEqual(video_states(self.clip), [(False, False), (True, True)])
