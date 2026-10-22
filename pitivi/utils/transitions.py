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
"""Transitions where two clips of a layer meet.

The kind of a transition is found from the clips, there is no other
record of it:
- A dissolve is two clips overlapping, for which GES creates a
  transition. Adding it moves the second clip and the following ones of
  the layer to the left, so the project gets shorter.
- A fade to black is two clips meeting, the first fading out and the
  second fading in. Nothing moves.
- A soft wipe is like a dissolve, the second clip appearing from a side.
- A push is like a dissolve, the second clip pushing the first one out of
  the frame. Their positions are animated during the transition, and a
  hard wipe follows the edge between them.
- A fade to white is two clips meeting, the first turning white and the
  second turning back from white, with an effect of each clip hidden
  from the user. Nothing moves.
"""
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Tuple

from gi.repository import GES
from gi.repository import Gst
from gi.repository import GstController

from pitivi.utils.blurfill import get_active_blur_fill
from pitivi.utils.blurfill import get_blur_fill
from pitivi.utils.blurfill import get_image_size
from pitivi.utils.blurfill import link_alpha
from pitivi.utils.blurfill import sync_shift
from pitivi.utils.fades import EPSILON
from pitivi.utils.fades import Fades
from pitivi.utils.fades import fades_keyframes
from pitivi.utils.fades import get_keyframes
from pitivi.utils.fades import get_source_range
from pitivi.utils.fades import read_fades
from pitivi.utils.fades import set_keyframes
from pitivi.utils.motion import BASE_META
from pitivi.utils.motion import get_frame_size
from pitivi.utils.motion import sync_motion
from pitivi.utils.motion import uses_zoom_effect

DISSOLVE = "dissolve"
FADE_TO_BLACK = "fade-to-black"
FADE_TO_WHITE = "fade-to-white"
BLUR = "blur"
SOFT_WIPE = "soft-wipe"
PUSH = "push"

# The sides the second clip appears from, and the wipes doing it.
LEFT = "left"
RIGHT = "right"
TOP = "top"
BOTTOM = "bottom"
DIRECTIONS = (LEFT, RIGHT, TOP, BOTTOM)
WIPES = {LEFT: (GES.VideoStandardTransitionType.BAR_WIPE_LR, False),
         RIGHT: (GES.VideoStandardTransitionType.BAR_WIPE_LR, True),
         TOP: (GES.VideoStandardTransitionType.BAR_WIPE_TB, False),
         BOTTOM: (GES.VideoStandardTransitionType.BAR_WIPE_TB, True)}
# For a push, the wipe uncovers the side of the second clip which comes in
# first. The wipe applies to the image of the clip, before it is placed.
PUSH_WIPES = {LEFT: WIPES[RIGHT],
              RIGHT: WIPES[LEFT],
              TOP: WIPES[BOTTOM],
              BOTTOM: WIPES[TOP]}
# The transition of a push with an image, the wipes are drawn wrong.
PUSH_FADE = GES.VideoStandardTransitionType.FADE_IN
# How soft the edge of a soft wipe is.
SOFT_WIPE_BORDER = 20000

# For the second clip appearing from a side, the position property and how
# many frames the first clip moves at the end and the second one at the start.
PUSHES = {LEFT: ("posx", 1, -1),
          RIGHT: ("posx", -1, 1),
          TOP: ("posy", 1, -1),
          BOTTOM: ("posy", -1, 1)}
# The position of a source when not pushed, kept while its position is
# animated.
PUSH_BASE_META = BASE_META
# Where the second clip of a push comes from, when the push has no wipe
# telling it.
PUSH_DIRECTION_META = "spl::push-direction"

# The effect turning a clip white, marked with this metadata. It mixes the
# image with white by lowering the contrast and the saturation, and raising
# the brightness, which videobalance applies to the luma between 16 and 235.
WHITE_EFFECT_BIN_DESCRIPTION = "videobalance"
WHITE_EFFECT_META = "spl::fade-to-white"
WHITE_BRIGHTNESS = 219 / 255

MIN_DURATION = 3 * Gst.SECOND // 10
MAX_DURATION = 2 * Gst.SECOND
DEFAULT_DURATION = Gst.SECOND


