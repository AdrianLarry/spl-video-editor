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
"""Rotating and mirroring the image of a clip with a videoflip effect."""
from typing import NamedTuple
from typing import Optional

from gi.repository import GES

FLIP_BIN_DESCRIPTION = "videoflip"


class Orientation(NamedTuple):
    """How the image is turned.

    Attributes:
        rotation (int): The clockwise rotation, in degrees: 0, 90, 180 or 270.
        mirrored (bool): Whether the image is mirrored horizontally before
            being rotated.
    """

    rotation: int = 0
    mirrored: bool = False

    def rotated(self, degrees: int) -> "Orientation":
        """Returns the orientation rotated clockwise by degrees."""
        return Orientation((self.rotation + degrees) % 360, self.mirrored)

    def mirrored_horizontally(self) -> "Orientation":
        """Returns the orientation mirrored horizontally, as seen."""
        return Orientation(-self.rotation % 360, not self.mirrored)

    def mirrored_vertically(self) -> "Orientation":
        """Returns the orientation mirrored vertically, as seen."""
        return Orientation((180 - self.rotation) % 360, not self.mirrored)

    @property
    def swaps_dimensions(self) -> bool:
        """Whether the width and height of the image are swapped."""
        return self.rotation in (90, 270)


# The values of the GstVideoFlipMethod enum of the "method" property.
METHODS = {
    Orientation(0, False): 0,  # none
    Orientation(90, False): 1,  # clockwise
    Orientation(180, False): 2,  # rotate-180
    Orientation(270, False): 3,  # counterclockwise
    Orientation(0, True): 4,  # horizontal-flip
    Orientation(180, True): 5,  # vertical-flip
    Orientation(270, True): 6,  # upper-left-diagonal
    Orientation(90, True): 7,  # upper-right-diagonal
}
ORIENTATIONS = {method: orientation for orientation, method in METHODS.items()}


def get_flip_effect(clip: GES.Clip) -> Optional[GES.Effect]:
    """Returns the effect rotating and mirroring the clip, if any."""
    for effect in clip.get_top_effects():
        if effect.props.bin_description == FLIP_BIN_DESCRIPTION:
            return effect
    return None


def get_orientation(clip: GES.Clip) -> Orientation:
    """Returns how the image of the clip is turned."""
    effect = get_flip_effect(clip)
    if not effect or not effect.props.active:
        return Orientation()
    res, method = effect.get_child_property("method")
    assert res
    # The automatic method follows the orientation tag of the media,
    # which is applied anyway when playing.
    return ORIENTATIONS.get(int(method), Orientation())


def set_orientation(clip: GES.Clip, orientation: Orientation) -> None:
    """Turns the image of the clip, adding or removing the effect."""
    effect = get_flip_effect(clip)
    if orientation == Orientation():
        if effect:
            clip.remove(effect)
        return

    if not effect:
        effect = GES.Effect.new(FLIP_BIN_DESCRIPTION)
        clip.add(effect)
    effect.props.active = True
    effect.set_child_property("method", METHODS[orientation])
