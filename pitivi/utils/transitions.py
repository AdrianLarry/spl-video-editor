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
"""
from typing import List
from typing import NamedTuple
from typing import Optional

from gi.repository import GES
from gi.repository import Gst
from gi.repository import GstController

from pitivi.utils.fades import Fades
from pitivi.utils.fades import fades_keyframes
from pitivi.utils.fades import get_keyframes
from pitivi.utils.fades import get_source_range
from pitivi.utils.fades import read_fades
from pitivi.utils.fades import set_keyframes

DISSOLVE = "dissolve"
FADE_TO_BLACK = "fade-to-black"

MIN_DURATION = 3 * Gst.SECOND // 10
MAX_DURATION = 2 * Gst.SECOND
DEFAULT_DURATION = Gst.SECOND


class Contact(NamedTuple):
    """Two clips of a layer which meet, with the transition between them.

    Attributes:
        clip_a (GES.Clip): The first clip.
        clip_b (GES.Clip): The second clip.
        kind (Optional[str]): DISSOLVE, FADE_TO_BLACK or None.
        duration (int): The duration of the transition.
    """

    clip_a: GES.Clip
    clip_b: GES.Clip
    kind: Optional[str]
    duration: int

    @property
    def position(self) -> int:
        """The time in the middle of the transition, or where the clips meet."""
        if self.kind == DISSOLVE:
            return self.clip_b.props.start + self.duration // 2
        return self.clip_b.props.start


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
            contacts.append(Contact(clip_a, clip_b, DISSOLVE, end_a - start_b))
        elif start_b == end_a:
            fades_a = get_image_fades(clip_a)
            fades_b = get_image_fades(clip_b)
            if fades_a and fades_b and fades_a.fade_out and fades_b.fade_in:
                contacts.append(Contact(clip_a, clip_b, FADE_TO_BLACK,
                                        fades_a.fade_out + fades_b.fade_in))
            else:
                contacts.append(Contact(clip_a, clip_b, None, 0))
    return contacts


def get_max_duration(contact: Contact) -> int:
    """Returns the longest transition the clips allow."""
    # Half of each clip, so a clip has room for transitions at both ends.
    longest = min(contact.clip_a.props.duration, contact.clip_b.props.duration)
    if contact.kind == DISSOLVE:
        # The clips overlap, they get back their length without it.
        longest += contact.duration
    return min(MAX_DURATION, longest // 2)


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


def remove_transition(contact: Contact) -> Contact:
    """Removes the transition between the clips, returns the contact."""
    if contact.kind == DISSOLVE:
        # GES removes the transition when the clips stop overlapping.
        _shift_following(contact, contact.duration)
    elif contact.kind == FADE_TO_BLACK:
        set_image_fades(contact.clip_a, fade_out=0)
        set_image_fades(contact.clip_b, fade_in=0)
    return Contact(contact.clip_a, contact.clip_b, None, 0)


def set_transition(contact: Contact, kind: str, duration: int) -> Contact:
    """Replaces the transition between the clips, returns the contact."""
    contact = remove_transition(contact)
    duration = max(MIN_DURATION, min(duration, get_max_duration(contact)))
    if kind == DISSOLVE:
        # GES creates the transition where the clips overlap.
        _shift_following(contact, -duration)
    elif kind == FADE_TO_BLACK:
        set_image_fades(contact.clip_a, fade_out=duration // 2)
        set_image_fades(contact.clip_b, fade_in=duration - duration // 2)
    return Contact(contact.clip_a, contact.clip_b, kind, duration)
