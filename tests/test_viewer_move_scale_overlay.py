"""Regression checks for resizing a photo over its blurred background."""
from unittest import mock

import numpy
from gi.repository import GES

from pitivi.utils.blurfill import set_blur_fill
from pitivi.utils.motion import get_base_position
from pitivi.utils.transitions import sync_pushes
from pitivi.viewer.move_scale_overlay import Edge
from pitivi.viewer.move_scale_overlay import MoveScaleOverlay
from tests import common


class MoveScaleOverlayTest(common.TestCase):

    @common.setup_project_with_clips(assets_names=["flat_colour1_640x480.png"])
    def test_resize_photo_with_blurred_fill(self):
        clip, = self.layer.get_clips()
        source = clip.find_track_element(None, GES.VideoSource)
        with self.action_log.started("fill", toplevel=True):
            set_blur_fill(clip, True)
            sync_pushes(self.layer)
        stack = mock.Mock(app=self.app, window_size=numpy.array([960, 540]))
        stack.get_normalized_drag_distance.return_value = numpy.array([0.1, 0.0])
        overlay = MoveScaleOverlay(stack, self.action_log, source)
        stack.selected_overlay = overlay
        stack.hovered_overlay = overlay
        overlay.hovered_handle = overlay.handles[(Edge.right,)]
        original = get_base_position(source)
        overlay.on_button_press()
        overlay.on_motion_notify(numpy.array([900, 270]))
        overlay.on_button_release(numpy.array([900, 270]))
        resized = get_base_position(source)
        self.assertEqual(resized["width"], original["width"] + 192)
        self.assertEqual(resized["height"], original["height"])
        self.assertEqual(source.get_child_property("width")[1], 1920)
        self.action_log.undo()
        self.assertEqual(get_base_position(source), original)
        self.action_log.redo()
        self.assertEqual(get_base_position(source), resized)
