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
"""Tests for the pitivi.clip_properties.crop module."""
from unittest import mock

from gi.repository import GES
from gi.repository import Gst

from pitivi.clip_properties.crop import apply_crop
from pitivi.clip_properties.crop import Crop
from pitivi.clip_properties.crop import cropped_rect
from pitivi.clip_properties.crop import get_crop
from pitivi.clip_properties.crop import get_crop_effect
from pitivi.clip_properties.crop import set_crop
from pitivi.clip_properties.crop import turned_crop
from pitivi.clip_properties.crop import uncropped_rect
from pitivi.clip_properties.orientation import get_flip_effect
from pitivi.clip_properties.orientation import get_orientation
from pitivi.clip_properties.orientation import Orientation
from pitivi.clip_properties.orientation import set_orientation
from pitivi.utils.blurfill import get_blur_fill
from pitivi.utils.blurfill import get_fit_rect
from pitivi.utils.blurfill import get_image_size
from pitivi.utils.blurfill import set_blur_fill
from pitivi.utils.motion import get_base_position
from pitivi.utils.transitions import sync_pushes
from pitivi.viewer.crop_overlay import CropOverlay
from tests import common


class CropTest(common.TestCase):
    """Tests for cropping the image of a clip."""

    def test_rects(self):
        whole = {"posx": 100, "posy": 50, "width": 800, "height": 600}
        crop = Crop(left=40, right=0, top=0, bottom=30)
        kept = cropped_rect(whole, crop, (400, 300))
        self.assertEqual(kept, {"posx": 180, "posy": 50, "width": 720, "height": 540})
        self.assertEqual(uncropped_rect(kept, crop, (400, 300)), whole)

    def test_turned_crop(self):
        crop = Crop(left=1, right=2, top=3, bottom=4)
        # Rotated clockwise, the left side goes to the top.
        self.assertEqual(turned_crop(crop, Orientation(), Orientation(90)),
                         Crop(left=4, right=3, top=1, bottom=2))
        self.assertEqual(turned_crop(crop, Orientation(), Orientation(180)),
                         Crop(left=2, right=1, top=4, bottom=3))
        self.assertEqual(turned_crop(crop, Orientation(), Orientation(0, True)),
                         Crop(left=2, right=1, top=3, bottom=4))
        orientations = [Orientation(rotation, mirrored)
                        for rotation in (0, 90, 180, 270) for mirrored in (False, True)]
        for orientation in orientations:
            for new_orientation in orientations:
                turned = turned_crop(crop, orientation, new_orientation)
                self.assertEqual(turned_crop(turned, new_orientation, orientation), crop)

    def _add_image(self):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("flat_colour1_640x480.png"))
        return self.layer.add_asset(asset, 0, 0, 3 * Gst.SECOND, GES.TrackType.UNKNOWN)

    def _apply_crop(self, clip, crop):
        with self.action_log.started("crop", toplevel=True):
            apply_crop(clip, crop)

    @common.setup_timeline
    def test_crop_keeps_place(self):
        self._wait_until_project_loaded()
        clip = self._add_image()
        source = clip.find_track_element(None, GES.VideoSource)
        whole = {"posx": 240, "posy": 0, "width": 1440, "height": 1080}
        self.assertEqual(get_base_position(source), whole)

        # The image is shown 2.25 times bigger.
        self._apply_crop(clip, Crop(left=64, top=48))
        effect = get_crop_effect(clip)
        self.assertEqual(effect.get_child_property("left")[1], 64)
        self.assertEqual(effect.get_child_property("top")[1], 48)
        self.assertEqual(get_image_size(clip), (576, 432))
        self.assertEqual(get_image_size(clip, cropped=False), (640, 480))
        kept = {"posx": 384, "posy": 108, "width": 1296, "height": 972}
        self.assertEqual(get_base_position(source), kept)

        # Cropping more is relative to the whole image.
        self._apply_crop(clip, Crop(left=64, right=64, top=48))
        self.assertEqual(get_base_position(source),
                         {"posx": 384, "posy": 108, "width": 1152, "height": 972})

        self.action_log.undo()
        self.assertEqual(get_crop(clip), Crop(left=64, top=48))
        self.assertEqual(get_base_position(source), kept)
        self.action_log.undo()
        self.assertIsNone(get_crop_effect(clip))
        self.assertEqual(get_base_position(source), whole)
        self.action_log.redo()
        self.assertEqual(get_crop(clip), Crop(left=64, top=48))
        self.assertEqual(get_base_position(source), kept)

        # Removing the crop shows the whole image where it was.
        self._apply_crop(clip, Crop())
        self.assertIsNone(get_crop_effect(clip))
        self.assertEqual(get_base_position(source), whole)

    @common.setup_timeline
    def test_crop_with_fill(self):
        self._wait_until_project_loaded()
        clip = self._add_image()
        with self.action_log.started("blur fill", toplevel=True):
            set_blur_fill(clip, True)
            sync_pushes(self.layer)

        # The square kept is fitted again, over the fill.
        self._apply_crop(clip, Crop(left=80, right=80))
        self.assertEqual(get_image_size(clip), (480, 480))
        self.assertEqual(get_fit_rect(clip), (420, 0, 1080, 1080))
        self.assertIn("width=240,height=240", get_blur_fill(clip).props.bin_description)

        self.action_log.undo()
        self.assertEqual(get_fit_rect(clip), (240, 0, 1440, 1080))

    @common.setup_timeline
    def test_crop_after_turning(self):
        self._wait_until_project_loaded()
        clip = self._add_image()
        with self.action_log.started("turn", toplevel=True):
            set_orientation(clip, Orientation(90))
        self._apply_crop(clip, Crop(top=40))
        # The effects with a bigger index come first: turning, then cropping.
        self.assertGreater(clip.get_top_effect_index(get_flip_effect(clip)),
                           clip.get_top_effect_index(get_crop_effect(clip)))
        self.assertEqual(get_image_size(clip), (480, 600))