class Contact(NamedTuple):
    """Two clips of a layer which meet, with the transition between them.

    Attributes:
        clip_a (GES.Clip): The first clip.
        clip_b (GES.Clip): The second clip.
        kind (Optional[str]): DISSOLVE, SOFT_WIPE, FADE_TO_BLACK,
            FADE_TO_WHITE or None.
        duration (int): The duration of the transition.
        direction (Optional[str]): The side the second clip appears from,
            for a wipe.
    """

    clip_a: GES.Clip
    clip_b: GES.Clip
    kind: Optional[str]
    duration: int
    direction: Optional[str] = None

    @property
    def position(self) -> int:
        """The time in the middle of the transition, or where the clips meet."""
        if self.kind in OVERLAPPING_KINDS:
            return self.clip_b.props.start + self.duration // 2
        return self.clip_b.props.start


# The kinds for which the clips overlap.
OVERLAPPING_KINDS = (DISSOLVE, SOFT_WIPE, PUSH)


def get_video_transition_of(clip: GES.TransitionClip) -> Optional[GES.VideoTransition]:
    """Returns the video transition of the transition clip, if any."""
    for element in clip.get_children(False):
        if isinstance(element, GES.VideoTransition):
            return element
    return None


def get_video_transition(clip_b: GES.Clip) -> Optional[GES.VideoTransition]:
    """Returns the video transition where the clip starts, if any."""
    layer = clip_b.get_layer()
    for clip in layer.get_clips() if layer else []:
        if isinstance(clip, GES.TransitionClip) and clip.props.start == clip_b.props.start:
            element = get_video_transition_of(clip)
            if element:
                return element
    return None


def covers_frame(clip: GES.Clip) -> bool:
    """Whether the video of the clip is as big as the frame, before placed."""
    if get_active_blur_fill(clip):
        # The effect makes the whole frame.
        return True
    source = clip.find_track_element(None, GES.VideoSource)
    if not source or not source.get_track():
        return False
    return get_image_size(clip) == get_frame_size(source)


def wipes_work(clip_a: GES.Clip, clip_b: GES.Clip) -> bool:
    """Whether the wipes of GES are drawn right between the clips.

    The wipes are drawn wrong when a clip is an image: parts of the frame
    are black and the edge is misplaced. They are also drawn small in a
    corner when neither video is as big as the frame.
    """
    for clip in (clip_a, clip_b):
        asset = clip.get_asset()
        if asset and asset.is_image():
            return False
    return covers_frame(clip_a) or covers_frame(clip_b)


def _get_push_wipe(clip_b: GES.Clip, direction: str):
    """Returns the wipe of a push, uncovering the second clip as it comes in.

    The wipe applies to the image of the second clip before it is placed,
    except when its blurred fill makes the frame already slid.
    """
    if get_active_blur_fill(clip_b):
        return WIPES[direction]
    return PUSH_WIPES[direction]


def _get_push_direction(clip_b: GES.Clip) -> Optional[str]:
    """Returns where the second clip of a push comes from.

    It is kept in the source of the clip, or else found from its animation.
    """
    source = clip_b.find_track_element(None, GES.VideoSource)
    if not source:
        return None
    direction = source.get_string(PUSH_DIRECTION_META)
    if direction in PUSHES:
        return direction
    start, unused_end = get_source_range(source)
    for direction, (property_name, unused_factor_a, factor_b) in PUSHES.items():
        control_source = _get_push_control_source(source, property_name)
        if not control_source:
            continue
        unused_res, base = source.get_int(PUSH_BASE_META % property_name)
        values = [value for timestamp, value in get_keyframes(control_source) if timestamp == start]
        if values and (values[0] - base) * factor_b > 0:
            return direction
    return None


def get_overlap_kind(clip_b: GES.Clip):
    """Returns the kind and direction of the transition where the clip starts."""
    element = get_video_transition(clip_b)
    if element:
        if element.get_transition_type() == PUSH_FADE:
            # A push where the second clip appears while coming in.
            return PUSH, _get_push_direction(clip_b) or RIGHT
        transition_type = element.get_transition_type()
        inverted = element.is_inverted()
        # A push has a hard edge.
        if not element.get_border() and transition_type != GES.VideoStandardTransitionType.CROSSFADE:
            direction = _get_push_direction(clip_b)
            if direction:
                return PUSH, direction
            wipes = PUSH_WIPES
            kind = PUSH
        else:
            wipes = WIPES
            kind = SOFT_WIPE
        for direction, wipe in wipes.items():
            if wipe == (transition_type, inverted):
                return kind, direction
    return DISSOLVE, None


