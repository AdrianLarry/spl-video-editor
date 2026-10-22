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
"""Tests for the pitivi.utils.blurfill module."""
from gi.repository import GES
from gi.repository import Gst

from pitivi.utils.blurfill import ALPHA_PROPERTY
from pitivi.utils.blurfill import blur_fill_description
from pitivi.utils.blurfill import get_active_blur_fill
from pitivi.utils.blurfill import get_blur_fill
from pitivi.utils.blurfill import get_blur_sigma
from pitivi.utils.blurfill import set_blur_fill
from pitivi.utils.blurfill import is_fill_needed
from pitivi.utils.blurfill import set_blur_sigma
from pitivi.utils.blurfill import update_blur_fill
from pitivi.utils.fades import get_keyframes
from pitivi.utils.formats import set_format
from pitivi.utils.formats import VERTICAL
from pitivi.utils.motion import get_base_position
from pitivi.utils.transitions import get_contacts
from pitivi.utils.transitions import PUSH
from pitivi.utils.transitions import RIGHT
from pitivi.utils.transitions import set_image_fades
from pitivi.utils.transitions import set_transition
from pitivi.utils.transitions import sync_pushes
from tests import common

SECOND = Gst.SECOND


class BlurFillTest(common.TestCase):
    """Tests for the blurred fill of the clips."""

    def test_description(self):
        # A square image in a vertical frame: it fits the width.
        description = blur_fill_description((800, 800), (1080, 1920))
        self.assertIn("width=1080,height=1080 ! spl-mix.sink_1", description)
        self.assertIn("sink_1::xpos=0 sink_1::ypos=420", description)
        # The background covers a small frame, cropped to it.
        self.assertIn("width=480,height=480 ! videocrop left=105 right=105 top=0 bottom=0", description)
        self.assertTrue(description.endswith("format=AYUV,width=1080,height=1920"))
        self.assertIsNotNone(GES.Effect.new(description))

        # Custom sigma in description
        custom_desc = blur_fill_description((800, 800), (1080, 1920), sigma=15.0)
        self.assertIn("gaussianblur sigma=15", custom_desc)

    def test_fill_needed(self):
        self.assertTrue(is_fill_needed((1080, 1920), (1920, 1080)))
        self.assertFalse(is_fill_needed((1080, 1920), (1080, 1920)))
        # A photo of a phone, 3:4, leaves bands in a vertical frame.
        self.assertTrue(is_fill_needed((3000, 4000), (1080, 1920)))
        # The rounding leaves a pixel at most.
        self.assertFalse(is_fill_needed((1079, 1920), (1080, 1920)))

    @common.setup_timeline
    def test_unneeded_fill_is_inactive(self):
        self._wait_until_project_loaded()
        clip_a = self._add_image(0)
        self._add_image(3)
        self._set_blur_fill(clip_a, True)
        with self.action_log.started("push", toplevel=True):
            set_transition(get_contacts(self.layer)[0], PUSH, SECOND, RIGHT)
        self.assertTrue(get_active_blur_fill(clip_a))

        # In a 4:3 frame the image covers it, the fill is kept inactive.
        source = clip_a.find_track_element(None, GES.VideoSource)
        with self.action_log.started("frame", toplevel=True):
            source.get_track().update_restriction_caps(
                Gst.Caps.from_string("video/x-raw,width=1440,height=1080"))
            update_blur_fill(clip_a)
            sync_pushes(self.layer)
        effect = get_blur_fill(clip_a)
        self.assertFalse(effect.props.active)
        self.assertIsNone(get_active_blur_fill(clip_a))
        # The source itself moves for the push.
        values = {value for unused, value in
                  get_keyframes(source.get_control_binding("posx").props.control_source)}
        self.assertGreater(len(values), 1)

        self.action_log.undo()
        self.assertTrue(get_active_blur_fill(clip_a))

    def _add_image(self, start):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("flat_colour1_640x480.png"))
        return self.layer.add_asset(asset, start * SECOND, 0, 3 * SECOND, GES.TrackType.UNKNOWN)

    def _set_blur_fill(self, clip, enabled):
        with self.action_log.started("blur fill", toplevel=True):
            set_blur_fill(clip, enabled)
            sync_pushes(self.layer)

    @common.setup_timeline
    def test_blur_fill(self):
        self._wait_until_project_loaded()
        clip = self._add_image(0)
        source = clip.find_track_element(None, GES.VideoSource)
        self._set_blur_fill(clip, True)
        effect = get_blur_fill(clip)
        self.assertIsNotNone(effect)
        # The source covers the frame, the effect makes it.
        self.assertEqual(get_base_position(source), {"posx": 0, "posy": 0, "width": 1920, "height": 1080})

        # Custom blur sigma
        set_blur_sigma(source, 12.0)
        self.assertEqual(get_blur_sigma(source), 12.0)
        self.assertEqual(get_blur_sigma(clip), 12.0)
        res, sigma_val = effect.get_child_property("sigma")
        self.assertTrue(res)
        self.assertEqual(sigma_val, 12.0)

        # Another format makes the blurred fill again, preserving sigma.
        set_format(self.app, self.project, VERTICAL)
        effect = get_blur_fill(clip)
        self.assertIn("format=AYUV,width=1080,height=1920", effect.props.bin_description)
        self.assertIn("sigma=12", effect.props.bin_description)
        self.assertEqual(get_base_position(source)["height"], 1920)
        self.action_log.undo()
        self.assertIn("format=AYUV,width=1920,height=1080", get_blur_fill(clip).props.bin_description)

        self._set_blur_fill(clip, False)
        self.assertIsNone(get_blur_fill(clip))
        self.action_log.undo()
        self.assertIsNotNone(get_blur_fill(clip))

    @common.setup_timeline
    def test_push_and_fades(self):
        self._wait_until_project_loaded()
        clip_a = self._add_image(0)
        clip_b = self._add_image(3)
        for clip in (clip_a, clip_b):
            self._set_blur_fill(clip, True)

        with self.action_log.started("fade", toplevel=True):
            set_image_fades(clip_a, fade_in=SECOND)
        source_a = clip_a.find_track_element(None, GES.VideoSource)
        effect_a = get_blur_fill(clip_a)
        # The effect shares the alpha of the source.
        self.assertIs(effect_a.get_control_binding(ALPHA_PROPERTY).props.control_source,
                      source_a.get_control_binding("alpha").props.control_source)

        contact, = get_contacts(self.layer)
        with self.action_log.started("transition", toplevel=True):
            set_transition(contact, PUSH, SECOND, RIGHT)

        def keyframes(effect, name):
            binding = effect.get_control_binding(name)
            return [(timestamp / SECOND, round(value))
                    for timestamp, value in get_keyframes(binding.props.control_source)]

        # The frame of the first clip goes out to the left: cropped on the
        # left, a border on the right.
        self.assertEqual(keyframes(effect_a, "GstVideoBox::left"), [(0, 0), (2, 0), (3, 1920)])
        self.assertEqual(keyframes(effect_a, "GstVideoBox::right"), [(0, 0), (2, 0), (3, -1920)])
        effect_b = get_blur_fill(clip_b)
        self.assertEqual(keyframes(effect_b, "GstVideoBox::left"), [(0, -1920), (1, 0), (3, 0)])
        # The sources do not move, the effects cover them.
        self.assertIsNone(source_a.get_control_binding("posx"))

        self.action_log.undo()
        self.assertIsNone(effect_a.get_control_binding("GstVideoBox::left"))
