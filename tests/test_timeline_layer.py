# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2015, Alex Băluț <alexandru.balut@gmail.com>
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
# pylint: disable=protected-access
from unittest import mock

from gi.repository import GES
from gi.repository import Gst

from pitivi.timeline.layer import AUDIO_ICONS
from pitivi.timeline.layer import FullLayer
from pitivi.timeline.transitions import TransitionPopover
from pitivi.timeline.layer import VIDEO_ICONS
from pitivi.utils.timeline import Zoomable
from pitivi.utils.transitions import DISSOLVE
from pitivi.utils.transitions import get_contacts
from pitivi.utils.ui import LAYER_HEIGHT
from tests import common


class TestLayerControl(common.TestCase):

    def test_name(self):
        timeline = mock.MagicMock()
        ges_layer = GES.Layer()
        layer = FullLayer(ges_layer, timeline)
        self.assertEqual(layer.get_name(), "Layer 1", "Default name generation failed")

        ges_layer.set_meta("audio::name", "a")
        self.assertEqual(layer.get_name(), "a", "Cannot use old audio name")

        ges_layer.set_meta("video::name", "v")
        self.assertEqual(layer.get_name(), "v", "Cannot use old video name")

        layer.set_name("vv")
        self.assertEqual(layer.get_name(), "vv")

    def test_name_meaningful(self):
        timeline = mock.MagicMock()
        ges_layer = GES.Layer()
        layer = FullLayer(ges_layer, timeline)
        layer.set_name("Layer 0x")
        self.assertEqual(layer.get_name(), "Layer 0x")

    def test_audio_toggle(self):
        """Checks that audio toggling is reflected in the UI."""
        timeline_container = common.create_timeline_container()
        timeline = timeline_container.timeline
        ges_layer = timeline.ges_timeline.append_layer()
        layer_controls = ges_layer.control_ui
        audio_button = layer_controls.audio_button

        for audio_track in layer_controls.timeline_audio_tracks:
            self.assertTrue(ges_layer.get_active_for_track(audio_track))
            self.assertEqual(audio_button.get_image().props.icon_name, AUDIO_ICONS[True])

            ges_layer.set_active_for_tracks(False, [audio_track])
            common.create_main_loop().run(until_empty=True)
            self.assertFalse(ges_layer.get_active_for_track(audio_track))
            self.assertEqual(audio_button.get_image().props.icon_name, AUDIO_ICONS[False])

            ges_layer.set_active_for_tracks(True, [audio_track])
            common.create_main_loop().run(until_empty=True)
            self.assertTrue(ges_layer.get_active_for_track(audio_track))
            self.assertEqual(audio_button.get_image().props.icon_name, AUDIO_ICONS[True])

    def test_audio_button(self):
        """Checks that the audio button toggles the audio track."""
        timeline_container = common.create_timeline_container()
        timeline = timeline_container.timeline
        ges_layer = timeline.ges_timeline.append_layer()
        layer_controls = ges_layer.control_ui
        audio_button = layer_controls.audio_button

        for audio_track in layer_controls.timeline_audio_tracks:
            self.assertTrue(ges_layer.get_active_for_track(audio_track))
        common.create_main_loop().run(until_empty=True)
        self.assertEqual(audio_button.get_image().props.icon_name, AUDIO_ICONS[True])

        audio_button.clicked()
        for audio_track in layer_controls.timeline_audio_tracks:
            self.assertFalse(ges_layer.get_active_for_track(audio_track))
        common.create_main_loop().run(until_empty=True)
        self.assertEqual(audio_button.get_image().props.icon_name, AUDIO_ICONS[False])

        audio_button.clicked()
        for audio_track in layer_controls.timeline_audio_tracks:
            self.assertTrue(ges_layer.get_active_for_track(audio_track))
        common.create_main_loop().run(until_empty=True)
        self.assertEqual(audio_button.get_image().props.icon_name, AUDIO_ICONS[True])

    def test_video_toggle(self):
        """Checks that video toggling is reflected in the UI."""
        timeline_container = common.create_timeline_container()
        timeline = timeline_container.timeline
        ges_layer = timeline.ges_timeline.append_layer()
        layer_controls = ges_layer.control_ui
        video_button = layer_controls.video_button

        for video_track in layer_controls.timeline_video_tracks:
            self.assertTrue(ges_layer.get_active_for_track(video_track))
            self.assertEqual(video_button.get_image().props.icon_name, VIDEO_ICONS[True])

            ges_layer.set_active_for_tracks(False, [video_track])
            common.create_main_loop().run(until_empty=True)
            self.assertFalse(ges_layer.get_active_for_track(video_track))
            self.assertEqual(video_button.get_image().props.icon_name, VIDEO_ICONS[False])

            ges_layer.set_active_for_tracks(True, [video_track])
            common.create_main_loop().run(until_empty=True)
            self.assertTrue(ges_layer.get_active_for_track(video_track))
            self.assertEqual(video_button.get_image().props.icon_name, VIDEO_ICONS[True])

    def test_video_button(self):
        """Checks that the video button toggles the video track."""
        timeline_container = common.create_timeline_container()
        timeline = timeline_container.timeline
        ges_layer = timeline.ges_timeline.append_layer()
        layer_controls = ges_layer.control_ui
        video_button = layer_controls.video_button

        for video_track in layer_controls.timeline_video_tracks:
            self.assertTrue(ges_layer.get_active_for_track(video_track))
        common.create_main_loop().run(until_empty=True)
        self.assertEqual(video_button.get_image().props.icon_name, VIDEO_ICONS[True])

        video_button.clicked()
        for video_track in layer_controls.timeline_video_tracks:
            self.assertFalse(ges_layer.get_active_for_track(video_track))
        common.create_main_loop().run(until_empty=True)
        self.assertEqual(video_button.get_image().props.icon_name, VIDEO_ICONS[False])

        video_button.clicked()
        for video_track in layer_controls.timeline_video_tracks:
            self.assertTrue(ges_layer.get_active_for_track(video_track))
        common.create_main_loop().run(until_empty=True)
        self.assertEqual(video_button.get_image().props.icon_name, VIDEO_ICONS[True])


