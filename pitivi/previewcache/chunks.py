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
"""The pieces of the prepared preview and what each one shows.

A piece is named by a hash of everything in the saved project which can
change its frames and its sound: the tracks, the layers, and the clips
under it with their effects and keyframes. Editing a clip makes new keys
only for the pieces under it, the others stay prepared.
"""
import hashlib
import os
import re
import xml.etree.ElementTree as ET
from typing import Dict
from typing import List
from typing import NamedTuple
from typing import Optional

from gi.repository import Gst

CHUNK_DURATION = 2 * Gst.SECOND
# Changed when the way of rendering changes, it makes all the keys new.
VERSION = "1"

# Names given when loading, and ids given when saving: they change while
# the clips stay the same.
_NAMES = re.compile(r"name=\(string\)[^,;]*[,;]?")


class Chunk(NamedTuple):
    start: int
    end: int
    key: str


def _clean(text: str) -> str:
    return _NAMES.sub("", text)


def _element_text(element: ET.Element, skip=("id",)) -> str:
    """Serializes the element without the attributes which change alone."""
    copy = ET.Element(element.tag, {key: _clean(value) for key, value in element.attrib.items()
                                    if key not in skip})
    copy.extend(element)
    return _clean(ET.tostring(copy, encoding="unicode"))


def _asset_text(asset: ET.Element) -> str:
    uri = asset.get("id", "")
    text = "%s|%s" % (uri, asset.get("proxy-id", ""))
    if uri.startswith("file://"):
        try:
            stat = os.stat(Gst.uri_get_location(uri))
            text += "|%d|%d" % (stat.st_size, stat.st_mtime_ns)
        except (OSError, TypeError):
            pass
    return text


def compute_chunks(xges: str, size: str) -> List[Chunk]:
    """Returns the pieces of the timeline of the saved project.

    Args:
        xges: The project, as saved by GES.
        size: The size of the rendered frames, part of the keys.
    """
    root = ET.fromstring(xges)
    timeline = root.find("project/timeline")
    if timeline is None:
        return []

    assets = {asset.get("id"): _asset_text(asset)
              for asset in root.iterfind("project/ressources/asset")}
    common = [VERSION, size]
    common.extend(_element_text(track) for track in timeline.iterfind("track"))

    clips = []
    end = 0
    for layer in timeline.iterfind("layer"):
        layer_text = _clean("%s|%s|%s" % (layer.get("priority"), layer.get("deactivated-tracks", ""),
                                         layer.get("metadatas", "")))
        common.append(layer_text)
        for clip in layer.iterfind("clip"):
            start = int(clip.get("start", 0))
            duration = int(clip.get("duration", 0))
            clip_end = start + duration
            end = max(end, clip_end)
            text = layer_text + _element_text(clip) + assets.get(clip.get("asset-id"), "")
            clips.append((start, clip_end, text))

    base = hashlib.sha1("\n".join(common).encode()).hexdigest()
    chunks = []
    position = 0
    while position < end:
        chunk_end = min(position + CHUNK_DURATION, end)
        digest = hashlib.sha1(base.encode())
        digest.update(b"%d-%d" % (position, chunk_end))
        for start, clip_end, text in clips:
            if start < chunk_end and clip_end > position:
                digest.update(text.encode())
        chunks.append(Chunk(position, chunk_end, digest.hexdigest()))
        position = chunk_end
    return chunks


def chunk_at(chunks: List[Chunk], position: int) -> Optional[int]:
    """Returns the index of the piece showing the position."""
    for index, chunk in enumerate(chunks):
        if chunk.start <= position < chunk.end:
            return index
    return None


def missing_from(chunks: List[Chunk], ready: Dict[str, str], position: int) -> List[Chunk]:
    """Returns the pieces not ready, from the one at the position, then the others."""
    first = chunk_at(chunks, position) or 0
    ordered = chunks[first:] + chunks[:first]
    return [chunk for chunk in ordered if chunk.key not in ready]
