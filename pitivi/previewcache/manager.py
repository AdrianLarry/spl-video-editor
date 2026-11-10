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
"""When the pieces of the prepared preview are rendered, which are ready."""
import json
import os
import signal
import subprocess
import sys
from typing import List
from typing import Optional
from typing import Tuple

from gi.repository import GES
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gst

from pitivi.previewcache.chunks import chunk_at
from pitivi.previewcache.chunks import compute_chunks
from pitivi.previewcache.chunks import lead_needed
from pitivi.previewcache.chunks import missing_from
from pitivi.previewcache.quality import AUTO
from pitivi.previewcache.quality import AutoQuality
from pitivi.previewcache.quality import FACTORS
from pitivi.previewcache.quality import HIGH
from pitivi.previewcache.scale import can_scale
from pitivi.utils.loggable import Loggable

# After an edit, waiting for the next one before rendering.
QUIET_MS = 1500
# The longer side of the rendered frames.
MAX_SIDE = 1280
# The pieces kept, the oldest used are removed beyond.
MAX_CACHE_BYTES = 2 * 1024 * 1024 * 1024
# Pieces ready ahead of the playhead to play the prepared preview.
MIN_AHEAD = 2
# The time taken to prepare a second of video, until measured, and more
# to be sure: while playing the computer prepares slower.
DEFAULT_RATE = 1.0
RATE_MARGIN = 1.2
# The pieces measured for the rate, the slowest counts: a transition or a
# blur takes several times longer than a photo.
RATE_PIECES = 6
# When all is prepared in less time, it plays once ready: going on with
# more pieces stops playing for a moment.
WAIT_ALL_SECONDS = 10
# SPL_VISTA_PREPARADA=0 turns it off.
ENABLED = os.environ.get("SPL_VISTA_PREPARADA", "1") != "0"


def cache_folder() -> str:
    # pylint: disable=import-outside-toplevel
    from pitivi.settings import xdg_cache_home
    return xdg_cache_home("spl-vista-preparada")


def prune(folder: str, limit: int = MAX_CACHE_BYTES) -> None:
    """Removes the pieces used least recently beyond the limit."""
    entries = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if name.endswith(".part") or name.endswith(".xges") or name.endswith(".json"):
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        entries.append((max(stat.st_atime, stat.st_mtime), stat.st_size, path))
    total = sum(size for unused, size, unused in entries)
    for unused, size, path in sorted(entries):
        if total <= limit:
            break
        try:
            os.unlink(path)
            total -= size
        except OSError:
            pass


