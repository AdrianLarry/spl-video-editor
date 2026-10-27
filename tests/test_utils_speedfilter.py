# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Frame-level regressions for video speed across transition boundaries."""
import hashlib

from gi.repository import GES
from gi.repository import Gst

from pitivi.utils.transitions import BLUR
from pitivi.utils.transitions import DISSOLVE
from pitivi.utils.transitions import get_contacts
from pitivi.utils.transitions import set_transition
from tests import common

SECOND = Gst.SECOND


class SpeedFilterTest(common.TestCase):
    """Check actual video content, not just the duration of the clips."""

    def _render(self, rate, transition=None, in_point=0, seek_seconds=None):
        timeline = GES.Timeline.new_audio_video()
        layer = timeline.append_layer()
        layer.set_auto_transition(True)
        track = next(track for track in timeline.get_tracks()
                     if track.props.track_type == GES.TrackType.VIDEO)
        track.set_restriction_caps(Gst.Caps.from_string(
            "video/x-raw,width=320,height=240,framerate=30/1"))
        photo = GES.UriClipAsset.request_sync(common.get_sample_uri("flat_colour1_640x480.png"))
        layer.add_asset(photo, 0, 0, 3 * SECOND, GES.TrackType.VIDEO)
        video = GES.UriClipAsset.request_sync(common.get_sample_uri("30fps_numeroted_frames_blue.webm"))
        clip = layer.add_asset(video, 3 * SECOND, in_point, 2 * SECOND, GES.TrackType.VIDEO)
        effect = GES.Effect.new("splspeed ! videorate")
        clip.add_top_effect(effect, 0)
        effect.set_meta("ptv::time-effect", True)
        self.assertTrue(effect.set_child_property("SPLSpeedFilter::rate", rate))
        self.assertTrue(clip.set_duration(round(2 * SECOND / rate)))
        if transition:
            set_transition(get_contacts(layer)[0], transition, SECOND // 2)
        timeline.commit_sync()
        pipeline = GES.Pipeline()
        pipeline.set_timeline(timeline)
        sink = Gst.parse_bin_from_description(
            "videoconvert ! video/x-raw,format=RGB ! appsink name=frames sync=false", True)
        pipeline.preview_set_video_sink(sink)
        pipeline.preview_set_audio_sink(Gst.ElementFactory.make("fakesink"))
        pipeline.set_mode(GES.PipelineFlags.FULL_PREVIEW)
        frames = []
        try:
            pipeline.set_state(Gst.State.PAUSED)
            self.assertEqual(pipeline.get_state(10 * SECOND)[0], Gst.StateChangeReturn.SUCCESS)
            if seek_seconds is not None:
                self.assertTrue(pipeline.seek_simple(
                    Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                    clip.props.start + round(seek_seconds * SECOND)))
            pipeline.set_state(Gst.State.PLAYING)
            self.assertEqual(pipeline.get_state(10 * SECOND)[0], Gst.StateChangeReturn.SUCCESS)
            for unused in range(400):
                sample = sink.get_by_name("frames").emit("try-pull-sample", 5 * SECOND)
                if sample is None:
                    break
                buffer = sample.get_buffer()
                timestamp = (buffer.pts - clip.props.start) / SECOND
                digest = hashlib.sha256(buffer.extract_dup(0, buffer.get_size())).digest()
                frames.append((timestamp, digest))
            self.assertIsNone(pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR))
            self.assertTrue(frames)
            self.assertAlmostEqual(frames[-1][0], 2 / rate, delta=1 / 30 + 1e-6)
        finally:
            pipeline.set_state(Gst.State.NULL)
        return frames

    def _check_transition(self, rate, in_point=0, seek_seconds=None):
        reference = {digest: timestamp for timestamp, digest in self._render(1, in_point=in_point)
                     if timestamp >= 0}
        seek_reference = None
        if seek_seconds is not None:
            seek_reference = {round(timestamp, 6): digest for timestamp, digest in
                              self._render(rate, in_point=in_point, seek_seconds=seek_seconds)}
        for kind in (DISSOLVE, BLUR):
            with self.subTest(kind=kind, rate=rate):
                frames = self._render(rate, kind, in_point, seek_seconds)
                checked = 0
                previous = 0
                for timestamp, digest in frames:
                    if timestamp <= 0.55:
                        continue
                    self.assertIn(digest, reference)
                    media_time = reference[digest]
                    if seek_reference is not None:
                        # The first two frames after an accurate seek use
                        # decoder preroll. They must match the same seek
                        # without a transition, including its cadence.
                        self.assertEqual(digest, seek_reference[round(timestamp, 6)])
                        if timestamp < seek_seconds + 0.1:
                            continue
                    # Allow one source frame for cadence selection, but no
                    # freeze or jump at the end of the overlap.
                    self.assertAlmostEqual(media_time, timestamp * rate, delta=1 / 30 + 1e-6)
                    self.assertGreaterEqual(media_time, previous)
                    previous = media_time
                    checked += 1
                self.assertGreater(checked, 5)

    def test_fast_transition(self):
        self._check_transition(2)

    def test_slow_transition(self):
        self._check_transition(0.5)

    def test_seek_trimmed_fast_video(self):
        self._check_transition(2, SECOND // 2, 0.6)

    def test_seek_trimmed_slow_video(self):
        self._check_transition(0.5, SECOND // 2, 0.6)

    def test_seek_trimmed_normal_video(self):
        self._check_transition(1, SECOND // 2, 0.6)
