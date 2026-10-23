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
"""The motion of the clips: the automatic zoom and the pushes.

The position and the size of a source are animated for its automatic
zoom, over the whole source, and for the pushes at its ends. The base
position, where the source is when not moving, is kept in metadata while
the properties are animated, and the animations are computed again from
it whenever something changes.

The animations are never removed: GES changes the keyframes of a control
source when added again, as when undoing. A source without motion has
flat animations.
"""
from typing import Dict
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Tuple

from gi.repository import GES
from gi.repository import GstController

from pitivi.utils.fades import get_source_range
from pitivi.utils.fades import set_keyframes
from pitivi.utils.blurfill import get_blur_fill
from pitivi.utils.blurfill import get_blur_sigma
from pitivi.utils.blurfill import get_fit_rect
from pitivi.utils.blurfill import is_blur_fill_needed
from pitivi.utils.blurfill import set_blur_fill_active
from pitivi.utils.kenburns import ELEMENT_NAME as ZOOM_ELEMENT_NAME

MOTION_PROPERTIES = ("posx", "posy", "width", "height")

# The position of a source when not moving, kept while its position is
# animated. The name comes from the pushes, which were animated first.
BASE_META = "spl::push-base-%s"

ZOOM_KIND_META = "spl::zoom-kind"
ZOOM_ANCHOR_META = "spl::zoom-anchor"
ZOOM_SCALE_META = "spl::zoom-scale"

ZOOM_IN = "in"
ZOOM_OUT = "out"

# Where the zoom goes, as a fraction of the frame.
ANCHORS = {"top-left": (0, 0), "top": (0.5, 0), "top-right": (1, 0),
           "left": (0, 0.5), "center": (0.5, 0.5), "right": (1, 0.5),
           "bottom-left": (0, 1), "bottom": (0.5, 1), "bottom-right": (1, 1)}

# The hidden effect which zooms the photos with sub-pixel precision, see
# the kenburns module. The source covers the frame and the effect places the
# image in its rectangle, the base position, and zooms and slides it.
ZOOM_EFFECT_META = "spl::zoom-effect"
ZOOM_EFFECT_RECT = {"posx": "rect-x", "posy": "rect-y", "width": "rect-width", "height": "rect-height"}

DEFAULT_ANCHOR = "center"
DEFAULT_SCALE = 1.2
MIN_SCALE = 1.05
MAX_SCALE = 2.0


class Zoom(NamedTuple):
    """The automatic zoom of a source.

    Attributes:
        kind: ZOOM_IN, ending bigger, or ZOOM_OUT, starting bigger.
        anchor: The point of the frame which stays in place, see ANCHORS.
        scale: How much bigger, 1.2 being 20 % bigger.
    """

    kind: str
    anchor: str = DEFAULT_ANCHOR
    scale: float = DEFAULT_SCALE


# A linear change of a property: from (timestamp, value) to (timestamp, value).
Segment = Tuple[int, float, int, float]


def get_zoom(source: GES.VideoSource) -> Optional[Zoom]:
    """Returns the automatic zoom of the source, if any."""
    kind = source.get_string(ZOOM_KIND_META)
    if kind not in (ZOOM_IN, ZOOM_OUT):
        return None
    anchor = source.get_string(ZOOM_ANCHOR_META)
    if anchor not in ANCHORS:
        anchor = DEFAULT_ANCHOR
    res, scale = source.get_double(ZOOM_SCALE_META)
    if not res:
        scale = DEFAULT_SCALE
    return Zoom(kind, anchor, min(MAX_SCALE, max(MIN_SCALE, scale)))


def set_zoom(source: GES.VideoSource, zoom: Optional[Zoom]) -> None:
    """Sets the automatic zoom of the source. Call `sync_motion` after."""
    kind = zoom.kind if zoom else ""
    if source.get_string(ZOOM_KIND_META) != kind:
        source.set_string(ZOOM_KIND_META, kind)
    if not zoom:
        return
    if source.get_string(ZOOM_ANCHOR_META) != zoom.anchor:
        source.set_string(ZOOM_ANCHOR_META, zoom.anchor)
    res, scale = source.get_double(ZOOM_SCALE_META)
    if not res or abs(scale - zoom.scale) > 0.0001:
        source.set_double(ZOOM_SCALE_META, zoom.scale)


