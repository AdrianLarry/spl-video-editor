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
"""Undoing the changes of the order of the effects of the clips.

GES moves an effect in steps, the priorities of the effects colliding
in between, and moves all the effects of a clip when the clips before it
in the layer change. Setting again the priorities of those steps, in the
reverse order, can leave two effects with the same priority, which the
composition cannot play. So the order of the effects of each clip is
kept as it was before and after each operation, and restored as a whole.
"""
from typing import Dict
from typing import List
from typing import Set

from gi.repository import GES

from pitivi.undo.base import UndoableAction
from pitivi.utils.loggable import Loggable


def get_effects_order(clip: GES.Clip) -> List[GES.BaseEffect]:
    """Returns the effects of the clip, the first applied last."""
    return list(clip.get_top_effects())


def set_effects_order(clip: GES.Clip, order: List[GES.BaseEffect]) -> None:
    """Orders the effects of the clip which are in the list as listed.

    The effects not listed, added after, are applied before them.
    """
    effects = clip.get_top_effects()
    for index, effect in enumerate(effect for effect in order if effect in effects):
        if clip.get_top_effect_index(effect) != index:
            clip.set_top_effect_index(effect, index)


class EffectsOrderChanged(UndoableAction):
    """The order of the effects of a clip changed."""

    def __init__(self, clip, old_order, new_order):
        UndoableAction.__init__(self)
        self.clip = clip
        self.old_order = old_order
        self.new_order = new_order

    def __repr__(self):
        return "<EffectsOrderChanged %s: %s -> %s>" % (self.clip, self.old_order, self.new_order)

    def do(self):
        set_effects_order(self.clip, self.new_order)

    def undo(self):
        set_effects_order(self.clip, self.old_order)


class EffectsOrderObserver(Loggable):
    """Reports the changes of the order of the effects of the clips.

    One change by clip and operation, when the operation ends.
    """

    def __init__(self, action_log):
        Loggable.__init__(self)
        self.action_log = action_log
        # The order of the effects of each clip, as it was before the
        # current operation.
        self.__orders: Dict[GES.Clip, List[GES.BaseEffect]] = {}
        self.__changed: Set[GES.Clip] = set()
        # The effects added to each clip by the current operation, in order.
        self.__added: Dict[GES.Clip, List[GES.BaseEffect]] = {}
        action_log.connect("pre-commit", self.__pre_commit_cb)
        action_log.connect("rollback", self.__rollback_cb)

    def add_clip(self, clip: GES.Clip) -> None:
        self.__orders[clip] = get_effects_order(clip)

    def remove_clip(self, clip: GES.Clip) -> None:
        self.__orders.pop(clip, None)
        self.__changed.discard(clip)
        self.__added.pop(clip, None)

    def add_effect(self, effect: GES.BaseEffect) -> None:
        effect.connect("notify::priority", self.__effect_priority_cb)
        clip = effect.get_parent()
        if clip in self.__orders and self.__recording():
            self.__added.setdefault(clip, []).append(effect)
        self.__effect_priority_cb(effect, None)

    def remove_effect(self, effect: GES.BaseEffect) -> None:
        effect.disconnect_by_func(self.__effect_priority_cb)

    def __effect_priority_cb(self, effect, unused_pspec):
        clip = effect.get_parent()
        if clip not in self.__orders:
            return
        if self.__recording():
            self.__changed.add(clip)
        elif clip not in self.__changed:
            # Undoing, redoing or a change not undoable.
            self.__orders[clip] = get_effects_order(clip)

    def __recording(self):
        return self.action_log.is_in_transaction() and not self.action_log.running

    def __pre_commit_cb(self, unused_action_log, unused_stack):
        for clip in self.__changed:
            old_order = self.__orders[clip]
            new_order = get_effects_order(clip)
            # Adding an effect puts it last, removing it is undone where
            # it was: the order is undone by those changes alone.
            added = [effect for effect in self.__added.get(clip, []) if effect in new_order]
            expected = [effect for effect in old_order if effect in new_order and effect not in added] + added
            if new_order != expected:
                self.action_log.push(EffectsOrderChanged(clip, old_order, new_order))
            self.__orders[clip] = new_order
        self.__changed.clear()
        self.__added.clear()

    def __rollback_cb(self, unused_action_log, unused_stack):
        if len(self.action_log.stacks) > 1:
            # The operation containing it goes on.
            return
        # Undone after this, the orders are as they were before it.
        self.__changed.clear()
        self.__added.clear()
