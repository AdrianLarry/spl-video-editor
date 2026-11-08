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
"""Tests for the pitivi.previewcache package."""
import os
import tempfile

from gi.repository import Gst

from pitivi.previewcache.chunks import CHUNK_DURATION
from pitivi.previewcache.chunks import compute_chunks
from pitivi.previewcache.chunks import missing_from
from pitivi.previewcache.manager import prune
from tests import common

SECOND = Gst.SECOND


def xges(clips, size="width=(int)1080, height=(int)1920"):
    """Returns a saved project with clips given as (id, start, duration, extra)."""
    lines = ["<ges version='0.7'><project><ressources>",
             "<asset id='file:///foto.jpg' extractable-type-name='GESUriClip'/>",
             "</ressources><timeline>",
             "<track caps='video/x-raw(ANY)' track-type='4' track-id='0' "
             "properties='properties, restriction-caps=(string)\"video/x-raw, %s\";'/>" % size,
             "<layer priority='0'>"]
    for clip_id, start, duration, extra in clips:
        lines.append("<clip id='%d' asset-id='file:///foto.jpg' type-name='GESUriClip' layer-priority='0' "
                     "track-types='6' start='%d' duration='%d' inpoint='0' rate='0' "
                     "properties='properties, name=(string)uriclip%d, %s;'/>"
                     % (clip_id, start, duration, clip_id, extra))
    lines.append("</layer></timeline></project></ges>")
    return "".join(lines)


class ChunksTest(common.TestCase):
    """Tests for the pieces of the prepared preview."""

    def test_pieces_cover_the_timeline(self):
        chunks = compute_chunks(xges([(0, 0, 5 * SECOND, "a=1")]), "720x1280")
        self.assertEqual([(chunk.start, chunk.end) for chunk in chunks],
                         [(0, CHUNK_DURATION), (CHUNK_DURATION, 2 * CHUNK_DURATION),
                          (2 * CHUNK_DURATION, 5 * SECOND)])
        self.assertEqual(len({chunk.key for chunk in chunks}), 3)

    def test_edit_changes_only_the_pieces_under_it(self):
        before = compute_chunks(xges([(0, 0, 3 * SECOND, "a=1"),
                                      (1, 3 * SECOND, 3 * SECOND, "a=1")]), "720x1280")
        after = compute_chunks(xges([(0, 0, 3 * SECOND, "a=1"),
                                     (1, 3 * SECOND, 3 * SECOND, "a=2")]), "720x1280")
        changed = [a.key != b.key for a, b in zip(before, after)]
        # The second clip is under the pieces from 2 s on.
        self.assertEqual(changed, [False, True, True])

    def test_names_and_ids_do_not_matter(self):
        one = compute_chunks(xges([(0, 0, 3 * SECOND, "a=1")]), "720x1280")
        other = compute_chunks(xges([(7, 0, 3 * SECOND, "a=1")]), "720x1280")
        self.assertEqual([chunk.key for chunk in one], [chunk.key for chunk in other])

    def test_size_changes_all(self):
        clips = [(0, 0, 3 * SECOND, "a=1")]
        vertical = compute_chunks(xges(clips), "720x1280")
        horizontal = compute_chunks(xges(clips, "width=(int)1920, height=(int)1080"), "1280x720")
        self.assertTrue(all(a.key != b.key for a, b in zip(vertical, horizontal)))

    def test_missing_from_the_position(self):
        chunks = compute_chunks(xges([(0, 0, 8 * SECOND, "a=1")]), "720x1280")
        ready = {chunks[1].key: "path"}
        missing = missing_from(chunks, ready, 5 * SECOND)
        self.assertEqual(missing, [chunks[2], chunks[3], chunks[0]])

    def test_prune(self):
        with tempfile.TemporaryDirectory() as folder:
            for index in range(4):
                path = os.path.join(folder, "%d.mkv" % index)
                with open(path, "wb") as piece:
                    piece.write(b"x" * 100)
                os.utime(path, (index, index))
            prune(folder, limit=250)
            self.assertEqual(sorted(os.listdir(folder)), ["2.mkv", "3.mkv"])
