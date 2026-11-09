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
"""The saved project made smaller, for preparing the preview faster.

Rendering the timeline at half its size takes about 60% of the time. The
size of the frame is in the restriction caps of the video track, but some
values are kept in pixels of the frame: where the clips are and their
animations, the foreground of the blurred fill, the slide of the pushes,
the sizes written in the bin descriptions of some
effects. They are all scaled here, in the text of the saved project, so
the editor and the export never see it.
"""
import re
import xml.etree.ElementTree as ET

# Child properties in pixels of the frame, by their qualified name.
_PIXEL_PROPERTIES = (
    "GstFramePositioner::posx", "GstFramePositioner::posy",
    "GstFramePositioner::width", "GstFramePositioner::height",
    "GstFramePositioner::fposx", "GstFramePositioner::fposy",
    "GstFramePositioner::fwidth", "GstFramePositioner::fheight",
    "pitivi+utils+kenburns+ZoomFilter::rect-x", "pitivi+utils+kenburns+ZoomFilter::rect-y",
    "pitivi+utils+kenburns+ZoomFilter::rect-width", "pitivi+utils+kenburns+ZoomFilter::rect-height",
    "pitivi+utils+kenburns+ZoomFilter::offset-x", "pitivi+utils+kenburns+ZoomFilter::offset-y",
    "SPLShapeFilter::frame-width", "SPLShapeFilter::frame-height",
)
# The same in the keyframes, named without the class.
_PIXEL_BINDINGS = ("posx", "posy", "width", "height", "fposx", "fposy", "fwidth", "fheight",
                   "rect-x", "rect-y", "rect-width", "rect-height", "offset-x", "offset-y")
# Element properties written in the bin descriptions of the effects.
_DESCRIPTION_PROPERTIES = ("rect-x", "rect-y", "rect-width", "rect-height", "sink_1::xpos", "sink_1::ypos")


def can_scale(text: str) -> bool:
    """Whether the preview of the saved project can be made smaller.

    The automatic zoom of a video, not of a photo, does not keep its
    framing when made smaller yet. The titles scale their font alone, with
    the frame.
    """
    root = ET.fromstring(text)
    images = set()
    for asset in root.iterfind("project/ressources/asset"):
        duration = re.search(r"duration=\(guint64\)(\d+)", asset.get("properties", ""))
        # The photos last forever.
        if duration and int(duration.group(1)) >= 2 ** 63:
            images.add(asset.get("id"))
    for clip in root.iterfind("project/timeline/layer/clip"):
        zoom = any("name=spl-zoom " in effect.get("asset-id", "") for effect in clip.iterfind("effect"))
        if zoom and clip.get("asset-id") not in images:
            return False
    return True


def _number(value: str, factor: float, integer: bool) -> str:
    scaled = float(value) * factor
    if integer:
        return str(int(round(scaled)))
    return repr(scaled)


def _scale_typed(match, factor):
    name, kind, value = match.group(1), match.group(2), match.group(3)
    integer = kind in ("int", "uint", "gint", "guint")
    return "%s=(%s)%s" % (name, kind, _number(value, factor, integer))


def scale_xges(text: str, width: int, height: int, factor: float) -> str:
    """Returns the saved project with a frame of width and height made smaller.

    Args:
        text: The project as saved by GES.
        width: The width of the frame of the project.
        height: The height of the frame of the project.
        factor: How much smaller, for example 0.5.
    """
    if factor == 1:
        return text
    new_width = max(2, int(round(width * factor / 2)) * 2)
    new_height = max(2, int(round(height * factor / 2)) * 2)
    exact = (new_width / width + new_height / height) / 2

    # The frame of the video track.
    text = re.sub(r"(restriction-caps=\(string\)&quot;video/x-raw[^&]*?)width\\?=\\?\(int\\?\)%d"
                  % width, lambda m: m.group(1) + "width\\=\\(int\\)%d" % new_width, text)
    text = re.sub(r"(restriction-caps=\(string\)&quot;video/x-raw[^&]*?)height\\?=\\?\(int\\?\)%d"
                  % height, lambda m: m.group(1) + "height\\=\\(int\\)%d" % new_height, text)

    # Child properties in pixels.
    names = "|".join(re.escape(name) for name in _PIXEL_PROPERTIES)
    text = re.sub(r"\b(%s)=\((\w+)\)(-?[0-9.eE+-]+)" % names,
                  lambda m: _scale_typed(m, exact), text)

    # The keyframes of those, values after the colons.
    def binding(match):
        values = re.sub(r"(\d+):(-?[0-9.eE+-]+)",
                        lambda v: "%s:%s" % (v.group(1), _number(v.group(2), exact, False)),
                        match.group(2))
        return match.group(1) + values + match.group(3)
    for name in _PIXEL_BINDINGS:
        text = re.sub(r"(<binding type='direct-absolute'[^>]*property='%s'[^>]*values\s*=\s*')([^']*)(')"
                      % re.escape(name), binding, text)

    # The base of the pushes, kept in the metas of the clips.
    text = re.sub(r"(spl::push-base-(?:posx|posy|width|height))=\((\w+)\)(-?[0-9.eE+-]+)",
                  lambda m: _scale_typed(m, exact), text)

    # Sizes in the bin descriptions of the effects, in their asset ids.
    def description(match):
        value = match.group(0)
        value = value.replace("width=%d,height=%d" % (width, height),
                              "width=%d,height=%d" % (new_width, new_height))
        for name in _DESCRIPTION_PROPERTIES:
            value = re.sub(r"(\b%s=)(-?[0-9.]+)" % re.escape(name),
                           lambda m: m.group(1) + _number(m.group(2), exact, "." not in m.group(2)), value)
        return value
    text = re.sub(r"asset-id='[^']*'", description, text)
    return text
