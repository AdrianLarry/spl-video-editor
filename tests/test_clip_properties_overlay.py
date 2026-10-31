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
"""Tests for the overlays, the shapes drawn over the video."""
from unittest import mock

import numpy
from gi.repository import GES

from pitivi.clip_properties.overlay import get_shape_effect
from pitivi.clip_properties.overlay import get_shape_name
from pitivi.clip_properties.overlay import get_values
from pitivi.clip_properties.overlay import is_overlay_clip
from pitivi.clip_properties.overlay import set_values
from pitivi.undo.timeline import CommitTimelineFinalizingAction
from pitivi.utils.formats import set_format
from pitivi.utils.formats import VERTICAL
from pitivi.utils.shapefilter import render_shape
from pitivi.utils.shapefilter import shape_box
from pitivi.utils.shapes import SHAPES
from tests import common


class ShapesTest(common.TestCase):
    """Tests for drawing the shapes."""

    def test_render(self):
        for name in SHAPES:
            values = {"shape": name, "x1": 0.2, "y1": 0.2, "x2": 0.8, "y2": 0.8,
                      "color": 0xFFFF0000, "line-width": 60.0, "corner-radius": 30.0}
            pixels = render_shape(values, 200, 100, 800).reshape(100, 200, 4)
            # Transparent out of the shape, opaque red on its line.
            self.assertEqual(pixels[2, 2].tolist(), [0, 0, 0, 0], name)
            opaque = pixels[pixels[:, :, 3] == 255]
            self.assertTrue(len(opaque), name)
            self.assertTrue((opaque == [0, 0, 255, 255]).all(), name)
            # The edges, half transparent, keep the color.
            edges = pixels[(pixels[:, :, 3] > 0) & (pixels[:, :, 3] < 255)]
            self.assertTrue((numpy.abs(edges[:, 2].astype(int) - 255) <= 2).all(), name)

            # Only the part of the frame with the shape, drawn the same.
            x, y, width, height = shape_box(values, (200, 100))
            self.assertLess(width * height, 200 * 100, name)
            part = render_shape(values, width, height, width * 4, (200, 100), (x, y))
            self.assertEqual(part.reshape(height, width, 4).tolist(),
                             pixels[y:y + height, x:x + width].tolist(), name)
            # Nothing is drawn out of it.
            outside = pixels.copy()
            outside[y:y + height, x:x + width] = 0
            self.assertFalse(outside.any(), name)


class OverlayPropertiesTest(common.TestCase):
    """Tests for adding and changing the overlays."""

    @common.setup_timeline
    @common.setup_clipproperties
    def test_create(self):
        self.project.pipeline.get_position = mock.Mock(return_value=0)
        self.clipproperties.create_overlay_clip("arrow")
        clips = self.layer.get_clips()
        self.assertEqual(len(clips), 1)
        clip = clips[0]
        self.assertTrue(is_overlay_clip(clip))
        self.assertEqual(get_shape_name(clip), "arrow")
        self.assertEqual(get_shape_effect(clip).get_child_property("shape")[1], "arrow")
        source = clip.find_track_element(None, GES.VideoTestSource)
        self.assertEqual(source.get_child_property("foreground-color")[1], 0)
        # Selected, its shape is shown in the properties.
        self.assertTrue(self.clipproperties.overlay_expander.props.visible)
        self.assertFalse(self.transformation_box.props.visible)

        self.action_log.undo()
        self.assertListEqual(self.layer.get_clips(), [])
        self.action_log.redo()
        self.assertTrue(is_overlay_clip(self.layer.get_clips()[0]))

    @common.setup_timeline
    @common.setup_clipproperties
    def test_change_style(self):
        self.project.pipeline.get_position = mock.Mock(return_value=0)
        self.clipproperties.create_overlay_clip("frame")
        clip = self.layer.get_clips()[0]
        box = self.clipproperties.overlay_expander

        box.color_buttons[0xFFFFD166].set_active(True)
        self.assertEqual(get_values(clip)["color"], 0xFFFFD166)
        box.line_width_scale.set_value(20)
        box.line_width_scale.set_value(25)
        self.assertEqual(get_values(clip)["line-width"], 25)
        self.assertTrue(box.corner_scale.props.visible)

        # Another shape keeps the place and the style.
        geometry = {prop: get_values(clip)[prop] for prop in ("x1", "y1", "x2", "y2")}
        box.shape_buttons["circle"].set_active(True)
        self.assertEqual(get_shape_name(clip), "circle")
        self.assertEqual(get_shape_effect(clip).get_child_property("shape")[1], "circle")
        self.assertEqual({prop: get_values(clip)[prop] for prop in geometry}, geometry)
        self.assertFalse(box.corner_scale.props.visible)

        self.action_log.undo()
        self.assertEqual(get_shape_name(clip), "frame")
        # The line width changes are a single change.
        self.action_log.undo()
        self.assertEqual(get_values(clip)["line-width"], 10)
        self.action_log.undo()
        self.assertEqual(get_values(clip)["color"], 0xFFD9531E)

    @common.setup_timeline
    @common.setup_clipproperties
    def test_placed_where_drawn(self):
        self.project.pipeline.get_position = mock.Mock(return_value=0)
        self.clipproperties.create_overlay_clip("arrow")
        clip = self.layer.get_clips()[0]
        source = clip.find_track_element(None, GES.VideoTestSource)

        def check_place(frame_size):
            box = [source.get_child_property(prop)[1] for prop in ("posx", "posy", "width", "height")]
            self.assertEqual(box, list(shape_box(get_values(clip), frame_size)))
            effect = get_shape_effect(clip)
            self.assertEqual((effect.get_child_property("frame-width")[1],
                              effect.get_child_property("frame-height")[1]), frame_size)
        check_place((1920, 1080))
        old_posx = source.get_child_property("posx")[1]

        with self.action_log.started("overlay change", toplevel=True,
                                     finalizing_action=CommitTimelineFinalizingAction(self.project.pipeline)):
            set_values(clip, {"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.3})
        check_place((1920, 1080))
        self.assertNotEqual(source.get_child_property("posx")[1], old_posx)
        self.action_log.undo()
        check_place((1920, 1080))
        self.assertEqual(source.get_child_property("posx")[1], old_posx)

        # The shape stays in the same place of the frame, so its box changes.
        set_format(self.app, self.project, VERTICAL)
        check_place((1080, 1920))
        self.action_log.undo()
        check_place((1920, 1080))
