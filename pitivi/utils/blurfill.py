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
source, sharing its control source. A final framepositioner restores the
composition metadata required by GES transitions and layer stacking.
The alpha of videobox is ignored when
it does not box anything.
"""
from typing import Optional
from typing import Tuple

from gi.repository import GES
from gi.repository import GstController

from pitivi.clip_properties.crop import cropped_size
from pitivi.clip_properties.orientation import get_orientation

BLUR_FILL_META = "spl::blur-fill"
BLUR_SIGMA_META = "spl::blur-sigma"

# The size of the blurred background before it is made big, the bigger
# side. Blurring a small image is fast, and it is blurred anyway: at 240
# exporting a video with the fill is about 3 times faster than at 480.
BACKGROUND_SIZE = 240
# The sigma chosen by the user blurs a background this big, the same blur
# for any BACKGROUND_SIZE.
SIGMA_SIZE = 480
DEFAULT_BLUR_SIGMA = 6.0
MIN_BLUR_SIGMA = 1.0
MAX_BLUR_SIGMA = 20.0

# The properties of the last element, sliding the frame.
SHIFT_PROPERTIES = {"posx": ("GstVideoBox::left", "GstVideoBox::right"),
                    "posy": ("GstVideoBox::top", "GstVideoBox::bottom")}
ALPHA_PROPERTY = "GstAlpha::alpha"
# The blurred fill is kept but inactive when the image fitting the frame
# leaves at most this on its sides: it would be hidden.
FITS_MARGIN = 2


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


def get_blur_fill_position(clip):
    """Returns the editable foreground rectangle of a photo fill, if present."""
    effect = get_blur_fill(clip)
    if not effect or "name=spl-foreground" not in effect.props.bin_description:
        return None
    return {prop: effect.get_child_property(name)[1] for prop, name in
            (("posx", "rect-x"), ("posy", "rect-y"),
             ("width", "rect-width"), ("height", "rect-height"))}


def set_blur_fill_position(clip, position):
    """Changes the foreground, leaving the blurred background full-frame."""
    effect = get_blur_fill(clip)
    if not effect or "name=spl-foreground" not in effect.props.bin_description:
        return
    names = {"posx": "rect-x", "posy": "rect-y", "width": "rect-width", "height": "rect-height"}
    for prop, value in position.items():
        effect.set_child_property(names[prop], float(value))


def get_active_blur_fill(clip: GES.Clip) -> Optional[GES.BaseEffect]:
    """Returns the effect making the blurred fill of the clip, if active."""
    effect = get_blur_fill(clip)
    return effect if effect and effect.props.active else None


def is_fill_needed(image_size: Tuple[int, int], frame_size: Tuple[int, int]) -> bool:
    """Whether the image fitting the frame leaves room for the blurred fill."""
    image_width, image_height = image_size
    frame_width, frame_height = frame_size
    fit = min(frame_width / image_width, frame_height / image_height)
    return frame_width - image_width * fit > FITS_MARGIN or \
        frame_height - image_height * fit > FITS_MARGIN


def _set_needed(effect: GES.BaseEffect, needed: bool) -> None:
    if effect.props.active != needed:
        effect.props.active = needed


def is_blur_fill_needed(clip: GES.Clip) -> bool:
    """Whether the image of the clip leaves room for its blurred fill."""
    source = clip.find_track_element(None, GES.VideoSource)
    if not source or not source.get_track():
        return False
    frame_size = _frame_size(source)
    position = get_blur_fill_position(clip)
    if position is not None:
        full = dict(zip(("posx", "posy", "width", "height"), (0, 0, *frame_size)))
        return any(abs(position[prop] - value) > FITS_MARGIN for prop, value in full.items())
    return is_fill_needed(get_image_size(clip), frame_size)


def set_blur_fill_active(clip: GES.Clip, active: bool) -> None:
    """Makes the effect of the blurred fill active or not, if any.

    It is inactive when not needed, or when the effect zooming the photo
    makes the fill.
    """
    effect = get_blur_fill(clip)
    if effect:
        _set_needed(effect, active)


def get_fit_rect(clip: GES.Clip) -> Tuple[float, float, float, float]:
    """Returns where the image of the clip fits the frame: x, y, width, height."""
    source = clip.find_track_element(None, GES.VideoSource)
    image_width, image_height = get_image_size(clip)
    frame_width, frame_height = _frame_size(source)
    fit = min(frame_width / image_width, frame_height / image_height)
    width, height = image_width * fit, image_height * fit
    return (frame_width - width) / 2, (frame_height - height) / 2, width, height


def get_blur_sigma(container: GES.MetaContainer) -> float:
    """Returns the sigma of the blurred fill, or DEFAULT_BLUR_SIGMA."""
    res, sigma = container.get_double(BLUR_SIGMA_META)
    if res and sigma > 0:
        return min(MAX_BLUR_SIGMA, max(MIN_BLUR_SIGMA, sigma))
    if isinstance(container, GES.Clip):
        source = container.find_track_element(None, GES.VideoSource)
        if source:
            return get_blur_sigma(source)
    elif isinstance(container, GES.VideoSource):
        clip = container.get_parent()
        if clip:
            res, sigma = clip.get_double(BLUR_SIGMA_META)
            if res and sigma > 0:
                return min(MAX_BLUR_SIGMA, max(MIN_BLUR_SIGMA, sigma))
    return DEFAULT_BLUR_SIGMA


def _element_sigma(sigma: float) -> float:
    return sigma * BACKGROUND_SIZE / SIGMA_SIZE


def set_effect_sigma(effect: GES.BaseEffect, sigma: float) -> None:
    """Sets the blur chosen by the user on the effect making the fill."""
    effect.set_child_property("sigma", _element_sigma(sigma))


def set_blur_sigma(source: GES.VideoSource, sigma: float) -> None:
    """Sets the blur amount for the blurred fill."""
    sigma = min(MAX_BLUR_SIGMA, max(MIN_BLUR_SIGMA, float(sigma)))
    source.set_double(BLUR_SIGMA_META, sigma)
    clip = source.get_parent()
    if clip:
        clip.set_double(BLUR_SIGMA_META, sigma)
        effect = get_blur_fill(clip)
        if effect:
            set_effect_sigma(effect, sigma)
        from pitivi.utils.motion import get_zoom_effect  # pylint: disable=import-outside-toplevel
        zoom_effect = get_zoom_effect(clip)
        if zoom_effect and zoom_effect.get_child_property("fill-sigma")[1]:
            # The effect zooming the photo makes its fill.
            zoom_effect.set_child_property("fill-sigma", float(sigma))


def _even(value: float) -> int:
    return max(2, round(value / 2) * 2)


def get_image_size(clip: GES.Clip, cropped: bool = True) -> Optional[Tuple[int, int]]:
    """Returns the size of the image of the clip, as turned and cropped."""
    asset = clip.get_asset()
    if not asset:
        return None
    streams = asset.get_info().get_video_streams()
    if not streams:
        return None
    width, height = streams[0].get_natural_width(), streams[0].get_natural_height()
    if get_orientation(clip).swaps_dimensions:
        width, height = height, width
    if cropped:
        width, height = cropped_size(clip, width, height)
    return width, height


def blur_fill_description(image_size: Tuple[int, int], frame_size: Tuple[int, int],
                          sigma: float = DEFAULT_BLUR_SIGMA, foreground: bool = False) -> str:
    """Returns the bin description of the effect making the blurred fill."""
    image_width, image_height = image_size
    frame_width, frame_height = frame_size

    # The background, small: the image covering a small frame.
    ratio = BACKGROUND_SIZE / max(frame_width, frame_height)
    small_width, small_height = _even(frame_width * ratio), _even(frame_height * ratio)
    cover = max(small_width / image_width, small_height / image_height)
    cover_width, cover_height = _even(image_width * cover), _even(image_height * cover)
    crop_x, crop_y = cover_width - small_width, cover_height - small_height

    # The sizes keep square pixels: else videoscale changes the pixel aspect
    # ratio to keep the shape of the image, the compositor makes it a bit
    # narrower and the last column shows the background of the compositor.

    # The image fitting the frame.
    fit = min(frame_width / image_width, frame_height / image_height)
    fit_width, fit_height = _even(image_width * fit), _even(image_height * fit)

    # The split of the frames is splsplit and not a tee: GES copies the
    # properties when splitting or pasting the clip, see splittee.
    description = ("videoconvert ! splsplit name=spl-split "
            "spl-split. ! queue ! videoscale ! capsfilter caps=video/x-raw,width=%d,height=%d,pixel-aspect-ratio=1/1 ! "
            "videocrop left=%d right=%d top=%d bottom=%d ! gaussianblur sigma=%g ! videoscale ! "
            "capsfilter caps=video/x-raw,width=%d,height=%d,pixel-aspect-ratio=1/1 ! spl-mix.sink_0 "
            "spl-split. ! queue ! videoscale ! "
            "capsfilter caps=video/x-raw,width=%d,height=%d,pixel-aspect-ratio=1/1 ! spl-mix.sink_1 "
            "compositor name=spl-mix background=black sink_1::xpos=%d sink_1::ypos=%d ! "
            "capsfilter caps=video/x-raw,width=%d,height=%d ! "
            "videobox border-alpha=0 ! alpha name=spl-alpha ! "
            "framepositioner name=spl-positioner ! "
            "capsfilter caps=video/x-raw,format=AYUV,width=%d,height=%d ! videoconvert"
            % (cover_width, cover_height,
               crop_x // 2, crop_x - crop_x // 2, crop_y // 2, crop_y - crop_y // 2, _element_sigma(round(sigma)),
               frame_width, frame_height,
               fit_width, fit_height,
               (frame_width - fit_width) // 2, (frame_height - fit_height) // 2,
               frame_width, frame_height, frame_width, frame_height))
    if foreground:
        original = ("spl-split. ! queue ! videoscale ! "
                    "capsfilter caps=video/x-raw,width=%d,height=%d,pixel-aspect-ratio=1/1 ! spl-mix.sink_1"
                    % (fit_width, fit_height))
        editable = ("spl-split. ! queue ! videoconvert ! video/x-raw,format=BGRA ! "
                    "splzoom name=spl-foreground static=true max-zoom=1 "
                    "rect-x=%d rect-y=%d rect-width=%d rect-height=%d ! "
                    "capsfilter caps=video/x-raw,width=%d,height=%d,pixel-aspect-ratio=1/1 ! "
                    "videoconvert ! spl-mix.sink_1"
                    % ((frame_width - fit_width) // 2, (frame_height - fit_height) // 2,
                       fit_width, fit_height, frame_width, frame_height))
        description = description.replace(original, editable).replace(
            "sink_1::xpos=%d sink_1::ypos=%d" % ((frame_width - fit_width) // 2, (frame_height - fit_height) // 2),
            "sink_1::xpos=0 sink_1::ypos=0")
    return description


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


def _sync_composition_priority(effect, unused_pspec=None):
    # Match GESVideoSource's framepositioner: smaller timeline priorities
    # are drawn above larger ones. Keep this current when layers move.
    effect.set_child_property("GstFramePositioner::zorder",
                              0xffffffff - effect.props.priority)


def _configure_composition(effect):
    if not effect.handler_is_connected(getattr(effect, "_blur_priority_handler", 0)):
        effect._blur_priority_handler = effect.connect(
            "notify::priority", _sync_composition_priority)
    _sync_composition_priority(effect)


def restore_blur_fills(timeline):
    """Upgrades saved fills and reconnects their runtime synchronization."""
    from pitivi.utils.transitions import sync_pushes  # pylint: disable=import-outside-toplevel

    for layer in timeline.get_layers():
        fills = [clip for clip in layer.get_clips() if get_blur_fill(clip)]
        for clip in fills:
            set_blur_fill(clip, True)
        if fills:
            sync_pushes(layer)


def set_blur_fill(clip: GES.Clip, enabled: bool, sigma: Optional[float] = None) -> Optional[GES.BaseEffect]:
    """Adds or removes the blurred fill of the clip, returns the effect.

    Call `sync_pushes` on the layer after it, for the pushes.
    """
    from pitivi.utils.motion import _set_source_base  # pylint: disable=import-outside-toplevel

    source = clip.find_track_element(None, GES.VideoSource)
    effect = get_blur_fill(clip)
    if not enabled:
        if effect:
            position = get_blur_fill_position(clip)
            clip.remove(effect)
            if position:
                _set_source_base(source, position)
        return None
    if not source or not source.get_track():
        return None

    if sigma is None:
        sigma = get_blur_sigma(source)
    sigma = min(MAX_BLUR_SIGMA, max(MIN_BLUR_SIGMA, float(sigma)))

    frame_size = _frame_size(source)
    image_size = get_image_size(clip)
    description = blur_fill_description(image_size, frame_size, sigma, foreground=clip.get_asset().is_image())
    # Kept for when the frame changes again, but the image covers it.
    if effect and effect.props.bin_description == description:
        set_effect_sigma(effect, sigma)
        _configure_composition(effect)
        link_alpha(effect, source)
        _set_needed(effect, is_blur_fill_needed(clip))
        return effect
    position = get_blur_fill_position(clip)
    if (source.get_child_property("width")[1], source.get_child_property("height")[1]) != frame_size:
        position = None
    if effect:
        clip.remove(effect)
    effect = GES.Effect.new(description)
    effect.set_boolean(BLUR_FILL_META, True)
    set_effect_sigma(effect, sigma)
    clip.set_double(BLUR_SIGMA_META, float(sigma))
    source.set_double(BLUR_SIGMA_META, float(sigma))
    clip.add(effect)
    # After the other effects, rotating the image or changing its colors.
    clip.set_top_effect_index(effect, 0)
    _configure_composition(effect)
    width, height = frame_size
    _set_source_base(source, {"posx": 0, "posy": 0, "width": width, "height": height})
    if position:
        set_blur_fill_position(clip, position)
    link_alpha(effect, source)
    _set_needed(effect, is_blur_fill_needed(clip))
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
