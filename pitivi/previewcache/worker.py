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
"""The process rendering the pieces of the prepared preview.

Run as: python3 -m pitivi.previewcache.worker JOB.json

The job tells the saved project, the folder, the size and the pieces. The
timeline plays as fast as it can into appsinks, from the start of each run
of consecutive pieces, and the frames and the sound are cut at the edges
of the pieces and encoded each piece in its own file, keeping the times of
the timeline: played one after the other they make one stream. Each file
is written with a temporary name and renamed when complete, then
"READY <key> <seconds taken>" is printed.

GES ignores the seeks of a pipeline in render mode, and the muxers refuse
them, hence the appsinks.
"""
import json
import os
import sys
import threading
import time

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GES", "1.0")
from gi.repository import GES  # noqa: E402 pylint: disable=wrong-import-position
from gi.repository import GLib  # noqa: E402 pylint: disable=wrong-import-position
from gi.repository import Gst  # noqa: E402 pylint: disable=wrong-import-position

AUDIO_CAPS = "audio/x-raw,format=S16LE,layout=interleaved,rate=48000,channels=2"
AUDIO_FRAME_BYTES = 4
AUDIO_RATE = 48000
# Giving up when nothing is rendered for this long.
STALL_SECONDS = 15


class PieceWriter:
    """Encodes the frames and the sound of one piece into its file."""

    def __init__(self, folder, chunk, video_caps):
        self.chunk = chunk
        self.path = os.path.join(folder, chunk[2] + ".mkv")
        self.partial = self.path + ".part"
        self.pipeline = Gst.parse_launch(
            "appsrc name=v format=time ! queue ! videoconvert ! "
            "x264enc speed-preset=ultrafast tune=zerolatency key-int-max=15 pass=quant quantizer=24 ! "
            "h264parse ! matroskamux name=m ! filesink name=f "
            "appsrc name=a format=time ! queue ! audioconvert ! %s ! m." % AUDIO_CAPS)
        self.pipeline.get_by_name("f").props.location = self.partial
        self.video = self.pipeline.get_by_name("v")
        if video_caps is not None:
            self.video.props.caps = video_caps
        self.audio = self.pipeline.get_by_name("a")
        self.audio.props.caps = Gst.Caps.from_string(AUDIO_CAPS)
        for src in (self.video, self.audio):
            src.props.max_bytes = 64 * 1024 * 1024
            src.props.block = True
        self.pipeline.set_state(Gst.State.PLAYING)

    def finish(self) -> bool:
        self.video.emit("end-of-stream")
        self.audio.emit("end-of-stream")
        message = self.pipeline.get_bus().timed_pop_filtered(
            30 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
        self.pipeline.set_state(Gst.State.NULL)
        if not message or message.type != Gst.MessageType.EOS:
            if os.path.exists(self.partial):
                os.unlink(self.partial)
            return False
        os.replace(self.partial, self.path)
        return True


class Worker:
    """Renders runs of consecutive pieces of the timeline."""

    def __init__(self, job):
        self.job = job
        self.folder = job["dir"]
        self.width, self.height = job["width"], job["height"]
        self.loop = GLib.MainLoop()
        self.timeline = None
        self.pipeline = None
        self.frame_duration = Gst.SECOND // 30
        self.lock = threading.Lock()
        self.run = []
        self.writers = {}
        self.reached = {}
        self.armed = False

    def load(self):
        path = self.job["xges"]
        factor = self.job.get("scale", 1)
        if factor != 1:
            # pylint: disable=import-outside-toplevel
            from pitivi.previewcache.scale import scale_xges
            with open(path, encoding="utf-8") as xges:
                text = scale_xges(xges.read(), self.job["project_width"], self.job["project_height"], factor)
            path = path[:-len(".xges")] + "-escala.xges"
            with open(path, "w", encoding="utf-8") as xges:
                xges.write(text)
        project = GES.Project.new(Gst.filename_to_uri(path))
        loaded = []
        project.connect("loaded", lambda *unused: (loaded.append(True), self.loop.quit()))
        project.connect("error-loading", lambda *unused: self.loop.quit())
        # A file gone since: without it, as GES leaves it.
        project.connect("missing-uri", lambda *unused: None)
        self.timeline = project.extract()
        timeout = GLib.timeout_add_seconds(60, self.loop.quit)
        self.loop.run()
        GLib.source_remove(timeout) if loaded else None
        if not loaded:
            print("ERROR the project did not load", flush=True)
            sys.exit(1)
        # As when the project loads in the editor.
        # pylint: disable=import-outside-toplevel
        from pitivi.clip_properties.overlay import restore_overlays
        from pitivi.utils.blurfill import restore_blur_fills
        from pitivi.utils.layeractive import watch_timeline
        from pitivi.utils.motion import restore_motion
        restore_blur_fills(self.timeline)
        restore_motion(self.timeline)
        restore_overlays(self.timeline)
        watch_timeline(self.timeline)
        self.timeline.commit_sync()

        for track in self.timeline.get_tracks():
            if track.props.track_type == GES.TrackType.VIDEO:
                caps = track.props.restriction_caps
                if caps and not caps.is_empty():
                    res, num, denom = caps.get_structure(0).get_fraction("framerate")
                    if res and num:
                        self.frame_duration = Gst.SECOND * denom // num

    def make_pipeline(self):
        self.pipeline = GES.Pipeline()
        self.pipeline.set_timeline(self.timeline)
        video = Gst.parse_bin_from_description(
            "videoconvert ! videoscale ! video/x-raw,format=I420,width=%d,height=%d,"
            "pixel-aspect-ratio=1/1,colorimetry=bt709 ! appsink name=s sync=false max-buffers=4"
            % (self.width, self.height), True)
        audio = Gst.parse_bin_from_description(
            "audioconvert ! audioresample ! %s ! appsink name=s sync=false max-buffers=32" % AUDIO_CAPS, True)
        self.pipeline.preview_set_video_sink(video)
        self.pipeline.preview_set_audio_sink(audio)
        for bin_, callback in ((video, self.__video_cb), (audio, self.__audio_cb)):
            sink = bin_.get_by_name("s")
            sink.props.emit_signals = True
            sink.connect("new-sample", callback)
        self.has_audio = any(track.props.track_type == GES.TrackType.AUDIO
                             for track in self.timeline.get_tracks())

    def __writer(self, index, video_caps=None):
        with self.lock:
            writer = self.writers.get(index)
            if writer is None:
                caps = video_caps or self.video_caps
                writer = PieceWriter(self.folder, self.run[index], caps)
                self.writers[index] = writer
            return writer

    def __index_at(self, position):
        for index, chunk in enumerate(self.run):
            if chunk[0] <= position < chunk[1]:
                return index
        return None

    # The streaming threads.

    def __video_cb(self, sink):
        sample = sink.emit("pull-sample")
        if not sample or not self.armed:
            return Gst.FlowReturn.OK
        buffer = sample.get_buffer()
        self.video_caps = sample.get_caps()
        # NLE gives a frame again when it builds a new stack.
        if buffer.pts < self.reached["video"]:
            return Gst.FlowReturn.OK
        # The frame belongs to the piece where its middle is.
        index = self.__index_at(buffer.pts + self.frame_duration // 2)
        if index is not None:
            out = buffer.copy_deep()
            out.dts = Gst.CLOCK_TIME_NONE
            writer = self.__writer(index, self.video_caps)
            if writer.video.props.caps is None:
                writer.video.props.caps = self.video_caps
            writer.video.emit("push-buffer", out)
        self.reached["video"] = max(self.reached["video"], buffer.pts + self.frame_duration // 2)
        return Gst.FlowReturn.OK

    def __audio_cb(self, sink):
        sample = sink.emit("pull-sample")
        if not sample or not self.armed:
            return Gst.FlowReturn.OK
        buffer = sample.get_buffer()
        ok, info = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        data = bytes(info.data)
        buffer.unmap(info)
        # The samples, in the time of the timeline.
        sample_pos = round(buffer.pts * AUDIO_RATE / Gst.SECOND)
        frames = len(data) // AUDIO_FRAME_BYTES
        offset = 0
        while offset < frames:
            position = (sample_pos + offset) * Gst.SECOND // AUDIO_RATE
            index = self.__index_at(position)
            if index is None:
                break
            edge = round(self.run[index][1] * AUDIO_RATE / Gst.SECOND)
            take = min(frames - offset, max(1, edge - sample_pos - offset))
            piece = Gst.Buffer.new_wrapped(data[offset * AUDIO_FRAME_BYTES:(offset + take) * AUDIO_FRAME_BYTES])
            piece.pts = position
            piece.duration = take * Gst.SECOND // AUDIO_RATE
            self.__writer(index).audio.emit("push-buffer", piece)
            offset += take
        end = (sample_pos + frames) * Gst.SECOND // AUDIO_RATE
        self.reached["audio"] = max(self.reached["audio"], end)
        return Gst.FlowReturn.OK

    # The main thread.

    def render_run(self, run) -> bool:
        self.run = run
        self.writers = {}
        self.video_caps = None
        self.armed = False
        self.reached = {"video": run[0][0], "audio": run[0][0] if self.has_audio else float("inf")}
        # Bounded waits: after a run the sound may have reached the end of
        # the timeline, and pausing never completes.
        self.pipeline.set_state(Gst.State.PAUSED)
        self.pipeline.get_state(5 * Gst.SECOND)
        self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, run[0][0])
        self.pipeline.get_state(10 * Gst.SECOND)
        self.armed = True
        self.pipeline.set_state(Gst.State.PLAYING)
        bus = self.pipeline.get_bus()
        finished = 0
        eos = False
        progress = (dict(self.reached), time.monotonic())
        # The time taken by each piece, for the automatic quality.
        last_ready = time.monotonic()
        while finished < len(run):
            message = bus.timed_pop_filtered(20 * Gst.MSECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
            if message and message.type == Gst.MessageType.ERROR:
                print("ERROR", message.parse_error()[0].message, flush=True)
                self.armed = False
                return False
            # Nothing comes, for example a file of the project is gone.
            if self.reached != progress[0]:
                progress = (dict(self.reached), time.monotonic())
            elif time.monotonic() - progress[1] > STALL_SECONDS:
                print("ERROR nothing rendered for %d s" % STALL_SECONDS, flush=True)
                self.armed = False
                return False
            eos = eos or bool(message)
            # A piece is complete when the frames and the sound went past it.
            while finished < len(run) and (eos or min(self.reached.values()) >= run[finished][1]):
                with self.lock:
                    writer = self.writers.pop(finished, None)
                if writer and writer.finish():
                    now = time.monotonic()
                    print("READY %s %.3f" % (writer.chunk[2], now - last_ready), flush=True)
                    last_ready = now
                finished += 1
        self.armed = False
        self.pipeline.set_state(Gst.State.PAUSED)
        return True

    def main(self):
        self.load()
        self.make_pipeline()
        # Consecutive pieces are rendered in one go.
        runs = []
        for chunk in self.job["chunks"]:
            chunk = tuple(chunk)
            if runs and runs[-1][-1][1] == chunk[0]:
                runs[-1].append(chunk)
            else:
                runs.append([chunk])
        for run in runs:
            if not self.render_run(run):
                break
        self.pipeline.set_state(Gst.State.NULL)
        print("DONE", flush=True)


def init():
    """Prepares GStreamer and the elements of the effects, without GTK."""
    # pylint: disable=import-outside-toplevel
    import gi
    for namespace in ("Gst", "GES", "GstController", "GstBase", "GstVideo", "GstPbutils", "GstApp"):
        gi.require_version(namespace, "1.0")
    Gst.init(None)
    GES.init()
    from pitivi.utils import blurfilter, kenburns, particlesfilter, shapefilter, speedfilter, splittee
    for module in (kenburns, blurfilter, splittee, speedfilter, shapefilter, particlesfilter):
        module.register()
    # As pitivi.check.initialize_modules does.
    from gi.repository import GstPbutils
    from pitivi.utils.misc import video_info_get_natural_height
    from pitivi.utils.misc import video_info_get_natural_width
    from pitivi.utils.misc import video_info_get_rotation
    GstPbutils.DiscovererVideoInfo.get_natural_width = video_info_get_natural_width
    GstPbutils.DiscovererVideoInfo.get_natural_height = video_info_get_natural_height
    GstPbutils.DiscovererVideoInfo.get_rotation = video_info_get_rotation


def main():
    init()
    with open(sys.argv[1], encoding="utf-8") as job_file:
        job = json.load(job_file)
    Worker(job).main()


if __name__ == "__main__":
    main()
