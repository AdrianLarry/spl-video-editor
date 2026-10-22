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
"""Tests for the pitivi.utils.motion module."""
from gi.repository import GES
from gi.repository import Gst

from pitivi.utils.blurfill import get_blur_fill
from pitivi.utils.blurfill import get_blur_sigma
from pitivi.utils.blurfill import set_blur_fill
from pitivi.utils.fades import get_keyframes
from pitivi.utils.formats import set_format
from pitivi.utils.formats import VERTICAL
from pitivi.utils.motion import get_base_position
from pitivi.utils.motion import get_zoom
from pitivi.utils.motion import get_zoom_effect
from pitivi.utils.motion import motion_keyframes
from pitivi.utils.motion import set_base_position
from pitivi.utils.motion import set_zoom
from pitivi.utils.motion import Zoom
from pitivi.utils.motion import ZOOM_IN
from pitivi.utils.motion import ZOOM_OUT
from pitivi.utils.timeline import EditingContext
from pitivi.utils.transitions import BLUR
from pitivi.utils.transitions import FADE_TO_WHITE
from pitivi.utils.transitions import get_contacts
from pitivi.utils.transitions import PUSH
from pitivi.utils.transitions import replace_asset
from pitivi.utils.transitions import RIGHT
from pitivi.utils.transitions import set_transition
from pitivi.utils.transitions import sync_pushes
from tests import common

SECOND = Gst.SECOND
FRAME = (1920, 1080)
FULL = {"posx": 0, "posy": 0, "width": 1920, "height": 1080}


def rounded(keyframes):
    return {prop: [(timestamp / SECOND, round(value)) for timestamp, value in values]
            for prop, values in keyframes.items()}


class MotionKeyframesTest(common.TestCase):
    """Tests for computing the animations."""

    def test_zoom_in_to_the_center(self):
        keyframes = motion_keyframes(FULL, Zoom(ZOOM_IN, "center", 1.5), {}, 0, 4 * SECOND, FRAME)
        self.assertEqual(rounded(keyframes), {
            "posx": [(0, 0), (4, -480)],
            "posy": [(0, 0), (4, -270)],
            "width": [(0, 1920), (4, 2880)],
            "height": [(0, 1080), (4, 1620)]})

    def test_zoom_out_from_a_corner(self):
        keyframes = motion_keyframes(FULL, Zoom(ZOOM_OUT, "bottom-right", 1.5), {}, 0, 4 * SECOND, FRAME)
        # The bottom right corner stays in place.
        self.assertEqual(rounded(keyframes)["posx"], [(0, -960), (4, 0)])
        self.assertEqual(rounded(keyframes)["posy"], [(0, -540), (4, 0)])

    def test_zoom_and_push(self):
        # A push at the end, to the left, during the last second.
        pushes = {"posx": [(3 * SECOND, 0, 4 * SECOND, -1920)]}
        keyframes = motion_keyframes(FULL, Zoom(ZOOM_IN, "center", 1.5), pushes, 0, 4 * SECOND, FRAME)
        self.assertEqual(rounded(keyframes)["posx"], [(0, 0), (3, -360), (4, -2400)])
        self.assertEqual(rounded(keyframes)["width"], [(0, 1920), (4, 2880)])

    def test_nothing(self):
        self.assertEqual(motion_keyframes(FULL, None, {}, 0, SECOND, FRAME), {})


