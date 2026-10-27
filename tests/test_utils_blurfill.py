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
"""Tests for the pitivi.utils.blurfill module."""
import tempfile

from gi.repository import GES
from gi.repository import Gst

from pitivi.project import Project
from pitivi.utils.blurfill import ALPHA_PROPERTY
from pitivi.utils.blurfill import blur_fill_description
from pitivi.utils.blurfill import BLUR_FILL_META
from pitivi.utils.blurfill import get_active_blur_fill
from pitivi.utils.blurfill import get_blur_fill
from pitivi.utils.blurfill import get_blur_sigma
from pitivi.utils.blurfill import restore_blur_fills
from pitivi.utils.blurfill import set_blur_fill
from pitivi.utils.blurfill import is_fill_needed
from pitivi.utils.blurfill import set_blur_sigma
from pitivi.utils.blurfill import update_blur_fill
from pitivi.utils.fades import get_keyframes
from pitivi.utils.formats import set_format
from pitivi.utils.formats import VERTICAL
from pitivi.utils.motion import set_base_position
from pitivi.utils.motion import get_base_position
from pitivi.utils.transitions import DISSOLVE
from pitivi.utils.transitions import get_contacts
from pitivi.utils.transitions import PUSH
from pitivi.utils.transitions import RIGHT
from pitivi.utils.transitions import set_image_fades
from pitivi.utils.transitions import set_transition
from pitivi.utils.transitions import sync_pushes
from tests import common

SECOND = Gst.SECOND