def is_zoom_effect(effect: GES.TrackElement) -> bool:
    """Whether the effect is the one zooming the photo."""
    if not isinstance(effect, GES.BaseEffect):
        return False
    res, value = effect.get_boolean(ZOOM_EFFECT_META)
    return bool(res and value)


def get_zoom_effect(clip: Optional[GES.Clip]) -> Optional[GES.BaseEffect]:
    """Returns the effect zooming the photo of the clip, if any."""
    for effect in clip.get_top_effects() if clip else []:
        if is_zoom_effect(effect):
            return effect
    return None


def uses_zoom_effect(source: GES.VideoSource) -> bool:
    """Whether the zoom of the source is made by the effect, for the photos.

    The compositor places the sources in whole pixels, a slow zoom of a
    photo shakes. The videos hide it.
    """
    clip = source.get_parent()
    asset = clip.get_asset() if clip else None
    return bool(get_zoom(source) and asset and asset.is_image())


def zoom_effect_description(frame_size: Tuple[int, int], max_zoom: float) -> str:
    """Returns the bin description of the effect zooming the photo."""
    return ("videoconvert ! video/x-raw,format=BGRA ! "
            "%s name=spl-zoom static=true max-zoom=%.3f ! "
            "capsfilter caps=video/x-raw,width=%d,height=%d ! videoconvert"
            % ((ZOOM_ELEMENT_NAME, max_zoom) + tuple(frame_size)))


def is_moving(source: GES.VideoSource, property_name: str) -> bool:
    """Whether the property is animated for the motion of the source."""
    res, unused_base = source.get_int(BASE_META % property_name)
    return res and source.get_control_binding(property_name) is not None


def has_motion(source: GES.VideoSource) -> bool:
    """Whether the position of the source is animated for its motion."""
    return bool(get_zoom_effect(source.get_parent())) or \
        any(is_moving(source, prop) for prop in MOTION_PROPERTIES)


def is_animated_by_user(source: GES.VideoSource) -> bool:
    """Whether the position of the source has keyframes added by the user."""
    return any(source.get_control_binding(prop) is not None and not is_moving(source, prop)
               for prop in MOTION_PROPERTIES)


def get_base_position(source: GES.VideoSource) -> Dict[str, int]:
    """Returns the position of the source when not moving."""
    effect = get_zoom_effect(source.get_parent())
    if effect:
        return {prop: round(effect.get_child_property(name)[1])
                for prop, name in ZOOM_EFFECT_RECT.items()}
    return _get_source_base(source)


def _get_source_base(source: GES.VideoSource) -> Dict[str, int]:
    position = {}
    for prop in MOTION_PROPERTIES:
        if is_moving(source, prop):
            position[prop] = source.get_int(BASE_META % prop)[1]
        else:
            position[prop] = source.get_child_property(prop)[1]
    return position


def set_base_position(source: GES.VideoSource, position: Dict[str, int]) -> None:
    """Sets the position of the source when not moving. Call `sync_motion` after."""
    effect = get_zoom_effect(source.get_parent())
    if effect:
        for prop, value in position.items():
            name = ZOOM_EFFECT_RECT[prop]
            if effect.get_child_property(name)[1] != float(value):
                effect.set_child_property(name, float(value))
        return
    _set_source_base(source, position)


def _set_source_base(source: GES.VideoSource, position: Dict[str, int]) -> None:
    for prop, value in position.items():
        value = int(value)
        if is_moving(source, prop):
            if source.get_int(BASE_META % prop)[1] != value:
                source.set_int(BASE_META % prop, value)
        elif source.get_child_property(prop)[1] != value:
            source.set_child_property(prop, value)