class PreparedPreview(GObject.Object, Loggable):
    """Renders the pieces of the timeline in another process.

    Signals:
        changed: Pieces got ready or stopped being up to date.
    """

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, pipeline):
        GObject.Object.__init__(self)
        Loggable.__init__(self)
        self.pipeline = pipeline
        self.timeline = None
        self.folder = cache_folder()
        self.chunks = []
        self.ready = {}
        self.size = (0, 0)
        self.up_to_date = False
        self.process = None
        self.watch_id = 0
        self.timer_id = 0
        self.job_keys = []
        self.job_started = 0
        self.dirty = False
        self.quality = None
        # Measured times taken to prepare a second of video.
        self.rates = []
        # Whether the last update changed what the pieces show.
        self.content_changed = False
        self.output = b""
        self.snapshot = None
        self.project_size = (0, 0)
        self.factor = 1.0
        settings = getattr(getattr(pipeline, "app", None), "settings", None)
        self.settings = settings if hasattr(settings, "previewQuality") else None
        self.auto = AutoQuality(self.settings.previewAutoLevel if self.settings else HIGH)
        if self.settings:
            self.settings.connect("previewQualityChanged", self.__quality_changed_cb)
        prune(self.folder)

    def __quality_changed_cb(self, unused_settings):
        self.up_to_date = False
        self.emit("changed")
        self.__schedule()

    def level(self, text: str) -> str:
        """Returns the quality used for the saved project."""
        chosen = self.settings.previewQuality if self.settings else HIGH
        level = self.auto.level if chosen == AUTO else chosen
        if level not in FACTORS or (FACTORS[level] != 1 and not can_scale(text)):
            return HIGH
        return level

    def set_timeline(self, timeline: Optional[GES.Timeline]):
        if self.timeline:
            self.timeline.disconnect_by_func(self.__commited_cb)
        self.stop_process()
        self.timeline = timeline
        self.up_to_date = False
        if timeline:
            timeline.connect("commited", self.__commited_cb)
            self.__schedule()

    def release(self):
        self.set_timeline(None)
        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = 0
        for name in ("proyecto-%d.xges" % os.getpid(), "trabajo-%d.json" % os.getpid()):
            try:
                os.unlink(os.path.join(self.folder, name))
            except OSError:
                pass

    def __commited_cb(self, timeline):
        # Emitted in the thread of NLE when the commit completes there.
        GLib.idle_add(self.__commited_main_cb, timeline)

    def __commited_main_cb(self, timeline):
        if timeline is not self.timeline:
            return False
        # Not played until saved again: maybe edited. NLE also commits
        # without edits, then the pieces stay the same.
        self.dirty = True
        self.__schedule()
        return False

    def __schedule(self):
        if not ENABLED:
            return
        if self.timer_id:
            GLib.source_remove(self.timer_id)
        self.timer_id = GLib.timeout_add(QUIET_MS, self.__quiet_cb)

    def __quiet_cb(self):
        self.timer_id = 0
        if not self.timeline:
            return False
        if self.pipeline.rendering():
            # Exporting, the computer is busy.
            self.stop_process()
            self.__schedule()
            return False
        try:
            self.update()
        except Exception as e:  # pylint: disable=broad-except
            self.warning("Could not prepare the preview: %s", e)
        return False

    def project_frame_size(self) -> Tuple[int, int]:
        width, height = 1080, 1920
        for track in self.timeline.get_tracks():
            if track.props.track_type == GES.TrackType.VIDEO:
                caps = track.props.restriction_caps
                if caps and not caps.is_empty():
                    structure = caps.get_structure(0)
                    res_w, w = structure.get_int("width")
                    res_h, h = structure.get_int("height")
                    if res_w and res_h and w > 0 and h > 0:
                        width, height = w, h
        return width, height

    def frame_size(self) -> Tuple[int, int]:
        """Returns the size of the rendered frames."""
        width, height = self.project_size
        fit = min(1, MAX_SIDE / max(width, height), self.factor)
        return max(2, round(width * fit / 2) * 2), max(2, round(height * fit / 2) * 2)

    def update(self):
        """Saves the timeline, and renders the pieces not ready."""
        # pylint: disable=import-outside-toplevel
        from pitivi.utils.transitions import sync_saved_types
        project = self.timeline.get_asset()
        snapshot = os.path.join(self.folder, "proyecto-%d.xges" % os.getpid())
        sync_saved_types(self.timeline)
        # Saved by GES, not by the project of Pitivi, which also saves the
        # settings of the encoders.
        # Saving sets metas, which are not edits to undo.
        action_log = getattr(getattr(self.pipeline, "app", None), "action_log", None)
        running = action_log.running if action_log else False
        if action_log:
            action_log.running = True
        try:
            saved = GES.Project.save(project, self.timeline, Gst.filename_to_uri(snapshot), None, True)
        finally:
            if action_log:
                action_log.running = running
        if not saved:
            self.warning("Could not save the timeline for the prepared preview")
            return
        with open(snapshot, encoding="utf-8") as xges:
            text = xges.read()
        self.snapshot = snapshot
        self.project_size = self.project_frame_size()
        self.factor = FACTORS[self.level(text)]
        self.size = self.frame_size()
        old_keys = [chunk.key for chunk in self.chunks]
        quality = "%dx%d@%.3f" % (self.size + (self.factor,))
        self.chunks = compute_chunks(text, quality)
        # Another quality is not an edit: what plays goes on.
        changed = old_keys != [chunk.key for chunk in self.chunks] and quality == self.quality
        self.quality = quality
        self.ready = {}
        for chunk in self.chunks:
            path = self.path(chunk.key)
            if os.path.exists(path):
                self.ready[chunk.key] = path
                os.utime(path)
        self.up_to_date = True
        self.dirty = False
        self.content_changed = changed
        self.emit("changed")
        self.content_changed = False
        self.prioritize(self.pipeline.get_position(fails=False) or 0, force=True)

    def prioritize(self, position: int, force: bool = False):
        """Renders first the pieces missing from the position."""
        if not self.up_to_date or not self.snapshot:
            return
        missing = missing_from(self.chunks, self.ready, position)
        keys = [chunk.key for chunk in missing]
        pending = [key for key in self.job_keys if key not in self.ready]
        if self.process and (keys == pending or (not force and (not keys or keys[0] in pending[:2]))):
            # Going on: the same pieces, or the next missing one soon.
            return
        self.debug("Rendering from %s: %d missing, force %s", position, len(missing), force)
        self.stop_process()
        if not missing:
            return
        job = {"xges": self.snapshot, "dir": self.folder, "width": self.size[0], "height": self.size[1],
               "scale": self.factor, "project_width": self.project_size[0],
               "project_height": self.project_size[1],
               "chunks": [list(chunk) for chunk in missing]}
        job_path = os.path.join(self.folder, "trabajo-%d.json" % os.getpid())
        with open(job_path, "w", encoding="utf-8") as job_file:
            json.dump(job, job_file)
        self.start_process(job_path, keys)

    def path(self, key: str) -> str:
        return os.path.join(self.folder, key + ".mkv")

    def start_process(self, job_path: str, keys: List[str]):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(path for path in sys.path if path)
        self.process = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, "-m", "pitivi.previewcache.worker", job_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
            preexec_fn=lambda: os.nice(10))
        self.job_keys = keys
        self.output = b""
        self.watch_id = GLib.io_add_watch(self.process.stdout.fileno(), GLib.PRIORITY_DEFAULT,
                                          GLib.IOCondition.IN | GLib.IOCondition.HUP,
                                          self.__output_cb, self.process)
        self.info("Preparing %d of %d pieces of the preview", len(keys), len(self.chunks))

    def __output_cb(self, fd, condition, process):
        if process is not self.process:
            return False
        data = os.read(fd, 4096) if condition & GLib.IOCondition.IN else b""
        if not data:
            self.__process_ended()
            return False
        self.output += data
        while b"\n" in self.output:
            line, self.output = self.output.split(b"\n", 1)
            words = line.decode(errors="replace").split()
            if len(words) >= 2 and words[0] == "READY":
                key = words[1]
                chunk = next((chunk for chunk in self.chunks if chunk.key == key), None)
                if self.up_to_date and chunk:
                    self.ready[key] = self.path(key)
                    self.emit("changed")
                    if len(words) == 3:
                        seconds = float(words[2])
                        duration = (chunk.end - chunk.start) / Gst.SECOND
                        if duration > 0:
                            self.rates = (self.rates + [seconds / duration])[-RATE_PIECES:]
                        self.debug("Piece at %s prepared in %.2f s", chunk.start, seconds)
                        self.__measured(seconds, duration)
            elif words and words[0] == "ERROR":
                self.warning("The prepared preview failed: %s", line)
        return True

    def __measured(self, seconds: float, duration: float):
        if not self.settings or self.settings.previewQuality != AUTO:
            return
        level = self.auto.add(seconds, duration)
        if level:
            self.info("The preview is prepared now in quality %s", level)
            self.settings.previewAutoLevel = level
            # What plays goes on, the next pieces in the new quality.
            self.__schedule()

    def __process_ended(self):
        process = self.process
        self.process = None
        self.watch_id = 0
        self.job_keys = []
        if process:
            process.wait()
            self.debug("The process preparing the preview ended: %s", process.returncode)

    def stop_process(self):
        if not self.process:
            return
        process = self.process
        self.process = None
        if self.watch_id:
            GLib.source_remove(self.watch_id)
            self.watch_id = 0
        keys = self.job_keys
        self.job_keys = []
        try:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait()
        # Another editor may be rendering in the folder: only ours.
        for key in keys:
            try:
                os.unlink(self.path(key) + ".part")
            except OSError:
                pass

    def files_from(self, position: int) -> Optional[Tuple[List[str], int, int]]:
        """Returns the ready files from the position, where they start and end.

        None unless the timeline did not change since and enough is ready:
        MIN_AHEAD pieces, or the ones to the end.
        """
        if not self.up_to_date or self.dirty or not self.chunks:
            return None
        index = chunk_at(self.chunks, position)
        if index is None:
            return None
        chunks = []
        for chunk in self.chunks[index:]:
            if chunk.key not in self.ready:
                break
            chunks.append(chunk)
        to_end = len(chunks) == len(self.chunks) - index
        if not chunks or (len(chunks) < MIN_AHEAD and not to_end):
            return None
        return [self.ready[chunk.key] for chunk in chunks], chunks[0].start, chunks[-1].end

    def ready_to_play(self, position: int) -> bool:
        """Whether playing from the position goes on to the end without waiting.

        When the pieces missing are prepared slower than they play, more
        must be ready ahead before starting.
        """
        found = self.files_from(position)
        if not found:
            return False
        unused_files, start, end = found
        if end >= self.end() or not self.rendering():
            return True
        missing = sum(chunk.end - chunk.start for chunk in self.chunks
                      if chunk.end > end and chunk.key not in self.ready)
        rate = max(self.rates or [DEFAULT_RATE]) * RATE_MARGIN
        if missing * rate <= WAIT_ALL_SECONDS * Gst.SECOND:
            # Soon all ready.
            return False
        return end - max(position, start) >= lead_needed(rate, missing)

    def end(self) -> int:
        return self.chunks[-1].end if self.chunks else 0

    def rendering(self) -> bool:
        """Whether pieces are being rendered."""
        return self.process is not None
