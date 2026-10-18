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
"""Tests for the pitivi.utils.formats module."""
from gi.repository import GES
from gi.repository import Gst

from pitivi.utils.fades import get_keyframes
from pitivi.utils.formats import FILL
from pitivi.utils.formats import FIT
from pitivi.utils.formats import get_closest_format
from pitivi.utils.formats import get_fill_position
from pitivi.utils.formats import get_format
from pitivi.utils.formats import get_framed_position
from pitivi.utils.formats import get_framing
from pitivi.utils.formats import HORIZONTAL
from pitivi.utils.formats import MANUAL
from pitivi.utils.formats import set_format
from pitivi.utils.formats import SQUARE
from pitivi.utils.formats import VERTICAL
from pitivi.utils.transitions import get_contacts
from pitivi.utils.transitions import PUSH
from pitivi.utils.transitions import RIGHT
from pitivi.utils.transitions import set_transition
from tests import common

SECOND = Gst.SECOND


def get_position(source):
    return {prop: source.get_child_property(prop)[1]
            for prop in ("posx", "posy", "width", "height")}


def set_position(source, position):
    for prop, value in position.items():
        source.set_child_property(prop, value)


class FramingTest(common.TestCase):
    """Tests for keeping the framing in another frame."""

    def test_formats(self):
        self.assertEqual(get_format(1920, 1080), HORIZONTAL)
        self.assertEqual(get_format(1280, 720), HORIZONTAL)
        self.assertEqual(get_format(1080, 1920), VERTICAL)
        self.assertEqual(get_format(500, 500), SQUARE)
        self.assertIsNone(get_format(640, 480))
        self.assertEqual(get_closest_format(640, 480), HORIZONTAL)
        self.assertEqual(get_closest_format(720, 1280), VERTICAL)
        self.assertEqual(get_closest_format(1000, 900), SQUARE)

    def test_framing(self):
        # An image of 4:3 in a horizontal frame, then in a vertical one.
        fit = {"posx": 240, "posy": 0, "width": 1440, "height": 1080}
        new_fit = {"posx": 0, "posy": 555, "width": 1080, "height": 810}

        self.assertEqual(get_framing(fit, fit, 1920, 1080), (FIT, 0, 0))
        self.assertEqual(get_framed_position((FIT, 0, 0), fit, (1920, 1080), new_fit, 1080, 1920),
                         new_fit)

        fill = get_fill_position(fit, 1920, 1080)
        self.assertEqual(fill, {"posx": 0, "posy": -180, "width": 1920, "height": 1440})
        # Showing the top of the image.
        top = dict(fill, posy=0)
        self.assertEqual(get_framing(top, fit, 1920, 1080), (FILL, 0, 1))
        # In the vertical frame it overflows only on the sides, centered.
        self.assertEqual(get_framed_position((FILL, 0, 1), top, (1920, 1080), new_fit, 1080, 1920),
                         {"posx": -740, "posy": 0, "width": 2560, "height": 1920})
        # Back in the horizontal frame, the top is shown again.
        self.assertEqual(get_framed_position((FILL, 0, 1), top, (1920, 1080), fit, 1920, 1080), top)

        # Half the fitting size, around a point at a quarter of the frame.
        manual = {"posx": 120, "posy": 135, "width": 720, "height": 540}
        framing = get_framing(manual, fit, 1920, 1080)
        self.assertEqual(framing, (MANUAL, 0.5, 0))
        self.assertEqual(get_framed_position(framing, manual, (1920, 1080), new_fit, 1080, 1920),
                         {"posx": 0, "posy": 518, "width": 540, "height": 405})