class ZoomTest(common.TestCase):
    """Tests for the automatic zoom of the clips."""

    # A video, 4:3: its own source moves. The photos zoom with an effect.
    SAMPLE = "one_fps_numeroted_blue.mkv"

    def _add_clip(self, start):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri(self.SAMPLE))
        clip = self.layer.add_asset(asset, start * SECOND, 0, 4 * SECOND, GES.TrackType.UNKNOWN)
        return clip, clip.find_track_element(None, GES.VideoSource)

    @staticmethod
    def _keyframes(source, prop):
        binding = source.get_control_binding(prop)
        if not binding:
            return None
        return [(timestamp / SECOND, round(value))
                for timestamp, value in get_keyframes(binding.props.control_source)]

    def _set_zoom(self, source, zoom):
        with self.action_log.started("zoom", toplevel=True):
            set_zoom(source, zoom)
            sync_pushes(self.layer)

    @common.setup_timeline
    def test_zoom(self):
        self._wait_until_project_loaded()
        clip, source = self._add_clip(0)
        base = get_base_position(source)
        self.assertEqual(base, {"posx": 240, "posy": 0, "width": 1440, "height": 1080})

        self._set_zoom(source, Zoom(ZOOM_IN, "center", 1.5))
        self.assertEqual(get_zoom(source), Zoom(ZOOM_IN, "center", 1.5))
        self.assertEqual(self._keyframes(source, "width"), [(0, 1440), (4, 2160)])
        self.assertEqual(self._keyframes(source, "posx"), [(0, 240), (4, -120)])
        # The base position is kept.
        self.assertEqual(get_base_position(source), base)

        # Trimming the clip keeps the zoom from its start to its end.
        with self.action_log.started("trim", toplevel=True):
            context = EditingContext(clip, self.timeline, GES.EditMode.EDIT_TRIM,
                                     GES.Edge.EDGE_END, self.app)
            context.edit_to(2 * SECOND, self.layer)
            context.finish()
        self.assertEqual(self._keyframes(source, "width"), [(0, 1440), (2, 2160)])
        self.action_log.undo()
        self.assertEqual(self._keyframes(source, "width"), [(0, 1440), (4, 2160)])

        # Without zoom, the animation stays, still.
        self._set_zoom(source, None)
        self.assertIsNone(get_zoom(source))
        self.assertEqual(self._keyframes(source, "width"), [(0, 1440), (4, 1440)])

        self.action_log.undo()
        self.assertEqual(get_zoom(source), Zoom(ZOOM_IN, "center", 1.5))
        self.assertEqual(self._keyframes(source, "width"), [(0, 1440), (4, 2160)])
        self.action_log.undo()
        self.assertIsNone(get_zoom(source))

    @common.setup_timeline
    def test_zoom_with_push_and_framing(self):
        self._wait_until_project_loaded()
        unused_clip_a, source_a = self._add_clip(0)
        unused_clip_b, source_b = self._add_clip(4)
        self._set_zoom(source_a, Zoom(ZOOM_IN, "center", 1.5))
        contact, = get_contacts(self.layer)
        with self.action_log.started("transition", toplevel=True):
            set_transition(contact, PUSH, SECOND, RIGHT)
        # The first clip zooms, and goes out to the left during the push.
        self.assertEqual(self._keyframes(source_a, "posx"), [(0, 240), (3, -30), (4, -2040)])
        self.assertEqual(self._keyframes(source_a, "width"), [(0, 1440), (4, 2160)])

        # Filling the frame changes the base position, the motion goes on.
        with self.action_log.started("fill", toplevel=True):
            set_base_position(source_a, {"posx": 0, "posy": -180, "width": 1920, "height": 1440})
            sync_pushes(self.layer)
        self.assertEqual(self._keyframes(source_a, "width"), [(0, 1920), (4, 2880)])
        self.assertEqual(self._keyframes(source_a, "posx"), [(0, 0), (3, -360), (4, -2400)])

        # Another format, the zoom follows.
        set_format(self.app, self.project, VERTICAL)
        self.assertEqual(get_zoom(source_a), Zoom(ZOOM_IN, "center", 1.5))
        base = get_base_position(source_a)
        self.assertEqual(base["height"], 1920)
        self.assertEqual(self._keyframes(source_a, "height"), [(0, 1920), (4, 2880)])
        self.action_log.undo()
        self.assertEqual(self._keyframes(source_a, "width"), [(0, 1920), (4, 2880)])


