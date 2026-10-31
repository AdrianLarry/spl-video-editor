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
"""The overlays: shapes drawn over the video, with their own duration.

An overlay is a clip of a transparent color, with an effect drawing the
shape. It goes in a layer above the video, as the texts. The clip is
placed where the shape is drawn, so that only that part is mixed with the
video.
"""
from typing import Dict
from typing import Optional
from typing import Tuple

import cairo
from gi.repository import GES

from pitivi.utils.motion import get_frame_size
from pitivi.utils.shapefilter import ELEMENT_NAME
from pitivi.utils.shapefilter import render_shape
from pitivi.utils.shapefilter import shape_box
from pitivi.utils.shapes import BOX
from pitivi.utils.shapes import SHAPES

# Set on the clips of the overlays, the name of their first shape.
OVERLAY_META = "spl::overlay"
SHAPE_BIN_DESCRIPTION = ("videoconvert ! video/x-raw,format=BGRA ! %s name=spl-shape ! videoconvert"
                         % ELEMENT_NAME)

GEOMETRY_PROPS = ("x1", "y1", "x2", "y2")
STYLE_PROPS = ("color", "line-width", "corner-radius")


def is_overlay_clip(clip: Optional[GES.Clip]) -> bool:
    """Whether the clip is an overlay."""
    return isinstance(clip, GES.TestClip) and bool(clip.get_string(OVERLAY_META))


def get_shape_effect(clip: GES.Clip) -> Optional[GES.Effect]:
    """Returns the effect drawing the shape of the overlay."""
    for effect in clip.get_top_effects():
        if effect.props.bin_description == SHAPE_BIN_DESCRIPTION:
            return effect
    return None


def get_shape_name(clip: GES.Clip) -> str:
    """Returns the name of the shape drawn by the overlay."""
    # The metadata of the clip are not undone, the property is.
    effect = get_shape_effect(clip)
    if effect:
        return effect.get_child_property("shape")[1]
    return clip.get_string(OVERLAY_META) or ""


def default_geometry(shape_name: str, frame_size: Tuple[int, int]) -> Dict[str, float]:
    """Returns where a new shape goes, as fractions of the frame.

    A box is a square in the middle, an arrow points at the middle.
    """
    width, height = frame_size
    side = min(width, height) * 0.4
    if SHAPES[shape_name].kind == BOX:
        return {"x1": (width - side) / 2 / width, "y1": (height - side) / 2 / height,
                "x2": (width + side) / 2 / width, "y2": (height + side) / 2 / height}
    return {"x1": (width / 2 - side) / width, "y1": (height / 2 + side * 0.7) / height,
            "x2": (width / 2 - side * 0.1) / width, "y2": (height / 2 + side * 0.1) / height}


def create_overlay_clip(duration: int) -> GES.TestClip:
    """Returns a new clip for an overlay, to be set up once in a layer."""
    clip = GES.TestClip.new()
    clip.set_duration(duration)
    clip.set_supported_formats(GES.TrackType.VIDEO)
    clip.set_vpattern(GES.VideoTestPattern.SOLID_COLOR)
    return clip


def setup_overlay(clip: GES.TestClip, shape_name: str, frame_size: Tuple[int, int]) -> GES.Effect:
    """Makes the clip, in a layer, draw the shape."""
    clip.set_string(OVERLAY_META, shape_name)
    source = clip.find_track_element(None, GES.VideoTestSource)
    # Transparent, the shape alone is seen.
    source.set_child_property("foreground-color", 0)
    effect = GES.Effect.new(SHAPE_BIN_DESCRIPTION)
    clip.add(effect)
    effect.set_child_property("shape", shape_name)
    for prop, value in default_geometry(shape_name, frame_size).items():
        effect.set_child_property(prop, value)
    place_overlay(clip)
    return effect


def place_overlay(clip: GES.Clip) -> None:
    """Places the clip where its shape is drawn, in the frame of the project."""
    effect = get_shape_effect(clip)
    source = clip.find_track_element(None, GES.VideoTestSource)
    if not effect or not source or not source.get_track():
        return
    frame_size = get_frame_size(source)
    for prop, value in zip(("frame-width", "frame-height"), frame_size):
        if effect.get_child_property(prop)[1] != value:
            effect.set_child_property(prop, value)
    box = shape_box(get_values(clip), frame_size)
    for prop, value in zip(("posx", "posy", "width", "height"), box):
        if source.get_child_property(prop)[1] != value:
            source.set_child_property(prop, value)


def restore_overlays(timeline: GES.Timeline) -> None:
    """Places the overlays of a project, saved before being placed."""
    for layer in timeline.get_layers():
        for clip in layer.get_clips():
            if is_overlay_clip(clip):
                place_overlay(clip)


def get_values(clip: GES.Clip) -> Dict[str, object]:
    """Returns the properties of the element drawing the shape."""
    effect = get_shape_effect(clip)
    values = {"shape": get_shape_name(clip)}
    if effect:
        for prop in GEOMETRY_PROPS + STYLE_PROPS:
            values[prop] = effect.get_child_property(prop)[1]
    return values


def set_values(clip: GES.Clip, values: Dict[str, object]) -> None:
    """Changes the properties of the element drawing the shape."""
    effect = get_shape_effect(clip)
    if not effect:
        return
    for prop, value in values.items():
        if prop != "shape" and effect.get_child_property(prop)[1] != value:
            effect.set_child_property(prop, value)
    place_overlay(clip)


def draw_thumbnail(clip: GES.Clip, size: int) -> cairo.ImageSurface:
    """Returns a square picture of the shape, on a dark background."""
    values = get_values(clip)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    cr.set_source_rgb(0.16, 0.16, 0.18)
    cr.paint()
    if len(values) > 1:
        # The shape filling the picture, thick enough to be seen.
        values = dict(values)
        kind = SHAPES[values["shape"]].kind if values["shape"] in SHAPES else BOX
        values.update({"x1": 0.15, "y1": 0.2, "x2": 0.85, "y2": 0.8} if kind == BOX else
                      {"x1": 0.15, "y1": 0.8, "x2": 0.8, "y2": 0.25})
        values["line-width"] = max(values["line-width"], 90.0)
        values["corner-radius"] = min(values["corner-radius"], 200.0)
        stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, size)
        pixels = render_shape(values, size, size, stride)
        # Back to colors multiplied by the alpha, as cairo uses them.
        rows = pixels[:, :size * 4].reshape(size, size, 4).astype("uint16")
        rows[:, :, :3] = rows[:, :, :3] * rows[:, :, 3:4] // 255
        shape = cairo.ImageSurface.create_for_data(
            bytearray(rows.astype("uint8").tobytes()), cairo.FORMAT_ARGB32, size, size, size * 4)
        cr.set_source_surface(shape, 0, 0)
        cr.paint()
    surface.flush()
    return surface
