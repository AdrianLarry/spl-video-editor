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
"""Formats of the video: horizontal, vertical or square.

The format is the size of the project. Changing it keeps the framing of
the clips: a clip fitting the frame fits the new frame, a clip filling
it fills the new frame showing the same part, and a clip placed by hand
keeps its size relative to the frame and its place.
"""
from typing import Dict
from typing import Optional
from typing import Tuple

from gi.repository import GES

from pitivi.clip_properties.overlay import is_overlay_clip
from pitivi.clip_properties.overlay import place_overlay
from pitivi.undo.base import UndoableAction
from pitivi.undo.timeline import CommitTimelineFinalizingAction
from pitivi.utils.blurfill import get_blur_fill
from pitivi.utils.blurfill import update_blur_fill
from pitivi.utils.motion import get_base_position
from pitivi.utils.motion import is_animated_by_user
from pitivi.utils.motion import set_base_position
from pitivi.utils.transitions import sync_pushes

HORIZONTAL = "horizontal"
VERTICAL = "vertical"
SQUARE = "square"

# The size of each format, for videos for social networks.
SIZES = {HORIZONTAL: (1920, 1080),
         VERTICAL: (1080, 1920),
         SQUARE: (1080, 1080)}

# How much a position can differ, because of the rounding.
TOLERANCE = 2

FIT = "fit"
FILL = "fill"
MANUAL = "manual"

POSITION_PROPERTIES = ("posx", "posy", "width", "height")


def get_format(width: int, height: int) -> Optional[str]:
    """Returns the format of the size, None if it has another shape."""
    for kind, (format_width, format_height) in SIZES.items():
        if width * format_height == height * format_width:
            return kind
    return None


def get_closest_format(width: int, height: int) -> str:
    """Returns the format closest to the shape of the size."""
    ratio = width / height
    if ratio > 1.2:
        return HORIZONTAL
    if ratio < 1 / 1.2:
        return VERTICAL
    return SQUARE


def get_fill_position(fit: Dict[str, int], width: int, height: int) -> Dict[str, int]:
    """Returns the position covering the frame, from the one fitting it."""
    scale = max(width / fit["width"], height / fit["height"])
    fill_width = round(fit["width"] * scale)
    fill_height = round(fit["height"] * scale)
    return {"posx": (width - fill_width) // 2,
            "posy": (height - fill_height) // 2,
            "width": fill_width,
            "height": fill_height}


def _close(position, other, properties=POSITION_PROPERTIES):
    return all(abs(position[prop] - other[prop]) <= TOLERANCE for prop in properties)


def get_framing(position: Dict[str, int], fit: Dict[str, int],
                width: int, height: int) -> Tuple[str, float, float]:
    """Returns how a clip is framed: FIT, FILL or MANUAL, with two values.

    For FILL, they are the horizontal and vertical place of the image,
    from 1 (its left or top edge is shown) to -1 (its right or bottom edge
    is shown), 0 being centered. For MANUAL, they are the size relative to
    the fitting size and nothing.
    """
    if _close(position, fit):
        return FIT, 0, 0
    fill = get_fill_position(fit, width, height)
    if _close(position, fill, ("width", "height")):
        pan = []
        for prop in ("posx", "posy"):
            # The centered position, zero or negative.
            centered = fill[prop]
            pan.append(max(-1, min(1, 1 - position[prop] / centered)) if centered else 0)
        return FILL, pan[0], pan[1]
    return MANUAL, position["width"] / fit["width"], 0


def get_framed_position(framing: Tuple[str, float, float], old_position: Dict[str, int],
                        old_size: Tuple[int, int], fit: Dict[str, int],
                        width: int, height: int) -> Dict[str, int]:
    """Returns the position framing a clip in the new frame as in the old one."""
    kind, first, second = framing
    if kind == FIT:
        return dict(fit)
    if kind == FILL:
        fill = get_fill_position(fit, width, height)
        fill["posx"] = round(fill["posx"] * (1 - first))
        fill["posy"] = round(fill["posy"] * (1 - second))
        return fill
    # The same size relative to the fitting size, the same center.
    clip_width = round(fit["width"] * first)
    clip_height = round(fit["height"] * first)
    old_width, old_height = old_size
    center_x = (old_position["posx"] + old_position["width"] / 2) / old_width
    center_y = (old_position["posy"] + old_position["height"] / 2) / old_height
    return {"posx": round(center_x * width - clip_width / 2),
            "posy": round(center_y * height - clip_height / 2),
            "width": clip_width,
            "height": clip_height}


def _get_position(source):
    """Returns the position of the source, None if animated by the user."""
    if is_animated_by_user(source):
        return None
    # When moving, the position is the one around which it moves.
    return get_base_position(source)


def _set_position(source, position):
    set_base_position(source, position)


class FormatChangedAction(UndoableAction):
    """The size of the project changed."""

    def __init__(self, project, old_size, new_size):
        UndoableAction.__init__(self)
        self.project = project
        self.old_size = old_size
        self.new_size = new_size

    def __set_size(self, size):
        width, height = size
        self.project.set_video_properties(width, height, self.project.videorate)

    def do(self):
        self.__set_size(self.new_size)

    def undo(self):
        self.__set_size(self.old_size)


def set_format(app, project, kind: str) -> None:
    """Changes the format of the project, keeping the framing of the clips."""
    old_size = (project.videowidth, project.videoheight)
    new_size = SIZES[kind]
    if old_size == new_size:
        return

    sources = []
    blur_fill_clips = []
    overlay_clips = []
    for layer in project.ges_timeline.get_layers():
        for clip in layer.get_clips():
            if isinstance(clip, GES.TransitionClip):
                continue
            if is_overlay_clip(clip):
                # Its shape is placed in fractions of the frame.
                overlay_clips.append(clip)
                continue
            if get_blur_fill(clip):
                # The blurred fill covers the new frame.
                blur_fill_clips.append(clip)
                continue
            for source in clip.find_track_elements(None, GES.TrackType.VIDEO, GES.VideoSource):
                ui = getattr(source, "ui", None)
                position = _get_position(source)
                if not ui or position is None:
                    continue
                framing = get_framing(position, ui.default_position, *old_size)
                sources.append((source, position, framing))

    with app.action_log.started("format",
                                finalizing_action=CommitTimelineFinalizingAction(project.pipeline),
                                toplevel=True):
        action = FormatChangedAction(project, old_size, new_size)
        action.do()
        app.action_log.push(action)
        for source, position, framing in sources:
            new_position = get_framed_position(framing, position, old_size,
                                               source.ui.default_position, *new_size)
            _set_position(source, new_position)
        for clip in blur_fill_clips:
            update_blur_fill(clip)
        for clip in overlay_clips:
            place_overlay(clip)
        for layer in project.ges_timeline.get_layers():
            sync_pushes(layer)
