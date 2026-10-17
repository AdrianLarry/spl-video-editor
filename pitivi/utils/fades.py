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
"""Fades of the sources, stored as keyframes of their control sources.

A source with fades has a control source going from zero at its start up to
a level, staying at that level and going back to zero at its end. The
keyframes timestamps are in the internal time of the source, so the start
is its in-point.
"""
from typing import Dict
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Tuple

from gi.repository import GES

# Values closer than this are considered equal.
EPSILON = 1e-6

Keyframes = List[Tuple[int, float]]


class Fades(NamedTuple):
    """A level which rises from zero and falls back to zero.

    Attributes:
        level (float): The value of the control source between the fades.
        fade_in (int): The duration of the rise from zero, in nanoseconds.
        fade_out (int): The duration of the fall to zero, in nanoseconds.
    """

    level: float
    fade_in: int
    fade_out: int


def fades_keyframes(fades: Fades, start: int, end: int) -> Keyframes:
    """Returns the keyframes describing the fades between start and end.

    The fades are shortened if they do not fit.
    """
    duration = end - start
    fade_in = max(0, min(fades.fade_in, duration))
    fade_out = max(0, min(fades.fade_out, duration - fade_in))

    keyframes = []
    if fade_in:
        keyframes.append((start, 0.0))
    keyframes.append((start + fade_in, fades.level))
    keyframes.append((end - fade_out, fades.level))
    if fade_out:
        keyframes.append((end, 0.0))
    # Without fades the level is constant and the duplicates are dropped.
    return sorted(dict(keyframes).items())


def read_fades(keyframes: Keyframes) -> Optional[Fades]:
    """Returns the fades described by the keyframes, if any.

    The first and last keyframes are taken as the ends of the fades, so
    the fades are still found when the keyframes go beyond the source.

    Args:
        keyframes: The timestamps and values of the control source,
            sorted by timestamp.

    Returns:
        The fades, or None if the keyframes have been edited freely.
    """
    if len(keyframes) < 2:
        return None

    values = [value for unused_timestamp, value in keyframes]
    first, last = 0, len(keyframes) - 1
    if values[first] < EPSILON:
        first = 1
    if values[last] < EPSILON and last > first:
        last -= 1
    plateau = values[first:last + 1]
    if not plateau or any(abs(value - plateau[0]) > EPSILON for value in plateau):
        return None

    if plateau[0] < EPSILON:
        # Zero all along.
        return Fades(0.0, 0, 0)

    fade_in = keyframes[first][0] - keyframes[0][0]
    fade_out = keyframes[-1][0] - keyframes[last][0]
    return Fades(plateau[0], fade_in, fade_out)


def get_fades_property(source: GES.TrackElement) -> Optional[str]:
    """Returns the name of the property faded in and out on the source."""
    if isinstance(source, GES.VideoSource):
        return "alpha"
    if isinstance(source, GES.AudioSource):
        return "volume"
    return None


def get_keyframes(control_source) -> Keyframes:
    """Returns the timestamps and values of the control source."""
    return [(keyframe.timestamp, keyframe.value) for keyframe in control_source.get_all()]


def set_keyframes(control_source, keyframes: Keyframes) -> None:
    """Replaces the keyframes of the control source.

    The keyframes are removed and set one by one, so that the undo system
    records the changes.
    """
    wanted = dict(keyframes)
    current = dict(get_keyframes(control_source))
    # The new keyframes are set first, so the control source never gets
    # empty for whoever reads it meanwhile.
    for timestamp, value in wanted.items():
        if timestamp not in current or abs(current[timestamp] - value) > EPSILON:
            control_source.set(timestamp, value)
    for timestamp in current:
        if timestamp not in wanted:
            control_source.unset(timestamp)


def get_source_range(source: GES.TrackElement) -> Tuple[int, int]:
    """Returns the internal times where the source starts and ends."""
    start = source.props.in_point
    return start, start + source.props.duration


class FadesAnchor:
    """Keeps the fades at the ends of the sources while they are trimmed.

    When a source is trimmed, GES shortens its control sources to the new
    range, so a fade at a trimmed end is lost. This remembers the fades
    of the sources in the timeline and puts them back at the new ends.

    Sources with keyframes edited freely are left alone.
    """

    def __init__(self, ges_timeline: GES.Timeline):
        self._fades: Dict[GES.TrackElement, Fades] = {}
        for layer in ges_timeline.get_layers():
            for clip in layer.get_clips():
                for source in clip.get_children(False):
                    self.__remember(source)

    def __remember(self, source: GES.TrackElement) -> None:
        control_source = self.__get_control_source(source)
        if not control_source:
            return
        fades = read_fades(get_keyframes(control_source))
        if fades and (fades.fade_in or fades.fade_out):
            self._fades[source] = fades

    @staticmethod
    def __get_control_source(source: GES.TrackElement):
        property_name = get_fades_property(source)
        if not property_name:
            return None
        binding = source.get_control_binding(property_name)
        return binding.props.control_source if binding else None

    def apply(self) -> None:
        """Puts the fades of the trimmed sources at their new ends."""
        for source, fades in self._fades.items():
            control_source = self.__get_control_source(source)
            if control_source and source.get_parent():
                set_keyframes(control_source, fades_keyframes(fades, *get_source_range(source)))