class BlurFillTest(common.TestCase):
    """Tests for the blurred fill of the clips."""

    def test_description(self):
        # A square image in a vertical frame: it fits the width.
        description = blur_fill_description((800, 800), (1080, 1920))
        self.assertIn("width=1080,height=1080,pixel-aspect-ratio=1/1 ! spl-mix.sink_1", description)
        self.assertIn("sink_1::xpos=0 sink_1::ypos=420", description)
        # The background covers a small frame, cropped to it.
        self.assertIn("width=480,height=480,pixel-aspect-ratio=1/1 ! videocrop left=105 right=105 top=0 bottom=0", description)
        self.assertTrue(description.endswith("format=AYUV,width=1080,height=1920 ! videoconvert"))
        self.assertIsNotNone(GES.Effect.new(description))

        # Custom sigma in description
        custom_desc = blur_fill_description((800, 800), (1080, 1920), sigma=15.0)
        self.assertIn("gaussianblur sigma=15", custom_desc)

    def test_fill_needed(self):
        self.assertTrue(is_fill_needed((1080, 1920), (1920, 1080)))
        self.assertFalse(is_fill_needed((1080, 1920), (1080, 1920)))
        # A photo of a phone, 3:4, leaves bands in a vertical frame.
        self.assertTrue(is_fill_needed((3000, 4000), (1080, 1920)))
        # The rounding leaves a pixel at most.
        self.assertFalse(is_fill_needed((1079, 1920), (1080, 1920)))

    @common.setup_timeline
    def test_unneeded_fill_is_inactive(self):
        self._wait_until_project_loaded()
        clip_a = self._add_image(0)
        self._add_image(3)
        self._set_blur_fill(clip_a, True)
        with self.action_log.started("push", toplevel=True):
            set_transition(get_contacts(self.layer)[0], PUSH, SECOND, RIGHT)
        self.assertTrue(get_active_blur_fill(clip_a))

        # In a 4:3 frame the image covers it, the fill is kept inactive.
        source = clip_a.find_track_element(None, GES.VideoSource)
        with self.action_log.started("frame", toplevel=True):
            source.get_track().update_restriction_caps(
                Gst.Caps.from_string("video/x-raw,width=1440,height=1080"))
            update_blur_fill(clip_a)
            sync_pushes(self.layer)
        effect = get_blur_fill(clip_a)
        self.assertFalse(effect.props.active)
        self.assertIsNone(get_active_blur_fill(clip_a))
        # The source itself moves for the push.
        values = {value for unused, value in
                  get_keyframes(source.get_control_binding("posx").props.control_source)}
        self.assertGreater(len(values), 1)

        self.action_log.undo()
        self.assertTrue(get_active_blur_fill(clip_a))

    def _add_image(self, start):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("flat_colour1_640x480.png"))
        return self.layer.add_asset(asset, start * SECOND, 0, 3 * SECOND, GES.TrackType.UNKNOWN)

    def _set_blur_fill(self, clip, enabled):
        with self.action_log.started("blur fill", toplevel=True):
            set_blur_fill(clip, enabled)
            sync_pushes(self.layer)

    @common.setup_timeline
    def test_blur_fill(self):
        self._wait_until_project_loaded()
        clip = self._add_image(0)
        source = clip.find_track_element(None, GES.VideoSource)
        self._set_blur_fill(clip, True)
        effect = get_blur_fill(clip)
        self.assertIsNotNone(effect)
        # The guides edit the foreground while the source covers the frame.
        self.assertEqual(get_base_position(source), {"posx": 240, "posy": 0, "width": 1440, "height": 1080})
        self.assertEqual(source.get_child_property("width")[1], 1920)

        # Custom blur sigma
        set_blur_sigma(source, 12.0)
        self.assertEqual(get_blur_sigma(source), 12.0)
        self.assertEqual(get_blur_sigma(clip), 12.0)
        res, sigma_val = effect.get_child_property("sigma")
        self.assertTrue(res)
        self.assertEqual(sigma_val, 12.0)

        # Another format makes the blurred fill again, preserving sigma.
        set_format(self.app, self.project, VERTICAL)
        effect = get_blur_fill(clip)
        self.assertIn("format=AYUV,width=1080,height=1920", effect.props.bin_description)
        self.assertIn("sigma=12", effect.props.bin_description)
        self.assertEqual(get_base_position(source)["width"], 1080)
        self.action_log.undo()
        self.assertIn("format=AYUV,width=1920,height=1080", get_blur_fill(clip).props.bin_description)

        self._set_blur_fill(clip, False)
        self.assertIsNone(get_blur_fill(clip))
        self.action_log.undo()
        self.assertIsNotNone(get_blur_fill(clip))

    @common.setup_timeline
    def test_resize_previously_unneeded_fill(self):
        self._wait_until_project_loaded()
        clip = self._add_image(0)
        source = clip.find_track_element(None, GES.VideoSource)
        source.get_track().update_restriction_caps(
            Gst.Caps.from_string("video/x-raw,width=1440,height=1080"))
        self._set_blur_fill(clip, True)
        self.assertIsNone(get_active_blur_fill(clip))
        with self.action_log.started("resize", toplevel=True):
            set_base_position(source, {"width": 800, "height": 600})
            sync_pushes(self.layer)
        self.assertIsNotNone(get_active_blur_fill(clip))
        self.action_log.undo()
        self.assertIsNone(get_active_blur_fill(clip))

    @common.setup_timeline
    def test_resize_foreground(self):
        self._wait_until_project_loaded()
        clip = self._add_image(0)
        source = clip.find_track_element(None, GES.VideoSource)
        self._set_blur_fill(clip, True)
        original = get_base_position(source)
        resized = {"posx": 500, "posy": 100, "width": 800, "height": 600}
        with self.action_log.started("resize foreground", toplevel=True):
            set_base_position(source, resized)
            sync_pushes(self.layer)
        self.assertEqual(get_base_position(source), resized)
        self.assertEqual(source.get_child_property("width")[1], 1920)
        self.assertEqual(source.get_child_property("height")[1], 1080)
        self.action_log.undo()
        self.assertEqual(get_base_position(source), original)
        self.action_log.redo()
        self.assertEqual(get_base_position(source), resized)
        update_blur_fill(clip)
        self.assertEqual(get_base_position(source), resized)
        with tempfile.NamedTemporaryFile(suffix=".xges") as saved:
            uri = Gst.filename_to_uri(saved.name)
            self.assertTrue(self.project.save(self.timeline, uri, None, overwrite=True))
            loaded = Project(app=self.app, uri=uri)
            loop = common.create_main_loop()
            loaded.connect_after("loaded", lambda *unused: loop.quit())
            self.assertTrue(loaded.create_timeline())
            try:
                loop.run()
                copy, = loaded.ges_timeline.get_layers()[0].get_clips()
                restore_blur_fills(loaded.ges_timeline)
                self.assertEqual(get_base_position(copy.find_track_element(None, GES.VideoSource)), resized)
            finally:
                loaded.release()
        self._set_blur_fill(clip, False)
        self.assertEqual(get_base_position(source), resized)

    @common.setup_timeline
    def test_push_and_fades(self):
        self._wait_until_project_loaded()
        clip_a = self._add_image(0)
        clip_b = self._add_image(3)
        for clip in (clip_a, clip_b):
            self._set_blur_fill(clip, True)

        with self.action_log.started("fade", toplevel=True):
            set_image_fades(clip_a, fade_in=SECOND)
        source_a = clip_a.find_track_element(None, GES.VideoSource)
        effect_a = get_blur_fill(clip_a)
        # The effect shares the alpha of the source.
        self.assertIs(effect_a.get_control_binding(ALPHA_PROPERTY).props.control_source,
                      source_a.get_control_binding("alpha").props.control_source)

        contact, = get_contacts(self.layer)
        with self.action_log.started("transition", toplevel=True):
            set_transition(contact, PUSH, SECOND, RIGHT)

        def keyframes(effect, name):
            binding = effect.get_control_binding(name)
            return [(timestamp / SECOND, round(value))
                    for timestamp, value in get_keyframes(binding.props.control_source)]

        # The frame of the first clip goes out to the left: cropped on the
        # left, a border on the right.
        self.assertEqual(keyframes(effect_a, "GstVideoBox::left"), [(0, 0), (2, 0), (3, 1920)])
        self.assertEqual(keyframes(effect_a, "GstVideoBox::right"), [(0, 0), (2, 0), (3, -1920)])
        effect_b = get_blur_fill(clip_b)
        self.assertEqual(keyframes(effect_b, "GstVideoBox::left"), [(0, -1920), (1, 0), (3, 0)])
        # The sources do not move, the effects cover them.
        self.assertIsNone(source_a.get_control_binding("posx"))

        self.action_log.undo()
        self.assertIsNone(effect_a.get_control_binding("GstVideoBox::left"))

    def _render_dissolve(self, filled_clips):
        # Exercise the actual GES mixer, not just the control bindings.
        timeline = GES.Timeline.new()
        track = GES.VideoTrack.new()
        timeline.add_track(track)
        track.set_restriction_caps(Gst.Caps.from_string(
            "video/x-raw,width=180,height=320,framerate=10/1"))
        layer = timeline.append_layer()
        layer.set_auto_transition(True)
        for index in range(2):
            asset = GES.UriClipAsset.request_sync(common.get_sample_uri(
                "flat_colour%d_640x480.png" % (index + 1)))
            clip = layer.add_asset(asset, index * 3 * SECOND, 0,
                                   3 * SECOND, GES.TrackType.VIDEO)
            if index in filled_clips:
                set_blur_fill(clip, True)
        set_transition(get_contacts(layer)[0], DISSOLVE, SECOND)
        timeline.commit_sync()
        pipeline = GES.Pipeline()
        pipeline.set_timeline(timeline)
        sink = Gst.parse_bin_from_description(
            "videoconvert ! video/x-raw,format=RGB ! appsink name=frames sync=false", True)
        pipeline.preview_set_video_sink(sink)
        pipeline.set_mode(GES.PipelineFlags.FULL_PREVIEW)
        frames = sink.get_by_name("frames")
        pixels = {}
        try:
            pipeline.set_state(Gst.State.PLAYING)
            self.assertEqual(pipeline.get_state(10 * SECOND)[0], Gst.StateChangeReturn.SUCCESS)
            for unused_index in range(100):
                sample = frames.emit("try-pull-sample", 10 * SECOND)
                if sample is None:
                    break
                buffer = sample.get_buffer()
                if buffer.pts in (SECOND, 5 * SECOND // 2, 4 * SECOND):
                    pixels[buffer.pts] = tuple(buffer.extract_dup((160 * 180 + 90) * 3, 3))
            error = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
            self.assertIsNone(error)
            self.assertEqual(len(pixels), 3)
            middle = pixels[5 * SECOND // 2]
            for endpoint in (pixels[SECOND], pixels[4 * SECOND]):
                self.assertGreater(sum(abs(a - b) for a, b in zip(middle, endpoint)), 30)
        finally:
            pipeline.set_state(Gst.State.NULL)

    def test_render_dissolve_outgoing_fill(self):
        self._render_dissolve({0})

    def test_render_dissolve_incoming_fill(self):
        self._render_dissolve({1})

    def test_render_dissolve_both_fills(self):
        self._render_dissolve({0, 1})

    @common.setup_timeline
    def test_restore_legacy_fill_and_priority(self):
        self._wait_until_project_loaded()
        clip = self._add_image(0)
        description = blur_fill_description((640, 480), (1920, 1080)).replace(
            "framepositioner name=spl-positioner ! ", "")
        legacy = GES.Effect.new(description)
        legacy.set_boolean(BLUR_FILL_META, True)
        clip.add(legacy)
        set_image_fades(clip, fade_in=SECOND)
        restore_blur_fills(self.layer.get_timeline())
        effect = get_blur_fill(clip)
        self.assertIn("framepositioner", effect.props.bin_description)
        source = clip.find_track_element(None, GES.VideoSource)
        self.assertIs(effect.get_control_binding(ALPHA_PROPERTY).props.control_source,
                      source.get_control_binding("alpha").props.control_source)
        self.layer.props.priority = 2
        self.assertEqual(effect.get_child_property("GstFramePositioner::zorder"),
                         (True, 0xffffffff - effect.props.priority))
        # Reconnecting a loaded effect is idempotent.
        restore_blur_fills(self.layer.get_timeline())
        self.assertIs(get_blur_fill(clip), effect)

    @common.setup_timeline
    def test_load_legacy_fill(self):
        self._wait_until_project_loaded()
        clip = self._add_image(0)
        self._add_image(3)
        description = blur_fill_description((640, 480), (1920, 1080)).replace(
            "framepositioner name=spl-positioner ! ", "")
        effect = GES.Effect.new(description)
        effect.set_boolean(BLUR_FILL_META, True)
        clip.add(effect)
        set_transition(get_contacts(self.layer)[0], DISSOLVE, SECOND)
        self.timeline.commit_sync()
        with tempfile.NamedTemporaryFile(suffix=".xges") as saved:
            uri = Gst.filename_to_uri(saved.name)
            self.assertTrue(self.project.save(self.timeline, uri, None, overwrite=True))
            loaded = Project(app=self.app, uri=uri)
            loop = common.create_main_loop()
            loaded.connect_after("loaded", lambda *unused: loop.quit())
            self.assertTrue(loaded.create_timeline())
            try:
                loop.run()
                layer = loaded.ges_timeline.get_layers()[0]
                contact, = get_contacts(layer)
                self.assertEqual(contact.kind, DISSOLVE)
                effect = get_blur_fill(contact.clip_a)
                self.assertIn("framepositioner", effect.props.bin_description)
                layer.props.priority = 2
                self.assertEqual(effect.get_child_property("GstFramePositioner::zorder"),
                                 (True, 0xffffffff - effect.props.priority))
            finally:
                loaded.release()