def get_frame_size(source: GES.VideoSource) -> Tuple[int, int]:
    caps = source.get_track().get_restriction_caps()
    structure = caps.get_structure(0)
    return structure.get_int("width")[1], structure.get_int("height")[1]


def _zoomed(base: Dict[str, int], zoom: Zoom, factor: float, frame_size) -> Dict[str, float]:
    """Returns the position of the source made bigger by factor, around the anchor."""
    fraction_x, fraction_y = ANCHORS[zoom.anchor]
    anchor_x = fraction_x * frame_size[0]
    anchor_y = fraction_y * frame_size[1]
    return {"posx": anchor_x - (anchor_x - base["posx"]) * factor,
            "posy": anchor_y - (anchor_y - base["posy"]) * factor,
            "width": base["width"] * factor,
            "height": base["height"] * factor}


def _segment_value(segment: Segment, timestamp: int) -> float:
    start, start_value, end, end_value = segment
    if timestamp < start or timestamp > end:
        return 0
    if end == start:
        return end_value
    return start_value + (end_value - start_value) * (timestamp - start) / (end - start)


def motion_keyframes(base: Dict[str, int], zoom: Optional[Zoom], pushes: Dict[str, List[Segment]],
                     start: int, end: int, frame_size) -> Dict[str, List[Tuple[int, float]]]:
    """Returns the keyframes of the properties which move.

    Args:
        base: The position of the source when not moving.
        zoom: The automatic zoom, if any.
        pushes: The offsets of the pushes, by property.
        start: The internal time where the source starts.
        end: The internal time where the source ends.
        frame_size: The width and the height of the frame.
    """
    keyframes = {}
    for prop in MOTION_PROPERTIES:
        segments = pushes.get(prop, [])
        if not zoom and not segments:
            continue
        timestamps = {start, end}
        for segment_start, unused, segment_end, unused in segments:
            timestamps.update((segment_start, segment_end))
        values = []
        for timestamp in sorted(timestamps):
            value = base[prop]
            if zoom:
                progress = (timestamp - start) / (end - start) if end > start else 0
                if zoom.kind == ZOOM_OUT:
                    progress = 1 - progress
                factor = 1 + (zoom.scale - 1) * progress
                value = _zoomed(base, zoom, factor, frame_size)[prop]
            value += sum(_segment_value(segment, timestamp) for segment in segments)
            values.append((timestamp, value))
        keyframes[prop] = values
    return keyframes


def sync_motion(source: GES.VideoSource, pushes: Dict[str, List[Segment]]) -> None:
    """Animates the position of the source for its zoom and its pushes."""
    if not source.get_track():
        return
    clip = source.get_parent()
    effect = get_zoom_effect(clip)
    if uses_zoom_effect(source):
        _sync_zoom_effect(source, effect, pushes)
        return
    if effect:
        # The photo is placed by the source again.
        base = get_base_position(source)
        clip.remove(effect)
        _set_source_base(source, base)
    if get_blur_fill(clip):
        # The effect of the blurred fill makes the frame again, if needed.
        set_blur_fill_active(clip, is_blur_fill_needed(clip))
    _sync_source(source, get_zoom(source), pushes)