class PhotoZoomTest(ZoomTest):
    """Tests for the automatic zoom of the photos, drawn by an effect."""

    SAMPLE = "flat_colour1_640x480.png"

    @staticmethod
    def _effect_keyframes(effect, name):
        binding = effect.get_control_binding(name)
        return [(timestamp / SECOND, round(value, 3))
                for timestamp, value in get_keyframes(binding.props.control_source)]

    @staticmethod
    def _source_position(source):
        return [source.get_child_property(prop)[1] for prop in ("posx", "posy", "width", "height")]

    @common.setup_timeline
    def test_zoom(self):
        self._wait_until_project_loaded()
        clip, source = self._add_clip(0)
        base = get_base_position(source)
        self.assertEqual(base, {"posx": 240, "posy": 0, "width": 1440, "height": 1080})

        self._set_zoom(source, Zoom(ZOOM_IN, "center", 1.5))
        effect = get_zoom_effect(clip)
        self.assertIn("max-zoom=1.500", effect.props.bin_description)
        self.assertIn("width=1920,height=1080", effect.props.bin_description)
        # The effect places the photo, the source covers the frame, still.
        self.assertEqual(self._source_position(source), [0, 0, 1920, 1080])
        self.assertFalse(source.get_control_binding("width"))
        self.assertEqual(get_base_position(source), base)
        self.assertEqual(self._effect_keyframes(effect, "zoom"), [(0, 1), (4, 1.5)])
        self.assertEqual(clip.get_top_effect_index(effect), 0)

        # Trimming the clip keeps the zoom from its start to its end.
        with self.action_log.started("trim", toplevel=True):
            context = EditingContext(clip, self.timeline, GES.EditMode.EDIT_TRIM,
                                     GES.Edge.EDGE_END, self.app)
            context.edit_to(2 * SECOND, self.layer)
            context.finish()
        self.assertEqual(self._effect_keyframes(effect, "zoom"), [(0, 1), (2, 1.5)])
        self.action_log.undo()
        self.assertEqual(self._effect_keyframes(effect, "zoom"), [(0, 1), (4, 1.5)])

        # Without zoom, the source places the photo again.
        self._set_zoom(source, None)
        self.assertIsNone(get_zoom_effect(clip))
        self.assertEqual(self._source_position(source), [240, 0, 1440, 1080])

        self.action_log.undo()
        effect = get_zoom_effect(clip)
        self.assertEqual(self._effect_keyframes(effect, "zoom"), [(0, 1), (4, 1.5)])
        self.assertEqual(self._source_position(source), [0, 0, 1920, 1080])
        self.action_log.undo()
        self.assertIsNone(get_zoom_effect(clip))
        self.assertEqual(self._source_position(source), [240, 0, 1440, 1080])

    @common.setup_timeline
    def test_zoom_with_push_and_framing(self):
        self._wait_until_project_loaded()
        clip_a, source_a = self._add_clip(0)
        self._add_clip(4)
        self._set_zoom(source_a, Zoom(ZOOM_IN, "center", 1.5))
        contact, = get_contacts(self.layer)
        with self.action_log.started("transition", toplevel=True):
            set_transition(contact, PUSH, SECOND, RIGHT)
        # The photo zooms, and goes out to the left during the push.
        effect = get_zoom_effect(clip_a)
        self.assertEqual(self._effect_keyframes(effect, "offset-x"), [(0, 0), (3, 0), (4, -1920)])
        self.assertEqual(self._effect_keyframes(effect, "zoom"), [(0, 1), (4, 1.5)])
        self.assertEqual(self._source_position(source_a), [0, 0, 1920, 1080])

        # Filling the frame changes the rectangle of the photo.
        with self.action_log.started("fill", toplevel=True):
            set_base_position(source_a, {"posx": 0, "posy": -180, "width": 1920, "height": 1440})
            sync_pushes(self.layer)
        self.assertEqual(get_base_position(source_a), {"posx": 0, "posy": -180, "width": 1920, "height": 1440})

        # Another format, the effect is made for it, the photo still fills.
        set_format(self.app, self.project, VERTICAL)
        effect = get_zoom_effect(clip_a)
        self.assertIn("width=1080,height=1920", effect.props.bin_description)
        self.assertEqual(get_base_position(source_a)["height"], 1920)
        self.assertEqual(self._source_position(source_a), [0, 0, 1080, 1920])
        self.assertEqual(self._effect_keyframes(effect, "offset-x"), [(0, 0), (3, 0), (4, -1080)])
        self.action_log.undo()
        effect = get_zoom_effect(clip_a)
        self.assertIn("width=1920,height=1080", effect.props.bin_description)
        self.assertEqual(get_base_position(source_a), {"posx": 0, "posy": -180, "width": 1920, "height": 1440})

    @common.setup_timeline
    def test_zoom_with_blur_fill(self):
        self._wait_until_project_loaded()
        clip, source = self._add_clip(0)
        self._set_zoom(source, Zoom(ZOOM_OUT, "top", 1.2))
        with self.action_log.started("fill", toplevel=True):
            set_blur_fill(clip, True)
            sync_pushes(self.layer)
        effect = get_zoom_effect(clip)
        # The effect makes the fill once, behind the photo fitting the frame,
        # and zooms all of it. The effect of the fill would remake it in
        # every frame, it is inactive.
        self.assertEqual(get_base_position(source), {"posx": 240, "posy": 0, "width": 1440, "height": 1080})
        self.assertEqual(effect.get_child_property("fill-sigma"), (True, get_blur_sigma(source)))
        self.assertFalse(get_blur_fill(clip).props.active)
        self.assertEqual(clip.get_top_effect_index(effect), 0)
        self.assertEqual(self._effect_keyframes(effect, "zoom"), [(0, 1.2), (4, 1)])
        self.assertEqual(effect.get_child_property("anchor-y"), (True, 0.0))

        # Without zoom, the effect of the fill makes it again.
        self._set_zoom(source, None)
        self.assertIsNone(get_zoom_effect(clip))
        self.assertTrue(get_blur_fill(clip).props.active)
        self.action_log.undo()
        self.assertFalse(get_blur_fill(clip).props.active)
        self.assertEqual(get_zoom_effect(clip).get_child_property("fill-sigma"), (True, get_blur_sigma(source)))

    @common.setup_timeline
    def test_zoom_with_transition_effects(self):
        """Checks the blurs and the fades to white apply to the zoomed frame."""
        self._wait_until_project_loaded()
        self._add_clip(0)
        clip_b, source_b = self._add_clip(4)
        self._set_zoom(source_b, Zoom(ZOOM_IN, "center", 1.5))
        effect = get_zoom_effect(clip_b)
        for kind in (BLUR, FADE_TO_WHITE):
            with self.action_log.started("transition", toplevel=True):
                set_transition(get_contacts(self.layer)[0], kind, SECOND)
            transition_effects = [e for e in clip_b.get_top_effects() if e != effect]
            self.assertEqual(len(transition_effects), 1, kind)
            # Applied after the zoom, on the frame.
            self.assertLess(clip_b.get_top_effect_index(transition_effects[0]),
                            clip_b.get_top_effect_index(effect), kind)
            if kind == BLUR:
                self.assertIn("width=1920,height=1080", transition_effects[0].props.bin_description)

        # Without zoom, the blur is made again for the photo.
        with self.action_log.started("transition", toplevel=True):
            set_transition(get_contacts(self.layer)[0], BLUR, SECOND)
        self._set_zoom(source_b, None)
        blur, = clip_b.get_top_effects()
        self.assertNotIn("width=1920", blur.props.bin_description)

    @common.setup_timeline
    def test_replace_asset_keeps_zoom(self):
        """Checks a proxy or its photo replacing the asset keeps the zoom."""
        self._wait_until_project_loaded()
        clip, source = self._add_clip(0)
        self._set_zoom(source, Zoom(ZOOM_IN, "top", 1.4))
        other = GES.UriClipAsset.request_sync(common.get_sample_uri("flat_colour2_640x480.png"))
        self.assertTrue(replace_asset(clip, other))
        source = clip.find_track_element(None, GES.VideoSource)
        self.assertEqual(get_zoom(source), Zoom(ZOOM_IN, "top", 1.4))
        self.assertEqual(self._effect_keyframes(get_zoom_effect(clip), "zoom"), [(0, 1), (4, 1.4)])