def is_visual(clip: GES.Clip) -> bool:
    """Whether the clip is a video or an image, which can have transitions."""
    return isinstance(clip, GES.UriClip) and \
        bool(clip.props.supported_formats & GES.TrackType.VIDEO)


def _get_alpha_control_source(clip: GES.Clip, create: bool = False):
    source = clip.find_track_element(None, GES.VideoSource)
    if not source:
        return None, None
    binding = source.get_control_binding("alpha")
    if binding:
        return source, binding.props.control_source
    if not create:
        return source, None
    control_source = GstController.InterpolationControlSource()
    control_source.props.mode = GstController.InterpolationMode.LINEAR
    source.set_control_source(control_source, "alpha", "direct")
    effect = get_blur_fill(clip)
    if effect:
        # The effect making the blurred fill loses the alpha of the source.
        link_alpha(effect, source)
    return source, control_source


def get_image_fades(clip: GES.Clip) -> Optional[Fades]:
    """Returns the image fades of the clip, or None if edited freely."""
    unused_source, control_source = _get_alpha_control_source(clip)
    if not control_source:
        return Fades(1.0, 0, 0)
    keyframes = get_keyframes(control_source)
    if not keyframes:
        return Fades(1.0, 0, 0)
    return read_fades(keyframes)


def set_image_fades(clip: GES.Clip, fade_in: Optional[int] = None,
                    fade_out: Optional[int] = None) -> bool:
    """Changes the image fades of the clip, unless edited freely."""
    fades = get_image_fades(clip)
    if not fades:
        return False
    fades = Fades(fades.level if fades.level else 1.0,
                  fades.fade_in if fade_in is None else fade_in,
                  fades.fade_out if fade_out is None else fade_out)
    source, control_source = _get_alpha_control_source(clip, create=True)
    set_keyframes(control_source, fades_keyframes(fades, *get_source_range(source)))
    return True


def is_white_effect(effect: GES.TrackElement) -> bool:
    """Whether the effect is the one turning the clip white."""
    if not isinstance(effect, GES.BaseEffect):
        return False
    res, value = effect.get_boolean(WHITE_EFFECT_META)
    return bool(res and value)


def _get_white_effect(clip: GES.Clip) -> Optional[GES.BaseEffect]:
    for effect in clip.get_top_effects():
        if is_white_effect(effect):
            return effect
    return None


def get_white_fades(clip: GES.Clip) -> Fades:
    """Returns how long the clip turns from and to white, at its ends."""
    effect = _get_white_effect(clip)
    binding = effect.get_control_binding("saturation") if effect else None
    if not binding:
        return Fades(1.0, 0, 0)
    # The saturation goes from zero, white, to its original value.
    keyframes = [(timestamp, value * 2) for timestamp, value
                 in get_keyframes(binding.props.control_source)]
    return read_fades(keyframes) or Fades(1.0, 0, 0)


def set_white_fades(clip: GES.Clip, fade_in: Optional[int] = None,
                    fade_out: Optional[int] = None) -> None:
    """Changes how long the clip turns from and to white, at its ends."""
    fades = get_white_fades(clip)
    fades = Fades(1.0, fades.fade_in if fade_in is None else fade_in,
                  fades.fade_out if fade_out is None else fade_out)
    effect = _get_white_effect(clip)
    if not fades.fade_in and not fades.fade_out:
        if effect:
            clip.remove(effect)
        return

    if not effect:
        effect = GES.Effect.new(WHITE_EFFECT_BIN_DESCRIPTION)
        effect.set_boolean(WHITE_EFFECT_META, True)
        clip.add(effect)
    # The fades of the image, 1 being the original image and 0 white.
    keyframes = fades_keyframes(fades, *get_source_range(effect))
    # The "direct" bindings map 0 and 1 to the lowest and highest values:
    # the brightness goes from -1 to 1, the contrast and the saturation
    # from 0 to 2.
    for property_name, value_of in (
            ("brightness", lambda image: (1 + (1 - image) * WHITE_BRIGHTNESS) / 2),
            ("contrast", lambda image: image / 2),
            ("saturation", lambda image: image / 2)):
        binding = effect.get_control_binding(property_name)
        if binding:
            control_source = binding.props.control_source
        else:
            control_source = GstController.InterpolationControlSource()
            control_source.props.mode = GstController.InterpolationMode.LINEAR
            effect.set_control_source(control_source, property_name, "direct")
        set_keyframes(control_source, [(timestamp, value_of(image))
                                       for timestamp, image in keyframes])