class CropOverlayTest(common.TestCase):
    """Tests for cropping in the viewer, with the undo history."""

    def _create_overlay(self):
        stack = mock.Mock(app=self.app)
        overlay = CropOverlay(stack)
        overlay.finished = mock.Mock()
        overlay.connect("finished", overlay.finished)
        return overlay

    def _add_image(self):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("flat_colour1_640x480.png"))
        return self.layer.add_asset(asset, 0, 0, 3 * Gst.SECOND, GES.TrackType.UNKNOWN)

    @common.setup_timeline
    def test_undo_after_cropping(self):
        self._wait_until_project_loaded()
        clip = self._add_image()
        with self.action_log.started("crop", toplevel=True):
            apply_crop(clip, Crop(left=64))
        effect = get_crop_effect(clip)
        with self.action_log.started("turn", toplevel=True):
            set_crop(clip, turned_crop(get_crop(clip), Orientation(), Orientation(90)))
            set_orientation(clip, Orientation(90))
        self.assertEqual(get_crop(clip), Crop(top=64))
        operations = len(self.action_log.undo_stacks)

        # Cancelling brings back the same effect, without changes to undo.
        overlay = self._create_overlay()
        overlay.start(clip)
        self.assertEqual(get_crop(clip), Crop())
        overlay.cancel()
        self.assertIs(get_crop_effect(clip), effect)
        self.assertEqual(len(self.action_log.undo_stacks), operations)
        self.assertFalse(self.action_log.redo_stacks)
        overlay.finished.assert_called_once()

        # The turn made before can be undone.
        self.action_log.undo()
        self.assertEqual(get_orientation(clip), Orientation())
        self.assertEqual(get_crop(clip), Crop(left=64))
        self.action_log.redo()

        # Applying is a single change.
        overlay.start(clip)
        overlay.crop = Crop(top=100)
        overlay.apply()
        self.assertEqual(get_crop(clip), Crop(top=100))
        self.assertEqual(len(self.action_log.undo_stacks), operations + 1)
        self.action_log.undo()
        self.assertEqual(get_crop(clip), Crop(top=64))
        self.assertIs(get_crop_effect(clip), effect)
        self.action_log.undo()
        self.assertEqual(get_crop(clip), Crop(left=64))

    @common.setup_timeline
    def test_undo_while_cropping(self):
        self._wait_until_project_loaded()
        clip = self._add_image()
        with self.action_log.started("crop", toplevel=True):
            apply_crop(clip, Crop(left=64))
        overlay = self._create_overlay()
        overlay.start(clip)
        overlay.crop = Crop(top=100)

        # Undoing stops cropping, the crop as it was.
        self.action_log.undo()
        self.assertFalse(overlay.active)
        self.assertEqual(get_crop(clip), Crop(left=64))
        self.assertFalse(self.action_log.redo_stacks)
        overlay.finished.assert_called_once()
        self.action_log.undo()
        self.assertEqual(get_crop(clip), Crop())
