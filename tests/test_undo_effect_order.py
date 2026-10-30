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
"""Tests for the pitivi.undo.effect_order module."""
from gi.repository import GES
from gi.repository import Gst

from pitivi.undo.effect_order import EffectsOrderChanged
from tests import common


class EffectsOrderTest(common.TestCase):
    """Tests for undoing the order of the effects."""

    def _add_clip(self, start, descriptions):
        clip = GES.TestClip()
        clip.props.start = start
        clip.props.duration = 4 * Gst.SECOND
        self.layer.add_clip(clip)
        effects = [GES.Effect.new(description) for description in descriptions]
        for effect in effects:
            clip.add(effect)
        return clip, effects

    def assert_order(self, clip, effects):
        self.assertEqual(clip.get_top_effects(), effects)
        priorities = [child.props.priority for child in clip.get_children(False)
                      if child.get_track() and child.get_track().props.track_type == GES.TrackType.VIDEO]
        self.assertEqual(len(priorities), len(set(priorities)), priorities)

    @common.setup_timeline
    def test_reordered_in_steps(self):
        clip0, effects0 = self._add_clip(0, ["videobalance", "videoflip"])
        clip1, (first, second, third) = self._add_clip(int(3.4 * Gst.SECOND),
                                                       ["videobalance", "videoscale", "agingtv"])

        # As when syncing the clips of the layer: the effects of the
        # neighbor move and move back, in steps.
        with self.action_log.started("change", toplevel=True):
            clip0.remove(effects0[1])
            clip1.set_top_effect_index(third, 0)
            clip1.set_top_effect_index(second, 0)
            clip1.set_top_effect_index(first, 0)
            clip1.set_top_effect_index(second, 0)
        self.assert_order(clip1, [second, first, third])
        actions = self.action_log.undo_stacks[-1].done_actions
        self.assertEqual(len([action for action in actions if isinstance(action, EffectsOrderChanged)]), 1)

        self.action_log.undo()
        self.assert_order(clip0, effects0)
        self.assert_order(clip1, [first, second, third])
        self.action_log.redo()
        self.assert_order(clip0, effects0[:1])
        self.assert_order(clip1, [second, first, third])
        self.action_log.undo()
        self.assert_order(clip1, [first, second, third])

    @common.setup_timeline
    def test_moved_back(self):
        clip, (first, second) = self._add_clip(0, ["videobalance", "agingtv"])
        with self.action_log.started("move", toplevel=True):
            clip.set_top_effect_index(second, 0)
            clip.set_top_effect_index(first, 0)
        # Nothing changed, nothing to undo.
        self.assertFalse(self.action_log.undo_stacks)
        self.assert_order(clip, [first, second])

    @common.setup_timeline
    def test_removed_from_moved_clip(self):
        clip, (first, second, third) = self._add_clip(0, ["videobalance", "videoscale", "agingtv"])
        with self.action_log.started("remove", toplevel=True):
            clip.remove(second)
        # The clip moves in the layer, its priorities with it.
        clip.props.priority = clip.props.priority + 5
        self.action_log.undo()
        self.assert_order(clip, [first, second, third])
