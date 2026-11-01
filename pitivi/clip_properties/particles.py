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
"""Model and helpers for particle effect overlays on independent timeline layers."""
from gettext import gettext as _
from typing import Optional
from typing import Tuple

import cairo
from gi.repository import GES

from pitivi.utils.motion import get_frame_size
from pitivi.utils.particles import render_particles

PARTICLES_META = "spl-particles"
PARTICLES_BIN_DESCRIPTION = "videoconvert ! video/x-raw,format=BGRA ! splparticles name=spl-particles ! videoconvert"

PARTICLE_LABELS = {
    "snow": _("Snow"),
    "confetti": _("Confetti"),
    "sparkles": _("Sparkles"),
    "smoke": _("Smoke"),
}


def is_particle_clip(clip: Optional[GES.Clip]) -> bool:
    """Returns whether the clip is an overlay running a particle effect."""
    if not clip or not isinstance(clip, GES.Clip):
        return False
    if clip.get_string(PARTICLES_META):
        return True
    return get_particle_effect(clip) is not None


def get_particle_effect(clip: Optional[GES.Clip]) -> Optional[GES.Effect]:
    """Returns the effect rendering particles on the clip, if present."""
    if not clip:
        return None
    for effect in clip.get_top_effects():
        if isinstance(effect, GES.Effect) and "splparticles" in effect.props.bin_description:
            return effect
    return None


def get_particle_effect_name(clip: GES.Clip) -> str:
    """Returns the name of the particle effect ("snow", "confetti", etc.)."""
    effect = get_particle_effect(clip)
    if effect:
        try:
            return effect.get_child_property("effect")[1]
        except Exception:
            pass
    return clip.get_string(PARTICLES_META) or "snow"


def create_particle_clip(duration: int) -> GES.TestClip:
    """Returns a new transparent clip for an independent particle layer."""
    clip = GES.TestClip.new()
    clip.set_duration(duration)
    clip.set_supported_formats(GES.TrackType.VIDEO)
    clip.set_vpattern(GES.VideoTestPattern.SOLID_COLOR)
    return clip


def setup_particle_overlay(clip: GES.TestClip, effect_name: str,
                           frame_size: Tuple[int, int]) -> GES.Effect:
    """Sets up the clip as a transparent layer running the specified particle effect."""
    clip.set_string(PARTICLES_META, effect_name)
    source = clip.find_track_element(None, GES.VideoTestSource)
    if source:
        # Transparent background, only particles are seen.
        source.set_child_property("foreground-color", 0)
        source.set_child_property("posx", 0)
        source.set_child_property("posy", 0)
        source.set_child_property("width", frame_size[0])
        source.set_child_property("height", frame_size[1])

    effect = GES.Effect.new(PARTICLES_BIN_DESCRIPTION)
    clip.add(effect)
    effect.set_child_property("effect", effect_name)
    return effect


def place_particle_overlay(clip: GES.Clip) -> None:
    """Ensures the particle layer covers the full frame of the project."""
    source = clip.find_track_element(None, GES.VideoTestSource)
    if not source or not source.get_track():
        return
    frame_size = get_frame_size(source)
    for prop, val in zip(("posx", "posy", "width", "height"),
                         (0, 0, frame_size[0], frame_size[1])):
        if source.get_child_property(prop)[1] != val:
            source.set_child_property(prop, val)


def draw_particle_thumbnail(clip: GES.Clip, size: int) -> cairo.ImageSurface:
    """Returns a square thumbnail preview of the particle effect on a dark background."""
    effect_name = get_particle_effect_name(clip)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    # Dark modern background to make particles pop in the timeline
    cr.set_source_rgb(0.14, 0.15, 0.18)
    cr.paint()
    render_particles(cr, effect_name, 1.2, size, size, amount=1.2, speed=1.0, size=1.3, opacity=0.9)
    surface.flush()
    return surface
