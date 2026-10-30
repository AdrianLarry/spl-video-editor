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
"""Cropping the sides of the image of a clip with a videocrop effect.

The crop is in pixels of the image as turned, the effect comes right
after the one turning it. The rest of the image keeps its place, or it
is fitted again when the clip has the blurred fill.
"""
from typing import Dict
from typing import NamedTuple
from typing import Optional
from typing import Tuple

from gi.repository import GES

from pitivi.clip_properties.orientation import get_flip_effect
from pitivi.clip_properties.orientation import Orientation

CROP_BIN_DESCRIPTION = "videocrop name=spl-crop"
# The smallest part of the image kept, in pixels.
MIN_SIZE = 16


class Crop(NamedTuple):
    """The pixels cropped on each side of the image."""

    left: int = 0
    right: int = 0
    top: int = 0
    bottom: int = 0

    def is_empty(self) -> bool:
        return not any(self)

    def kept_size(self, width: int, height: int) -> Tuple[int, int]:
        """Returns the size of the image kept, for an image this big."""
        return width - self.left - self.right, height - self.top - self.bottom


def _rotated_clockwise(crop: Crop) -> Crop:
    return Crop(left=crop.bottom, right=crop.top, top=crop.left, bottom=crop.right)


def _rotated_counterclockwise(crop: Crop) -> Crop:
    return Crop(left=crop.top, right=crop.bottom, top=crop.right, bottom=crop.left)


def _mirrored(crop: Crop) -> Crop:
    return Crop(left=crop.right, right=crop.left, top=crop.top, bottom=crop.bottom)


def turned_crop(crop: Crop, orientation: Orientation, new_orientation: Orientation) -> Crop:
    """Returns the crop for the image turned again, cropping the same part.

    The image is mirrored first, then rotated clockwise.
    """
    for unused_turn in range(orientation.rotation // 90):
        crop = _rotated_counterclockwise(crop)
    if orientation.mirrored != new_orientation.mirrored:
        crop = _mirrored(crop)
    for unused_turn in range(new_orientation.rotation // 90):
        crop = _rotated_clockwise(crop)
    return crop


def get_crop_effect(clip: GES.Clip) -> Optional[GES.Effect]:
    """Returns the effect cropping the clip, if any."""
    for effect in clip.get_top_effects():
        if effect.props.bin_description == CROP_BIN_DESCRIPTION:
            return effect
    return None


def get_crop(clip: Optional[GES.Clip]) -> Crop:
    """Returns how the image of the clip is cropped."""
    effect = get_crop_effect(clip) if clip else None
    if not effect or not effect.props.active:
        return Crop()
    return Crop(*(effect.get_child_property(side)[1] for side in Crop._fields))


def cropped_size(clip: Optional[GES.Clip], width: int, height: int) -> Tuple[int, int]:
    """Returns the size of the image of the clip kept by the crop.

    Args:
        width (int): The width of the image as turned.
        height (int): The height of the image as turned.
    """
    kept_width, kept_height = get_crop(clip).kept_size(width, height)
    if kept_width < MIN_SIZE or kept_height < MIN_SIZE:
        # Cropped for another size of the image.
        return width, height
    return kept_width, kept_height


def set_crop(clip: GES.Clip, crop: Crop) -> None:
    """Crops the image of the clip, adding or removing the effect.

    It does not place the image, see `apply_crop`.
    """
    effect = get_crop_effect(clip)
    if crop.is_empty():
        if effect:
            clip.remove(effect)
        return

    if not effect:
        effect = GES.Effect.new(CROP_BIN_DESCRIPTION)
        clip.add(effect)
        # Right after turning the image, before the fill or the zoom
        # making the frame. The effects with a bigger index come first.
        flip = get_flip_effect(clip)
        if flip:
            clip.set_top_effect_index(effect, clip.get_top_effect_index(flip))
        else:
            clip.set_top_effect_index(effect, len(clip.get_top_effects()) - 1)
    effect.props.active = True
    for side, value in crop._asdict().items():
        if effect.get_child_property(side)[1] != value:
            effect.set_child_property(side, value)


def uncropped_rect(rect: Dict[str, float], crop: Crop,
                   image_size: Tuple[int, int]) -> Dict[str, float]:
    """Returns where the whole image would be, the kept part being at rect.

    Args:
        rect (dict): The posx, posy, width and height of the kept part.
        crop (Crop): How the image is cropped.
        image_size (tuple): The width and height of the image as turned.
    """
    width, height = image_size
    kept_width, kept_height = crop.kept_size(width, height)
    scale_x, scale_y = rect["width"] / kept_width, rect["height"] / kept_height
    return {"posx": rect["posx"] - crop.left * scale_x,
            "posy": rect["posy"] - crop.top * scale_y,
            "width": width * scale_x,
            "height": height * scale_y}


def cropped_rect(rect: Dict[str, float], crop: Crop,
                 image_size: Tuple[int, int]) -> Dict[str, float]:
    """Returns where the kept part is, the whole image being at rect."""
    width, height = image_size
    kept_width, kept_height = crop.kept_size(width, height)
    scale_x, scale_y = rect["width"] / width, rect["height"] / height
    return {"posx": rect["posx"] + crop.left * scale_x,
            "posy": rect["posy"] + crop.top * scale_y,
            "width": kept_width * scale_x,
            "height": kept_height * scale_y}


def apply_crop(clip: GES.Clip, crop: Crop) -> None:
    """Crops the clip, the rest of the image keeping its place.

    With the blurred fill, the rest of the image is fitted again.
    Call it in an undoable operation, it does not commit.
    """
    # pylint: disable=import-outside-toplevel
    from pitivi.utils.blurfill import get_blur_fill
    from pitivi.utils.blurfill import get_blur_fill_position
    from pitivi.utils.blurfill import get_image_size
    from pitivi.utils.blurfill import set_blur_fill_position
    from pitivi.utils.blurfill import update_blur_fill
    from pitivi.utils.motion import get_base_position
    from pitivi.utils.motion import has_motion
    from pitivi.utils.motion import set_base_position
    from pitivi.utils.transitions import sync_pushes

    source = clip.find_track_element(None, GES.VideoSource)
    if not source:
        return
    old_crop = get_crop(clip)
    if old_crop == crop:
        return
    # The image as turned, before cropping.
    image_size = get_image_size(clip, cropped=False)

    if get_blur_fill(clip):
        # The photo in front of the fill keeps its place, a video is
        # fitted again.
        position = get_blur_fill_position(clip)
        whole = uncropped_rect(position, old_crop, image_size) if position else None
        set_crop(clip, crop)
        # Made again for the image kept.
        update_blur_fill(clip)
        if whole:
            set_blur_fill_position(clip, {prop: round(value) for prop, value
                                          in cropped_rect(whole, crop, image_size).items()})
    else:
        whole = uncropped_rect(get_base_position(source), old_crop, image_size)
        set_crop(clip, crop)
        rect = {prop: round(value) for prop, value in cropped_rect(whole, crop, image_size).items()}
        if has_motion(source):
            set_base_position(source, rect)
        else:
            for prop, value in rect.items():
                source.set_child_property(prop, value)
    layer = clip.get_layer()
    if layer:
        sync_pushes(layer)