class TestLayer(common.TestCase):

    @common.setup_timeline
    def test_close_gap(self):
        """Checks closing a gap moves only the clips of the layer."""
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("one_fps_numeroted_blue.mkv"))

        def add_clip(layer, start):
            clip = layer.add_asset(asset, start * Gst.SECOND, 0, 2 * Gst.SECOND,
                                   GES.TrackType.UNKNOWN)
            self.assertIsNotNone(clip)
            return clip

        clip1 = add_clip(self.layer, 0)
        clip2 = add_clip(self.layer, 5)
        clip3 = add_clip(self.layer, 9)
        other_layer = self.timeline.append_layer()
        other_clip = add_clip(other_layer, 6)
        # Zoom in, so that the buttons fit in the gaps.
        Zoomable.set_zoom_level(78)
        self.project.pipeline.commit_timeline()

        layer_ui = self.layer.ui
        self.assertEqual(layer_ui.get_gaps(),
                         [(2 * Gst.SECOND, 5 * Gst.SECOND), (7 * Gst.SECOND, 9 * Gst.SECOND)])
        self.assertEqual(len(layer_ui.gap_buttons), 2)

        layer_ui.gap_buttons[0].clicked()
        self.assertEqual([clip.props.start / Gst.SECOND for clip in (clip1, clip2, clip3)],
                         [0, 2, 6])
        self.assertEqual(other_clip.props.start, 6 * Gst.SECOND)
        self.assertEqual(len(layer_ui.gap_buttons), 1)

        self.action_log.undo()
        self.assertEqual([clip.props.start / Gst.SECOND for clip in (clip1, clip2, clip3)],
                         [0, 5, 9])

        # A gap at the beginning of the layer.
        with self.action_log.started("move"):
            clip1.set_start(Gst.SECOND)
        self.assertEqual(layer_ui.get_gaps()[0], (0, Gst.SECOND))
        layer_ui.close_gap(0, Gst.SECOND)
        self.assertEqual([clip.props.start / Gst.SECOND for clip in (clip1, clip2, clip3)],
                         [0, 4, 8])
        self.action_log.undo()
        self.action_log.undo()
        # The buttons are updated when the timeline has been committed.
        common.create_main_loop().run(until_empty=True)
        self.assertEqual(len(layer_ui.gap_buttons), 2)

    def test_check_media_types(self):
        """Checks media types when there is no control UI."""
        ges_layer = GES.Layer()
        png = common.get_sample_uri("flat_colour1_640x480.png")
        video_clip = GES.UriClipAsset.request_sync(png).extract()
        self.assertTrue(ges_layer.add_clip(video_clip))
        self.assertEqual(len(ges_layer.get_clips()), 1)
        timeline_container = common.create_timeline_container()
        timeline = timeline_container.timeline
        # This will add widgets for the clips in ges_layer and
        # the layer will use check_media_types which updates the
        # height of layer.control_ui, which now it should not be set.
        self.assertFalse(hasattr(ges_layer, "control_ui"))
        unused_layer = FullLayer(ges_layer, timeline)

    @common.setup_timeline
    def test_layer_heights(self):
        self.check_layer_height(GES.TrackType(0))

        clip_video = GES.UriClipAsset.request_sync(common.get_sample_uri("one_fps_numeroted_blue.mkv")).extract()
        self.timeline_container._insert_clips_and_assets([clip_video], 0, self.layer)
        self.check_layer_height(GES.TrackType.VIDEO)

        clip_audio = GES.UriClipAsset.request_sync(common.get_sample_uri("mp3_sample.mp3")).extract()
        self.timeline_container._insert_clips_and_assets([clip_audio], 0, self.layer)
        self.check_layer_height(GES.TrackType.AUDIO | GES.TrackType.VIDEO)

        self.click_clip(clip_video, expect_selected=True)
        self.timeline_container.delete_action.activate()
        self.check_layer_height(GES.TrackType.AUDIO)

        self.click_clip(clip_audio, expect_selected=True)
        self.timeline_container.delete_action.activate()
        self.check_layer_height(GES.TrackType(0))

        # Undo everything.
        self.action_log.undo()
        self.check_layer_height(GES.TrackType.AUDIO)

        self.action_log.undo()
        self.check_layer_height(GES.TrackType.AUDIO | GES.TrackType.VIDEO)

        self.action_log.undo()
        self.check_layer_height(GES.TrackType.VIDEO)

        self.action_log.undo()
        self.check_layer_height(GES.TrackType(0))

        # Redo everything.
        self.action_log.redo()
        self.check_layer_height(GES.TrackType.VIDEO)

        self.action_log.redo()
        self.check_layer_height(GES.TrackType.AUDIO | GES.TrackType.VIDEO)

        self.action_log.redo()
        self.check_layer_height(GES.TrackType.AUDIO)

        self.action_log.redo()
        self.check_layer_height(GES.TrackType(0))

    def check_layer_height(self, expected_media_types: GES.TrackType):
        self.assertEqual(self.timeline_container.timeline.media_types, expected_media_types)
        if expected_media_types == GES.TrackType.AUDIO | GES.TrackType.VIDEO:
            self.assertEqual(self.layer.ui.props.height_request, LAYER_HEIGHT)
        else:
            self.assertEqual(self.layer.ui.props.height_request, LAYER_HEIGHT // 2)

    @common.setup_timeline
    def test_transition_buttons(self):
        """Checks adding a transition with the button where clips meet."""
        self._wait_until_project_loaded()
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("one_fps_numeroted_blue.mkv"))
        clip_a = self.layer.add_asset(asset, 0, 0, 4 * Gst.SECOND, GES.TrackType.UNKNOWN)
        clip_b = self.layer.add_asset(asset, 4 * Gst.SECOND, 0, 4 * Gst.SECOND, GES.TrackType.UNKNOWN)
        Zoomable.set_zoom_level(78)
        layer_ui = self.layer.ui
        layer_ui.update_gaps()

        button, = layer_ui.transition_buttons
        self.assertIsNone(button.get_child().kind)
        self.assertEqual(button.get_tooltip_text(), "Add a transition")

        contact, = get_contacts(self.layer)
        popover = TransitionPopover(self.app, contact, button)
        self.assertEqual(popover.get_kind(), DISSOLVE)
        popover.duration_scale.set_value(1.5)
        popover.apply_button.clicked()

        self.assertEqual(clip_b.props.start, int(2.5 * Gst.SECOND))
        self.assertEqual(get_contacts(self.layer)[0].kind, DISSOLVE)
        layer_ui.update_gaps()
        button, = layer_ui.transition_buttons
        # An icon of the kind, its name is in the tooltip.
        self.assertEqual(button.get_child().kind, DISSOLVE)
        self.assertTrue(button.get_tooltip_text().startswith("Dissolve, "))

        # Removed with the button of the popover.
        popover = TransitionPopover(self.app, get_contacts(self.layer)[0], button)
        popover.remove_button.clicked()
        self.assertEqual(clip_b.props.start, 4 * Gst.SECOND)
        self.assertIsNone(get_contacts(self.layer)[0].kind)
        self.assertEqual(clip_a.props.duration, 4 * Gst.SECOND)

    @common.setup_timeline
    def test_empty_layers_are_removed(self):
        """Checks the empty layers are removed, keeping a layer."""
        self._wait_until_project_loaded()
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("one_fps_numeroted_blue.mkv"))
        layers = [self.layer, self.timeline.append_layer(), self.timeline.append_layer()]
        clips = [layer.add_asset(asset, 0, 0, Gst.SECOND, GES.TrackType.UNKNOWN) for layer in layers]
        timeline = self.timeline_container.timeline

        # Emptying a layer removes it.
        timeline.selection.select([clips[1]])
        self.timeline_container.delete_action.activate(None)
        self.assertEqual(self.timeline.get_layers(), [layers[0], layers[2]])

        # Undone with the removed clip.
        self.action_log.undo()
        self.assertEqual(self.timeline.get_layers(), layers)
        self.assertEqual([len(layer.get_clips()) for layer in layers], [1, 1, 1])

        # The last layer is kept.
        for clip in clips:
            timeline.selection.select([clip])
            self.timeline_container.delete_action.activate(None)
        self.assertEqual(len(self.timeline.get_layers()), 1)

    @common.setup_timeline
    def test_new_layers_keep_the_audio_below(self):
        """Checks where the layers created by dragging go."""
        image = GES.UriClipAsset.request_sync(common.get_sample_uri("flat_colour1_640x480.png"))
        music = GES.UriClipAsset.request_sync(common.get_sample_uri("mp3_sample.mp3"))
        image_clip = self.layer.add_asset(image, 0, 0, 4 * Gst.SECOND, GES.TrackType.UNKNOWN)
        self.timeline.append_layer().add_asset(music, 0, 0, 4 * Gst.SECOND, GES.TrackType.UNKNOWN)
        timeline_ui = self.timeline_container.timeline
        image_formats = image.get_supported_formats()
        music_formats = music.get_supported_formats()

        # Below the audio, a layer for images goes above it.
        self.assertEqual(timeline_ui.get_new_layer_priority(2, image_formats), 1)
        self.assertEqual(timeline_ui.get_new_layer_priority(0, image_formats), 0)
        # Above the images, a layer for audio goes below them.
        self.assertEqual(timeline_ui.get_new_layer_priority(0, music_formats), 1)
        self.assertEqual(timeline_ui.get_new_layer_priority(2, music_formats), 2)
        # The clip being moved does not count.
        self.assertEqual(timeline_ui.get_new_layer_priority(0, music_formats, image_clip), 0)

        new_layer = timeline_ui.create_layer_for(2, image_formats)
        self.assertEqual(self.timeline.get_layers().index(new_layer), 1)

    @common.setup_timeline
    def test_audio_in_layers_of_its_own(self):
        """Checks the audio clips and the others go in separate layers."""
        self._wait_until_project_loaded()
        image = GES.UriClipAsset.request_sync(common.get_sample_uri("flat_colour1_640x480.png"))
        music = GES.UriClipAsset.request_sync(common.get_sample_uri("mp3_sample.mp3"))
        image_clip = self.layer.add_asset(image, 0, 0, 4 * Gst.SECOND, GES.TrackType.UNKNOWN)
        self.timeline_container.timeline.selection.select([image_clip])

        # The music goes to a new layer at the bottom.
        self.timeline_container.add_assets_to_selected_layer([music])
        layers = self.timeline.get_layers()
        self.assertEqual(len(layers), 2)
        self.assertEqual(layers[0].get_clips(), [image_clip])
        music_clip, = layers[1].get_clips()
        self.assertEqual(music_clip.get_asset(), music)

        # Another music goes after it, an image to the layer of images.
        self.timeline_container.timeline.selection.select([music_clip])
        self.timeline_container.add_assets_to_selected_layer([music, image])
        self.assertEqual(len(self.timeline.get_layers()), 2)
        self.assertEqual([clip.get_asset() for clip in sorted(layers[1].get_clips(), key=lambda c: c.start)],
                         [music, music])
        self.assertEqual(len(layers[0].get_clips()), 2)

        # Undone in a single step.
        self.action_log.undo()
        self.assertEqual(len(layers[1].get_clips()), 1)
        self.assertEqual(len(layers[0].get_clips()), 1)
