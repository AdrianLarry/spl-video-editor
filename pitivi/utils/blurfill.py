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
"""The blurred fill: the image fits the frame, over a blurred copy filling it.

An effect hidden from the user makes the whole frame: the image made
bigger to cover a small frame, blurred and made big again, and the image
fitting the frame over it. The source covers the frame.

The effect makes new buffers, which lose the position and the alpha GES
gives the source, so the effect does them: its last element slides the
frame for the pushes, and the alpha element after it has the alpha of the
source, sharing its control source. The alpha of videobox is ignored when
it does not box anything.
"""
from typing import Optional
from typing import Tuple

from gi.repository import GES
from gi.repository import GstController

from pitivi.clip_properties.orientation import get_orientation

BLUR_FILL_META = "spl::blur-fill"

# The size of the blurred background before it is made big, the bigger
# side. Blurring a small image is fast, and it is blurred anyway.
BACKGROUND_SIZE = 480
BLUR_SIGMA = 6

# The properties of the last element, sliding the frame.
SHIFT_PROPERTIES = {"posx": ("GstVideoBox::left", "GstVideoBox::right"),
                    "posy": ("GstVideoBox::top", "GstVideoBox::bottom")}
ALPHA_PROPERTY = "GstAlpha::alpha"


def is_blur_fill_effect(effect: GES.TrackElement) -> bool:
    """Whether the effect is the one making the blurred fill."""
    if not isinstance(effect, GES.BaseEffect):
        return False
    res, value = effect.get_boolean(BLUR_FILL_META)
    return bool(res and value)


def get_blur_fill(clip: GES.Clip) -> Optional[GES.BaseEffect]:
    """Returns the effect making the blurred fill of the clip, if any."""
    for effect in clip.get_top_effects():
        if is_blur_fill_effect(effect):
            return effect
    return None


def _even(value: float) -> int:
    return max(2, round(value / 2) * 2)


def get_image_size(clip: GES.Clip) -> Optional[Tuple[int, int]]:
    """Returns the size of the image of the clip, as turned."""
    asset = clip.get_asset()
    if not asset:
        return None
    streams = asset.get_info().get_video_streams()
    if not streams:
        return None
    width, height = streams[0].get_natural_width(), streams[0].get_natural_height()
    if get_orientation(clip).swaps_dimensions:
        width, height = height, width
    return width, height


def blur_fill_description(image_size: Tuple[int, int], frame_size: Tuple[int, int]) -> str:
    """Returns the bin description of the effect making the blurred fill."""
    image_width, image_height = image_size
    frame_width, frame_height = frame_size

    # The background, small: the image covering a small frame.
    ratio = BACKGROUND_SIZE / max(frame_width, frame_height)
    small_width, small_height = _even(frame_width * ratio), _even(frame_height * ratio)
    cover = max(small_width / image_width, small_height / image_height)
    cover_width, cover_height = _even(image_width * cover), _even(image_height * cover)
    crop_x, crop_y = cover_width - small_width, cover_height - small_height

    # The image fitting the frame.
    fit = min(frame_width / image_width, frame_height / image_height)
    fit_width, fit_height = _even(image_width * fit), _even(image_height * fit)

    return ("tee name=spl-tee "
            "spl-tee. ! queue ! videoscale ! capsfilter caps=video/x-raw,width=%d,height=%d ! "
            "videocrop left=%d right=%d top=%d bottom=%d ! gaussianblur sigma=%d ! videoscale ! "
            "capsfilter caps=video/x-raw,width=%d,height=%d ! spl-mix.sink_0 "
            "spl-tee. ! queue ! videoscale ! capsfilter caps=video/x-raw,width=%d,height=%d ! spl-mix.sink_1 "
            "compositor name=spl-mix sink_1::xpos=%d sink_1::ypos=%d ! "
            "capsfilter caps=video/x-raw,width=%d,height=%d ! "
            "videobox border-alpha=0 ! alpha name=spl-alpha ! "
            "capsfilter caps=video/x-raw,format=AYUV,width=%d,height=%d"
            % (cover_width, cover_height,
               crop_x // 2, crop_x - crop_x // 2, crop_y // 2, crop_y - crop_y // 2, BLUR_SIGMA,
               frame_width, frame_height,
               fit_width, fit_height,
               (frame_width - fit_width) // 2, (frame_height - fit_height) // 2,
               frame_width, frame_height, frame_width, frame_height))


def _frame_size(source: GES.VideoSource) -> Tuple[int, int]:
    caps = source.get_track().get_restriction_caps()
    structure = caps.get_structure(0)
    return structure.get_int("width")[1], structure.get_int("height")[1]


def get_alpha_control_source(source: GES.VideoSource):
    binding = source.get_control_binding("alpha")
    return binding.props.control_source if binding else None


def link_alpha(effect: GES.BaseEffect, source: GES.VideoSource) -> None:
    """Gives the effect the alpha of the source, sharing its control source."""
    control_source = get_alpha_control_source(source)
    if not control_source:
        return
    binding = effect.get_control_binding(ALPHA_PROPERTY)
    if binding and binding.props.control_source is control_source:
        return
    effect.set_control_source(control_source, ALPHA_PROPERTY, "direct")


def set_blur_fill(clip: GES.Clip, enabled: bool) -> Optional[GES.BaseEffect]:
    """Adds or removes the blurred fill of the clip, returns the effect.

    Call `sync_pushes` on the layer after it, for the pushes.
    """
    from pitivi.utils.motion import set_base_position  # pylint: disable=import-outside-toplevel

    source = clip.find_track_element(None, GES.VideoSource)
    effect = get_blur_fill(clip)
    if not enabled:
        if effect:
            clip.remove(effect)
        return None
    if not source or not source.get_track():
        return None

    frame_size = _frame_size(source)
    description = blur_fill_description(get_image_size(clip), frame_size)
    if effect and effect.props.bin_description == description:
        return effect
    if effect:
        clip.remove(effect)
    effect = GES.Effect.new(description)
    effect.set_boolean(BLUR_FILL_META, True)
    clip.add(effect)
    # After the other effects, rotating the image or changing its colors.
    clip.set_top_effect_index(effect, 0)
    width, height = frame_size
    set_base_position(source, {"posx": 0, "posy": 0, "width": width, "height": height})
    link_alpha(effect, source)
    return effect


def update_blur_fill(clip: GES.Clip) -> None:
    """Makes the blurred fill again if the frame or the image changed."""
    if get_blur_fill(clip):
        set_blur_fill(clip, True)


def sync_shift(effect: GES.BaseEffect, offsets, start: int, end: int) -> None:
    """Slides the frame made by the effect, for the pushes.

    Args:
        effect: The effect making the blurred fill.
        offsets: The keyframes of the offsets by property, posx or posy.
        start: The internal time where the source starts.
        end: The internal time where the source ends.
    """
    from pitivi.utils.fades import set_keyframes  # pylint: disable=import-outside-toplevel

    for prop, (cropped_side, other_side) in SHIFT_PROPERTIES.items():
        keyframes = offsets.get(prop) or [(start, 0), (end, 0)]
        for name, sign in ((cropped_side, -1), (other_side, 1)):
            binding = effect.get_control_binding(name)
            values = [(timestamp, sign * value) for timestamp, value in keyframes]
            if not binding:
                if not offsets.get(prop):
                    continue
                control_source = GstController.InterpolationControlSource()
                control_source.props.mode = GstController.InterpolationMode.LINEAR
                control_source.set(start, 0)
                effect.set_control_source(control_source, name, "direct-absolute")
                binding = effect.get_control_binding(name)
            set_keyframes(binding.props.control_source, values)