BLUR_BACKGROUND_SIZE = 640
BLUR_MAX_SIGMA = 6.0
BLUR_EFFECT_META = "spl::fade-blur"


def _get_clip_media_size(clip: GES.Clip) -> Optional[Tuple[int, int]]:
    """Returns the natural dimensions of the clip media, if available."""
    asset = clip.get_asset()
    if asset:
        info = asset.get_info()
        if info:
            streams = info.get_video_streams()
            if streams:
                w, h = streams[0].get_width(), streams[0].get_height()
                if w > 0 and h > 0:
                    return w, h
    source = clip.find_track_element(None, GES.VideoSource)
    if source and source.get_track():
        return get_frame_size(source)
    return None


def get_blur_bin_description(clip: GES.Clip) -> str:
    """Returns the optimized bin description for the blur transition effect."""
    size = _get_clip_media_size(clip)
    if size:
        width, height = size
        max_dim = max(width, height)
        if max_dim > BLUR_BACKGROUND_SIZE:
            ratio = BLUR_BACKGROUND_SIZE / max_dim
            small_w = max(2, round(width * ratio / 2) * 2)
            small_h = max(2, round(height * ratio / 2) * 2)
            return (
                f"videoconvert ! videoscale ! "
                f"capsfilter caps=video/x-raw,width={small_w},height={small_h} ! "
                f"gaussianblur ! videoscale ! "
                f"capsfilter caps=video/x-raw,width={width},height={height} ! "
                f"videoconvert"
            )
    return "videoconvert ! gaussianblur ! videoconvert"


def is_blur_effect(effect: GES.TrackElement) -> bool:
    """Whether the effect is the one blurring the clip for a blur transition."""
    if not isinstance(effect, GES.BaseEffect):
        return False
    res, value = effect.get_boolean(BLUR_EFFECT_META)
    return bool(res and value)


def _get_blur_effect(clip: GES.Clip) -> Optional[GES.BaseEffect]:
    for effect in clip.get_top_effects():
        if is_blur_effect(effect):
            return effect
    return None


def get_blur_fades(clip: GES.Clip) -> Fades:
    """Returns how long the clip blurs and unblurs at its ends."""
    effect = _get_blur_effect(clip)
    binding = effect.get_control_binding("sigma") if effect else None
    if not binding:
        return Fades(0.0, 0, 0)
    keyframes = get_keyframes(binding.props.control_source)
    if not keyframes or len(keyframes) < 2:
        return Fades(0.0, 0, 0)

    fade_in = 0
    fade_out = 0
    start_time = keyframes[0][0]
    end_time = keyframes[-1][0]

    if keyframes[0][1] > EPSILON:
        for t, val in keyframes[1:]:
            if abs(val) < EPSILON:
                fade_in = t - start_time
                break

    if keyframes[-1][1] > EPSILON:
        for t, val in reversed(keyframes[:-1]):
            if abs(val) < EPSILON:
                fade_out = end_time - t
                break

    return Fades(BLUR_MAX_SIGMA, fade_in, fade_out)


