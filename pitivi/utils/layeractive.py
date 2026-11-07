# -*- coding: utf-8 -*-
# Pitivi video editor
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
"""Keeps the effects of hidden tracks hidden too.

GES (1.24) does not apply the layer state to an effect added to a clip of
a layer deactivated for the track: the effect stays active over a source
which is not, and NLE fails with "Not enough sinkpads to link all objects
to the operation ! 1 / 0", the fatal backend error. It happens loading a
project with a hidden track, and adding a blurred fill, a transition or
an effect to a clip of a hidden track.

Deactivating the layer again does nothing when it is already inactive, so
it is activated and deactivated again for the track, which applies its
state to all the elements. The layer state is not in the undo history.
"""
from gi.repository import GES


def refresh_layer(layer: GES.Layer, track: GES.Track) -> None:
    """Applies again the inactive state of the layer to its elements."""
    if layer.get_active_for_track(track):
        return
    layer.set_active_for_tracks(True, [track])
    layer.set_active_for_tracks(False, [track])


def refresh_timeline(ges_timeline: GES.Timeline) -> None:
    """Applies the state of the inactive layers to all their elements."""
    for track in ges_timeline.get_tracks():
        for layer in ges_timeline.get_layers():
            refresh_layer(layer, track)


def _track_element_added_cb(track: GES.Track, element: GES.TrackElement) -> None:
    if not isinstance(element, GES.BaseEffect):
        return
    clip = element.get_parent()
    layer = clip.get_layer() if isinstance(clip, GES.Clip) else None
    if layer:
        refresh_layer(layer, track)


def _watch_track(track: GES.Track) -> None:
    track.connect("track-element-added", _track_element_added_cb)


def _track_added_cb(unused_timeline: GES.Timeline, track: GES.Track) -> None:
    _watch_track(track)


def watch_timeline(ges_timeline: GES.Timeline) -> None:
    """Fixes the effects of hidden tracks now and when added later."""
    for track in ges_timeline.get_tracks():
        _watch_track(track)
    ges_timeline.connect("track-added", _track_added_cb)
    refresh_timeline(ges_timeline)
