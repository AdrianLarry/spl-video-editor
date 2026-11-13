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
"""Tests for the pitivi.utils.lightproxy module."""
import os
import tempfile
from unittest import mock

from gi.repository import GES
from gi.repository import Gst
from gi.repository import GstTranscoder

from pitivi.utils import lightproxy
from pitivi.utils.effectmigration import replace_effects
from tests import common


class LightProxyTest(common.TestCase):
    """Tests for the light copies of the videos."""

    def test_switch(self):
        with mock.patch.dict(os.environ, {"SPL_COPIAS_LIVIANAS": "0"}):
            self.assertFalse(lightproxy.enabled())
            self.assertIsNone(lightproxy.encoding_profile(960, 540))

    def test_every_frame_stands_alone(self):
        with mock.patch.dict(os.environ, {"SPL_COPIAS_LIVIANAS": "1"}):
            if not lightproxy.enabled():
                self.skipTest("x264enc or qtmux missing")
            profile = lightproxy.encoding_profile(320, 180)
        with tempfile.TemporaryDirectory() as folder:
            dest = os.path.join(folder, "copia.mov")
            transcoder = GstTranscoder.Transcoder.new_full(
                common.get_sample_uri("30fps_numeroted_frames_red.mkv"), Gst.filename_to_uri(dest), profile)
            self.assertTrue(transcoder.run())
            asset = GES.UriClipAsset.request_sync(Gst.filename_to_uri(dest))
            stream = asset.get_info().get_video_streams()[0]
            self.assertEqual((stream.get_width(), stream.get_height()), (320, 180))


class EffectMigrationTest(common.TestCase):
    """Tests for replacing the effects of older projects."""

    def test_replace_in_place(self):
        timeline = common.create_timeline_container().timeline.ges_timeline
        clip = GES.TestClip.new()
        clip.props.duration = Gst.SECOND
        layers = timeline.get_layers()
        (layers[0] if layers else timeline.append_layer()).add_clip(clip)
        first = GES.Effect.new("gaussianblur sigma=4")
        second = GES.Effect.new("videobalance saturation=0")
        clip.add_top_effect(first, 0)
        clip.add_top_effect(second, 1)
        first.props.active = False

        self.assertEqual(replace_effects(timeline, {"gaussianblur sigma=4": "agingtv"}), 1)
        effects = clip.get_top_effects()
        self.assertEqual([effect.props.bin_description for effect in effects],
                         ["agingtv", "videobalance saturation=0"])
        self.assertFalse(effects[0].props.active)