def set_blur_fades(clip: GES.Clip, fade_in: Optional[int] = None,
                   fade_out: Optional[int] = None) -> None:
    """Changes how long the clip blurs and unblurs at its ends."""
    fades = get_blur_fades(clip)
    fades = Fades(BLUR_MAX_SIGMA,
                  fades.fade_in if fade_in is None else fade_in,
                  fades.fade_out if fade_out is None else fade_out)
    effect = _get_blur_effect(clip)
    if not fades.fade_in and not fades.fade_out:
        if effect:
            clip.remove(effect)
        return

    description = get_blur_bin_description(clip)
    if effect and effect.props.bin_description != description:
        clip.remove(effect)
        effect = None

    if not effect:
        effect = GES.Effect.new(description)
        effect.set_boolean(BLUR_EFFECT_META, True)
        clip.add(effect)

    binding = effect.get_control_binding("sigma")
    if binding:
        control_source = binding.props.control_source
    else:
        control_source = GstController.InterpolationControlSource()
        control_source.props.mode = GstController.InterpolationMode.LINEAR
        effect.set_control_source(control_source, "sigma", "direct-absolute")

    start, end = get_source_range(effect)
    keyframes = []
    if fades.fade_in:
        keyframes.append((start, BLUR_MAX_SIGMA))
        keyframes.append((start + fades.fade_in, 0.0))
    else:
        keyframes.append((start, 0.0))

    if fades.fade_out:
        keyframes.append((end - fades.fade_out, 0.0))
        keyframes.append((end, BLUR_MAX_SIGMA))
    else:
        keyframes.append((end, 0.0))

    set_keyframes(control_source, sorted(dict(keyframes).items()))


def get_contacts(layer: GES.Layer) -> List[Contact]:
    """Returns where the visual clips of the layer meet or overlap."""
    clips = sorted((clip for clip in layer.get_clips()
                    if not isinstance(clip, GES.TransitionClip)),
                   key=lambda clip: clip.props.start)
    contacts = []
    for clip_a, clip_b in zip(clips, clips[1:]):
        if not is_visual(clip_a) or not is_visual(clip_b):
            continue
        end_a = clip_a.props.start + clip_a.props.duration
        start_b = clip_b.props.start
        if clip_a.props.start < start_b < end_a:
            kind, direction = get_overlap_kind(clip_b)
            contacts.append(Contact(clip_a, clip_b, kind, end_a - start_b, direction))
        elif start_b == end_a:
            blur_a = get_blur_fades(clip_a)
            blur_b = get_blur_fades(clip_b)
            white_a = get_white_fades(clip_a)
            white_b = get_white_fades(clip_b)
            fades_a = get_image_fades(clip_a)
            fades_b = get_image_fades(clip_b)
            if blur_a.fade_out and blur_b.fade_in:
                contacts.append(Contact(clip_a, clip_b, BLUR,
                                        blur_a.fade_out + blur_b.fade_in))
            elif white_a.fade_out and white_b.fade_in:
                contacts.append(Contact(clip_a, clip_b, FADE_TO_WHITE,
                                        white_a.fade_out + white_b.fade_in))
            elif fades_a and fades_b and fades_a.fade_out and fades_b.fade_in:
                contacts.append(Contact(clip_a, clip_b, FADE_TO_BLACK,
                                        fades_a.fade_out + fades_b.fade_in))
            else:
                contacts.append(Contact(clip_a, clip_b, None, 0))
    return contacts


