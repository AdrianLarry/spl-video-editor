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
"""Effects of older projects made again as the current ones, when loading."""
from typing import Dict

from gi.repository import GES


def replace_effects(timeline: GES.Timeline, replaced: Dict[str, str]) -> int:
    """Replaces the effects by bin description, in the same place.

    Returns:
        How many were replaced.
    """
    count = 0
    for layer in timeline.get_layers():
        for clip in layer.get_clips():
            for effect in clip.get_top_effects():
                new = replaced.get(effect.props.bin_description)
                if not new:
                    continue
                index = clip.get_top_effect_index(effect)
                active = effect.props.active
                replacement = GES.Effect.new(new)
                clip.remove_top_effect(effect)
                clip.add_top_effect(replacement, index)
                replacement.props.active = active
                count += 1
    return count
