# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2016, Thibault Saunier <tsaunier@gnome.org>
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
"""Tests for the utils.pipeline module."""
# pylint: disable=protected-access
from unittest import mock

from gi.repository import GES
from gi.repository import GLib
from gi.repository import Gst

from pitivi.utils.pipeline import MAX_RECOVERIES
from pitivi.utils.pipeline import Pipeline
from pitivi.utils.pipeline import SimplePipeline
from tests import common


class TestPipeline(common.TestCase):
    """Tests for the Pipeline class."""

    @staticmethod
    def post_fake_error_message(pipeline):
        """Simulates an error message on the specified Pipeline."""
        message = mock.Mock()
        message.type = Gst.MessageType.ERROR
        error = GLib.Error.new_literal(Gst.core_error_quark(),
                                       "fake", Gst.CoreError.TOO_LAZY)
        message.parse_error = mock.MagicMock(return_value=(error, "fake"))
        pipeline._bus_message_cb(None, message)

    def test_recovery(self):
        """Checks the recovery mechanism."""
        pipe = Pipeline(common.create_pitivi_mock())
        pipe.set_timeline(GES.Timeline())

        pipeline_died_cb = mock.Mock()
        pipe.connect("died", pipeline_died_cb)

        with mock.patch.object(pipe, "set_state") as set_state:
            pipe.pause()
            set_state.assert_called_once_with(Gst.State.PAUSED)
        self.assertEqual(pipe._attempted_recoveries, 0)
        self.assertFalse(pipeline_died_cb.called)

        for i in range(MAX_RECOVERIES):
            with mock.patch.object(pipe, "set_state") as set_state:
                set_state.return_value = Gst.StateChangeReturn.SUCCESS
                self.post_fake_error_message(pipe)
                set_state.assert_has_calls([mock.call(Gst.State.NULL),
                                            mock.call(Gst.State.PAUSED)])
                self.assertEqual(set_state.call_count, 2)
            self.assertEqual(pipe._attempted_recoveries, i + 1)
            self.assertFalse(pipeline_died_cb.called)

        with mock.patch.object(pipe, "set_state") as set_state:
            self.post_fake_error_message(pipe)
            set_state.assert_not_called()
        self.assertTrue(pipeline_died_cb.called)
        self.assertEqual(pipe._attempted_recoveries, MAX_RECOVERIES)

    def test_async_done_not_received(self):
        """Checks the recovery when the ASYNC_DONE message timed out."""
        ges_timeline = GES.Timeline.new()
        self.assertTrue(ges_timeline.add_track(GES.VideoTrack.new()))
        ges_layer = ges_timeline.append_layer()
        uri = common.get_sample_uri("tears_of_steel.webm")
        asset = GES.UriClipAsset.request_sync(uri)
        ges_clip = asset.extract()
        self.assertTrue(ges_layer.add_clip(ges_clip))
        self.assertFalse(ges_timeline.is_empty())

        pipe = Pipeline(app=common.create_pitivi_mock())

        pipe.set_timeline(ges_timeline)
        self.assertFalse(pipe._busy_async)
        self.assertEqual(pipe._recovery_state, SimplePipeline.RecoveryState.NOT_RECOVERING)

        # Pretend waiting for async-done timed out.
        # We mock set_state because we don't actually care about the state,
        # and setting the state to PAUSED could show a video window.
        with mock.patch.object(pipe, "set_state"):
            pipe._async_done_not_received_cb("reason1", 1)
        # Make sure the pipeline started a watchdog timer waiting for async-done
        # as part of setting the state from NULL to PAUSED.
        self.assertTrue(pipe._busy_async)
        self.assertEqual(pipe._attempted_recoveries, 1)
        self.assertEqual(pipe._recovery_state, SimplePipeline.RecoveryState.STARTED_RECOVERING)

        # Pretend the state changed to READY.
        message = mock.Mock()
        message.type = Gst.MessageType.STATE_CHANGED
        message.src = pipe._pipeline
        message.parse_state_changed.return_value = (Gst.State.NULL, Gst.State.READY, Gst.State.PAUSED)
        pipe._bus_message_cb(None, message)

        # Pretend the state changed to PAUSED.
        message.parse_state_changed.return_value = (Gst.State.READY, Gst.State.PAUSED, Gst.State.VOID_PENDING)
        self.assertEqual(pipe._next_seek, None)
        pipe._bus_message_cb(None, message)
        self.assertEqual(pipe._recovery_state, SimplePipeline.RecoveryState.SEEKED_AFTER_RECOVERING)
        self.assertTrue(pipe._busy_async)
        # The pipeline should have tried to seek back to the last position.
        self.assertEqual(pipe._next_seek, 0)

        # Pretend the state change (to PAUSED) async operation succeeded.
        message.type = Gst.MessageType.ASYNC_DONE
        with mock.patch.object(pipe, "get_state") as get_state:
            get_state.return_value = (0, Gst.State.PAUSED, 0)
            pipe._bus_message_cb(None, message)
        self.assertEqual(pipe._recovery_state, SimplePipeline.RecoveryState.NOT_RECOVERING)
        # Should still be busy because of seeking to _next_seek.
        self.assertTrue(pipe._busy_async)
        self.assertIsNone(pipe._next_seek)

        # Pretend the seek async operation finished.
        message.type = Gst.MessageType.ASYNC_DONE
        pipe._bus_message_cb(None, message)
        self.assertEqual(pipe._recovery_state, SimplePipeline.RecoveryState.NOT_RECOVERING)
        self.assertFalse(pipe._busy_async)
        self.assertIsNone(pipe._next_seek)

    def test_commit_empty_timeline(self):
        """Checks committing an empty timeline does not wait for async-done."""
        ges_timeline = GES.Timeline.new()
        self.assertTrue(ges_timeline.add_track(GES.VideoTrack.new()))
        ges_timeline.append_layer()
        self.assertTrue(ges_timeline.is_empty())

        pipe = Pipeline(app=common.create_pitivi_mock())
        pipe.set_timeline(ges_timeline)
        with mock.patch.object(pipe, "get_simple_state") as get_simple_state:
            get_simple_state.return_value = Gst.State.PAUSED
            pipe.commit_timeline()
        # No ASYNC_DONE is emitted for an empty timeline.
        self.assertFalse(pipe._busy_async)

    def test_commit_timeline_after(self):
        """Checks the recovery mechanism."""
        pipe = Pipeline(common.create_pitivi_mock())
        timeline = GES.Timeline()
        pipe.set_timeline(timeline)

        with mock.patch.object(pipe, "get_state") as get_state:
            get_state.return_value = (0, Gst.State.PAUSED, 0)
            with mock.patch.object(timeline, "commit") as commit:
                with pipe.commit_timeline_after():
                    pipe.commit_timeline()
                self.assertEqual(commit.call_count, 1)

            with mock.patch.object(timeline, "commit") as commit:
                with pipe.commit_timeline_after():
                    self.assertEqual(pipe._prevent_commits, 1)
                    with pipe.commit_timeline_after():
                        self.assertEqual(pipe._prevent_commits, 2)
                        pipe.commit_timeline()
                        self.assertEqual(commit.call_count, 0)
                self.assertEqual(commit.call_count, 1)

    def test_last_frame(self):
        """Checks the viewer stops on the last frame, not on the black after it."""
        ges_timeline = GES.Timeline.new()
        track = GES.VideoTrack.new()
        self.assertTrue(ges_timeline.add_track(track))
        track.set_restriction_caps(Gst.Caps.from_string("video/x-raw,framerate=25/1"))
        layer = ges_timeline.append_layer()
        layer.add_clip(GES.TestClip.new())
        pipe = Pipeline(app=common.create_pitivi_mock())
        pipe.set_timeline(ges_timeline)

        with mock.patch.object(pipe, "get_duration") as get_duration, \
                mock.patch.object(SimplePipeline, "simple_seek") as simple_seek:
            get_duration.return_value = 10 * Gst.SECOND
            last_frame = 10 * Gst.SECOND - Gst.SECOND // 25
            self.assertEqual(pipe.get_last_frame_position(), last_frame)

            # The end is the last frame.
            pipe.simple_seek(10 * Gst.SECOND)
            simple_seek.assert_called_with(pipe, last_frame)

            # Playing on the last frame starts again.
            pipe._last_position = last_frame
            with mock.patch.object(pipe, "play"):
                pipe.toggle_playback()
            simple_seek.assert_called_with(pipe, 0)

    def test_preview_audio_format_stays_stable(self):
        """Changing source audio formats does not renegotiate the device."""
        pipe = Pipeline(app=common.create_pitivi_mock())
        audio = pipe.props.audio_sink
        output_format = audio.get_by_name("spl-preview-audio-format")
        device = output_format.get_static_pad("src").get_peer().get_parent_element()
        output_format.unlink(device)
        audio.remove(device)
        sink = Gst.ElementFactory.make("appsink")
        sink.props.sync = False
        audio.add(sink)
        self.assertTrue(output_format.link(sink))
        pipeline = Gst.Pipeline()
        src = Gst.ElementFactory.make("appsrc")
        src.props.format = Gst.Format.TIME
        pipeline.add(src)
        pipeline.add(audio)
        self.assertTrue(src.link(audio))
        changes = []

        def event_probe(unused_pad, info):
            event = info.get_event()
            if event.type == Gst.EventType.CAPS:
                changes.append(event.parse_caps().copy())
            return Gst.PadProbeReturn.OK

        output_format.get_static_pad("src").add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM, event_probe)
        try:
            pipeline.set_state(Gst.State.PLAYING)
            # A mono music source, stereo video audio and a float mix.
            formats = (("F32LE", 44100, 1, 4), ("S16LE", 48000, 2, 2),
                       ("F64LE", 48000, 2, 8))
            for index, (fmt, rate, channels, size) in enumerate(formats):
                caps = Gst.Caps.from_string(
                    "audio/x-raw,format=%s,layout=interleaved,rate=%d,channels=%d"
                    % (fmt, rate, channels))
                buffer = Gst.Buffer.new_allocate(None, rate // 10 * channels * size, None)
                buffer.memset(0, 0, buffer.get_size())
                buffer.pts = index * Gst.SECOND // 10
                buffer.duration = Gst.SECOND // 10
                sample = Gst.Sample.new(buffer, caps, None, None)
                self.assertEqual(src.emit("push-sample", sample), Gst.FlowReturn.OK)
            src.emit("end-of-stream")
            samples = 0
            while True:
                sample = sink.emit("try-pull-sample", 5 * Gst.SECOND)
                if sample is None:
                    break
                caps = sample.get_caps().get_structure(0)
                self.assertEqual(caps.get_string("format"), "S16LE")
                self.assertEqual(caps.get_string("layout"), "interleaved")
                self.assertEqual(caps.get_int("rate"), (True, 48000))
                self.assertEqual(caps.get_int("channels"), (True, 2))
                samples += 1
            self.assertGreaterEqual(samples, 3)
            self.assertEqual(len(changes), 1)
            self.assertIsNone(pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR))
        finally:
            pipeline.set_state(Gst.State.NULL)
            pipe.release()

    def test_preview_size(self):
        """Checks the viewer gets frames as big as shown, not as the project."""
        ges_timeline = GES.Timeline.new()
        track = GES.VideoTrack.new()
        self.assertTrue(ges_timeline.add_track(track))
        track.set_restriction_caps(Gst.Caps.from_string("video/x-raw,width=1080,height=1920"))
        pipe = Pipeline(app=common.create_pitivi_mock())
        pipe.set_timeline(ges_timeline)
        size = Gst.ElementFactory.make("capsfilter", None)
        widget = mock.Mock()
        widget.get_scale_factor.return_value = 2
        allocation = mock.Mock(width=400, height=500)

        pipe._Pipeline__preview_size_allocate_cb(widget, allocation, size)
        # 1000 pixels high on the screen, the project keeps its shape.
        structure = size.props.caps.get_structure(0)
        self.assertEqual((structure.get_int("width")[1], structure.get_int("height")[1]), (562, 1000))

        # Never bigger than the project.
        allocation = mock.Mock(width=1000, height=2000)
        pipe._Pipeline__preview_size_allocate_cb(widget, allocation, size)
        structure = size.props.caps.get_structure(0)
        self.assertEqual((structure.get_int("width")[1], structure.get_int("height")[1]), (1080, 1920))