def get_max_duration(contact: Contact, kind: str) -> int:
    """Returns the longest transition of the kind the clips allow."""
    shortest = min(contact.clip_a.props.duration, contact.clip_b.props.duration)
    if contact.kind in OVERLAPPING_KINDS:
        # The clips overlap, they get back their length without it.
        shortest += contact.duration
    if kind in OVERLAPPING_KINDS:
        # The clips overlap at most half of their length, so a clip has
        # room for transitions at both ends.
        return min(MAX_DURATION, shortest // 2)
    # Each clip fades during half of the transition, at most half of it.
    return min(MAX_DURATION, shortest)


def _shift_following(contact: Contact, shift: int) -> None:
    """Moves the second clip and the following ones of the layer."""
    layer = contact.clip_b.get_layer()
    following = sorted((clip for clip in layer.get_clips()
                        if not isinstance(clip, GES.TransitionClip) and
                        clip != contact.clip_a and
                        clip.props.start >= contact.clip_b.props.start),
                       key=lambda clip: clip.props.start)
    if shift > 0:
        # Moving right, start with the last one so that none overlap.
        following.reverse()
    for clip in following:
        clip.set_start(clip.props.start + shift)


def apply_wipe(clip_a: GES.Clip, clip_b: GES.Clip, kind: str, direction: str) -> None:
    """Makes the transition where the clip starts a soft wipe or a push.

    GES creates the transition as a dissolve when the clips start
    overlapping, also when they stop overlapping for a moment.
    """
    element = get_video_transition(clip_b)
    if not element:
        return
    if kind == PUSH and not wipes_work(clip_a, clip_b):
        # Without the wipe, the second clip appears while coming in.
        transition_type, inverted = PUSH_FADE, False
    elif kind == PUSH:
        transition_type, inverted = _get_push_wipe(clip_b, direction)
    else:
        transition_type, inverted = WIPES[direction]
    border = SOFT_WIPE_BORDER if kind == SOFT_WIPE else 0
    if element.get_transition_type() != transition_type:
        element.set_transition_type(transition_type)
    if element.is_inverted() != inverted:
        element.set_inverted(inverted)
    if element.get_border() != border:
        element.set_border(border)


def sync_saved_types(timeline: GES.Timeline) -> None:
    """Gives the transition clips the type of their video transitions.

    The wipes and the pushes change the type of the video transition, and
    the undo restores it there, but the project saves the type of the clip.
    """
    for layer in timeline.get_layers():
        for clip in layer.get_clips():
            if not isinstance(clip, GES.TransitionClip):
                continue
            element = get_video_transition_of(clip)
            if element and clip.props.vtype != element.get_transition_type():
                # Setting it on the clip sets it on its elements again,
                # which resets their invert and border.
                inverted, border = element.is_inverted(), element.get_border()
                clip.props.vtype = element.get_transition_type()
                element.set_inverted(inverted)
                element.set_border(border)


def _get_push_control_source(source: GES.VideoSource, property_name: str):
    """Returns the control source animating the position for pushes, if any."""
    res, unused_base = source.get_int(PUSH_BASE_META % property_name)
    binding = source.get_control_binding(property_name)
    if res and binding:
        return binding.props.control_source
    return None


def sync_pushes(layer: GES.Layer) -> None:
    """Animates the positions of the clips of the layer for their motion.

    Called after the pushes, the zooms or the clips change, so that the
    clips move during the pushes where they are, and only there, and zoom
    over their whole duration.
    """
    pushes = [contact for contact in get_contacts(layer) if contact.kind == PUSH]
    for contact in pushes:
        # The wipe depends on the sizes and the blurred fills of the clips.
        apply_wipe(contact.clip_a, contact.clip_b, PUSH, contact.direction)
    for clip in layer.get_clips():
        source = clip.find_track_element(None, GES.VideoSource) if is_visual(clip) else None
        if not source or not source.get_track():
            continue
        width, height = get_frame_size(source)
        start, end = get_source_range(source)
        segments = {}
        for contact in pushes:
            property_name, factor_a, factor_b = PUSHES[contact.direction]
            size = width if property_name == "posx" else height
            if contact.clip_a == clip:
                segments.setdefault(property_name, []).append(
                    (end - contact.duration, 0, end, factor_a * size))
            if contact.clip_b == clip:
                segments.setdefault(property_name, []).append(
                    (start, factor_b * size, start + contact.duration, 0))
        effect = get_active_blur_fill(clip)
        if effect and uses_zoom_effect(source):
            # The effect zooming the frame made by the fill slides it.
            sync_shift(effect, {}, start, end)
        elif effect:
            # The effect makes the whole frame, it slides it.
            offsets = {}
            for property_name, prop_segments in segments.items():
                timestamps = {start, end}
                for segment_start, unused, segment_end, unused in prop_segments:
                    timestamps.update((segment_start, segment_end))
                offsets[property_name] = [
                    (timestamp, sum(_segment_offset(segment, timestamp) for segment in prop_segments))
                    for timestamp in sorted(timestamps)]
            sync_shift(effect, offsets, start, end)
            segments = {}
        sync_motion(source, segments)


def _segment_offset(segment, timestamp: int) -> float:
    segment_start, start_value, segment_end, end_value = segment
    if timestamp < segment_start or timestamp > segment_end:
        return 0
    if segment_end == segment_start:
        return end_value
    return start_value + (end_value - start_value) * (timestamp - segment_start) / (segment_end - segment_start)


def remove_transition(contact: Contact) -> Contact:
    """Removes the transition between the clips, returns the contact."""
    if contact.kind in OVERLAPPING_KINDS:
        # GES removes the transition when the clips stop overlapping.
        _shift_following(contact, contact.duration)
        if contact.kind == PUSH:
            sync_pushes(contact.clip_b.get_layer())
    elif contact.kind == FADE_TO_BLACK:
        set_image_fades(contact.clip_a, fade_out=0)
        set_image_fades(contact.clip_b, fade_in=0)
    elif contact.kind == FADE_TO_WHITE:
        set_white_fades(contact.clip_a, fade_out=0)
        set_white_fades(contact.clip_b, fade_in=0)
    elif contact.kind == BLUR:
        set_blur_fades(contact.clip_a, fade_out=0)
        set_blur_fades(contact.clip_b, fade_in=0)
    return Contact(contact.clip_a, contact.clip_b, None, 0)


def set_transition(contact: Contact, kind: str, duration: int,
                   direction: Optional[str] = None) -> Contact:
    """Replaces the transition between the clips, returns the contact."""
    contact = remove_transition(contact)
    duration = max(MIN_DURATION, min(duration, get_max_duration(contact, kind)))
    if kind in OVERLAPPING_KINDS:
        # GES creates the transition where the clips overlap.
        _shift_following(contact, -duration)
        if kind in (SOFT_WIPE, PUSH):
            direction = direction or RIGHT
            if kind == PUSH:
                source = contact.clip_b.find_track_element(None, GES.VideoSource)
                if source and source.get_string(PUSH_DIRECTION_META) != direction:
                    source.set_string(PUSH_DIRECTION_META, direction)
            apply_wipe(contact.clip_a, contact.clip_b, kind, direction)
            if kind == PUSH:
                sync_pushes(contact.clip_b.get_layer())
        else:
            direction = None
    elif kind == FADE_TO_BLACK:
        set_image_fades(contact.clip_a, fade_out=duration // 2)
        set_image_fades(contact.clip_b, fade_in=duration - duration // 2)
    elif kind == FADE_TO_WHITE:
        set_white_fades(contact.clip_a, fade_out=duration // 2)
        set_white_fades(contact.clip_b, fade_in=duration - duration // 2)
    elif kind == BLUR:
        set_blur_fades(contact.clip_a, fade_out=duration // 2)
        set_blur_fades(contact.clip_b, fade_in=duration - duration // 2)
    return Contact(contact.clip_a, contact.clip_b, kind, duration, direction)


def remove_transitions_of(clips) -> None:
    """Removes the transitions of clips about to be removed.

    Nothing moves: the overlapping transitions go away with the overlap and
    the fades of the other clips are removed. Call `sync_pushes` on the
    layers once the clips are removed.
    """
    clips = set(clips)
    for layer in {clip.get_layer() for clip in clips if clip.get_layer()}:
        for contact in get_contacts(layer):
            if contact.clip_a in clips or contact.clip_b in clips:
                remove_fades(contact.clip_a, contact.clip_b, contact.kind)


def remove_fades(clip_a: GES.Clip, clip_b: GES.Clip, kind: Optional[str]) -> None:
    """Removes the fades of a fade to black, white or blur between the clips."""
    if kind == FADE_TO_BLACK:
        set_image_fades(clip_a, fade_out=0)
        set_image_fades(clip_b, fade_in=0)
    elif kind == FADE_TO_WHITE:
        set_white_fades(clip_a, fade_out=0)
        set_white_fades(clip_b, fade_in=0)
    elif kind == BLUR:
        set_blur_fades(clip_a, fade_out=0)
        set_blur_fades(clip_b, fade_in=0)


def find_contact_for_transition(element: GES.TimelineElement) -> Optional[Contact]:
    """Returns the Contact corresponding to a TransitionClip or VideoTransition."""
    if isinstance(element, GES.TransitionClip):
        clip = element
    elif hasattr(element, "get_parent") and isinstance(element.get_parent(), GES.TransitionClip):
        clip = element.get_parent()
    else:
        return None

    layer = clip.get_layer()
    if not layer:
        return None

    for contact in get_contacts(layer):
        if contact.clip_b.props.start == clip.props.start:
            return contact

    return None


def are_in_contact(clip_a: GES.Clip, clip_b: GES.Clip) -> bool:
    """Whether the second clip starts where the first ends, in their layer."""
    layer = clip_a.get_layer()
    return layer is not None and layer == clip_b.get_layer() and \
        clip_b.props.start == clip_a.props.start + clip_a.props.duration