def _sync_zoom_effect(source: GES.VideoSource, effect: Optional[GES.BaseEffect],
                      pushes: Dict[str, List[Segment]]) -> None:
    """Zooms and slides the photo with the effect, the source covers the frame."""
    clip = source.get_parent()
    zoom = get_zoom(source)
    frame_size = get_frame_size(source)
    description = zoom_effect_description(frame_size, zoom.scale)
    if not effect or effect.props.bin_description != description:
        base = get_base_position(source)
        if effect:
            clip.remove(effect)
        effect = GES.Effect.new(description)
        effect.set_boolean(ZOOM_EFFECT_META, True)
        clip.add(effect)
        for prop, name in ZOOM_EFFECT_RECT.items():
            effect.set_child_property(name, float(base[prop]))
    # Always, a clip split or pasted getting the position of a new one.
    width, height = frame_size
    _set_source_base(source, {"posx": 0, "posy": 0, "width": width, "height": height})
    if clip.get_top_effect_index(effect) != 0:
        # After the other effects, the blurred fill making the frame.
        clip.set_top_effect_index(effect, 0)
    if get_blur_fill(clip):
        # Its effect remakes the fill in every frame, too slow with the zoom.
        # This effect makes it once, behind the photo fitting the frame.
        set_blur_fill_active(clip, False)
        sigma = get_blur_sigma(source) if is_blur_fill_needed(clip) else 0.0
        rect = dict(zip(("posx", "posy", "width", "height"), get_fit_rect(clip)))
    else:
        sigma = 0.0
        rect = None
    if effect.get_child_property("fill-sigma")[1] != sigma:
        effect.set_child_property("fill-sigma", sigma)
    for prop, name in ZOOM_EFFECT_RECT.items() if rect else ():
        if effect.get_child_property(name)[1] != rect[prop]:
            effect.set_child_property(name, rect[prop])
    fraction_x, fraction_y = ANCHORS[zoom.anchor]
    for name, value in (("anchor-x", fraction_x), ("anchor-y", fraction_y)):
        if effect.get_child_property(name)[1] != value:
            effect.set_child_property(name, float(value))

    start, end = get_source_range(source)
    zoom_keyframes = []
    for timestamp in (start, end):
        progress = (timestamp - start) / (end - start) if end > start else 0
        if zoom.kind == ZOOM_OUT:
            progress = 1 - progress
        zoom_keyframes.append((timestamp, 1 + (zoom.scale - 1) * progress))
    _set_effect_keyframes(effect, "zoom", zoom_keyframes)
    for prop, name in (("posx", "offset-x"), ("posy", "offset-y")):
        segments = pushes.get(prop, [])
        timestamps = {start, end}
        for segment_start, unused, segment_end, unused in segments:
            timestamps.update((segment_start, segment_end))
        _set_effect_keyframes(effect, name, [
            (timestamp, sum(_segment_value(segment, timestamp) for segment in segments))
            for timestamp in sorted(timestamps)])
    # The source covers the frame, still.
    _sync_source(source, None, {})


def _set_effect_keyframes(effect: GES.BaseEffect, name: str, keyframes) -> None:
    binding = effect.get_control_binding(name)
    if binding:
        control_source = binding.props.control_source
    else:
        control_source = GstController.InterpolationControlSource()
        control_source.props.mode = GstController.InterpolationMode.LINEAR
        effect.set_control_source(control_source, name, "direct-absolute")
    set_keyframes(control_source, keyframes)


def _sync_source(source: GES.VideoSource, zoom: Optional[Zoom], pushes: Dict[str, List[Segment]]) -> None:
    """Animates the position of the source itself for the zoom and the pushes."""
    start, end = get_source_range(source)
    base = _get_source_base(source)
    keyframes = motion_keyframes(base, zoom, pushes, start, end, get_frame_size(source))
    for prop in MOTION_PROPERTIES:
        binding = source.get_control_binding(prop)
        moving = is_moving(source, prop)
        if binding and not moving:
            # Animated by the user.
            continue
        prop_keyframes = keyframes.get(prop)
        if not prop_keyframes:
            if moving:
                # The animation is kept, still.
                set_keyframes(binding.props.control_source, [(start, base[prop]), (end, base[prop])])
            continue
        if not moving:
            source.set_int(BASE_META % prop, base[prop])
            control_source = GstController.InterpolationControlSource()
            control_source.props.mode = GstController.InterpolationMode.LINEAR
            # Never empty, for whoever reads it.
            control_source.set(start, base[prop])
            source.set_control_source(control_source, prop, "direct-absolute")
            binding = source.get_control_binding(prop)
        set_keyframes(binding.props.control_source, prop_keyframes)