class SetFormatTest(common.TestCase):
    """Tests for changing the format of the project."""

    def _add_clip(self, sample, start, duration=4):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri(sample))
        clip = self.layer.add_asset(asset, start * SECOND, 0, duration * SECOND,
                                    GES.TrackType.UNKNOWN)
        self.assertIsNotNone(clip)
        return clip, clip.find_track_element(None, GES.VideoSource)

    @common.setup_timeline
    def test_set_format(self):
        self._wait_until_project_loaded()
        self.assertEqual((self.project.videowidth, self.project.videoheight), (1920, 1080))
        unused_clip, fitting = self._add_clip("flat_colour1_640x480.png", 0)
        unused_clip, filling = self._add_clip("flat_colour1_640x480.png", 4)
        unused_clip, placed = self._add_clip("flat_colour1_640x480.png", 8)
        title = GES.TitleClip()
        title.set_start(12 * SECOND)
        title.set_duration(SECOND)
        self.layer.add_clip(title)
        title_source = title.find_track_element(None, GES.VideoSource)

        fit = get_position(fitting)
        self.assertEqual(fit, {"posx": 240, "posy": 0, "width": 1440, "height": 1080})
        set_position(filling, dict(get_fill_position(fit, 1920, 1080), posy=0))
        set_position(placed, {"posx": 120, "posy": 135, "width": 720, "height": 540})
        positions = [get_position(source) for source in (fitting, filling, placed, title_source)]

        set_format(self.app, self.project, VERTICAL)
        self.assertEqual((self.project.videowidth, self.project.videoheight), (1080, 1920))
        vertical_positions = [
            {"posx": 0, "posy": 555, "width": 1080, "height": 810},
            {"posx": -740, "posy": 0, "width": 2560, "height": 1920},
            {"posx": 0, "posy": 518, "width": 540, "height": 405},
            {"posx": 0, "posy": 0, "width": 1080, "height": 1920}]
        self.assertEqual([get_position(source) for source in (fitting, filling, placed, title_source)],
                         vertical_positions)

        # Undone in a single step.
        self.action_log.undo()
        self.assertEqual((self.project.videowidth, self.project.videoheight), (1920, 1080))
        self.assertEqual([get_position(source) for source in (fitting, filling, placed, title_source)],
                         positions)

        self.action_log.redo()
        self.assertEqual((self.project.videowidth, self.project.videoheight), (1080, 1920))
        self.assertEqual([get_position(source) for source in (fitting, filling, placed, title_source)],
                         vertical_positions)

        # A square, the filling image covers it.
        set_format(self.app, self.project, SQUARE)
        self.assertEqual(get_position(filling), {"posx": -180, "posy": 0, "width": 1440, "height": 1080})

    @common.setup_timeline
    def test_set_format_with_push(self):
        self._wait_until_project_loaded()
        clip_a, source_a = self._add_clip("one_fps_numeroted_blue.mkv", 0)
        unused_clip, source_b = self._add_clip("one_fps_numeroted_blue.mkv", 4)

        def get_posx_keyframes(source):
            binding = source.get_control_binding("posx")
            return [(timestamp / SECOND, round(value)) for timestamp, value
                    in get_keyframes(binding.props.control_source)]

        contact, = get_contacts(self.layer)
        with self.action_log.started("transition"):
            set_transition(contact, PUSH, SECOND, RIGHT)
        base_a = source_a.get_child_property("posx")[1]
        keyframes_a = get_posx_keyframes(source_a)
        self.assertEqual(keyframes_a, [(0, base_a), (3, base_a), (4, base_a - 1920)])

        set_format(self.app, self.project, VERTICAL)
        new_base_a = source_a.ui.default_position["posx"]
        # The first clip goes out to the left of the narrower frame.
        self.assertEqual(get_posx_keyframes(source_a),
                         [(0, new_base_a), (3, new_base_a), (4, new_base_a - 1080)])
        self.assertEqual(get_posx_keyframes(source_b)[0], (0, new_base_a + 1080))
        self.assertEqual(get_position(source_a)["width"], 1080)

        self.action_log.undo()
        self.assertEqual(get_posx_keyframes(source_a), keyframes_a)
        self.assertEqual(get_contacts(self.layer)[0].kind, PUSH)
