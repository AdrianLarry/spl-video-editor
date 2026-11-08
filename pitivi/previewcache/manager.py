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
from pitivi.previewcache.chunks import missing_from
from pitivi.utils.loggable import Loggable

# After an edit, waiting for the next one before rendering.
QUIET_MS = 1500
# The longer side of the rendered frames.
MAX_SIDE = 1280
# The pieces kept, the oldest used are removed beyond.
MAX_CACHE_BYTES = 2 * 1024 * 1024 * 1024
# SPL_VISTA_PREPARADA=0 turns it off.
ENABLED = os.environ.get("SPL_VISTA_PREPARADA", "1") != "0"


def cache_folder() -> str:
    folder = os.path.join(GLib.get_user_cache_dir(), "pitivi", "spl-vista-preparada")
    os.makedirs(folder, exist_ok=True)
    return folder


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
        self.output = b""
        prune(self.folder)

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
        if self.up_to_date:
            self.up_to_date = False
            self.emit("changed")
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

    def frame_size(self) -> Tuple[int, int]:
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
        fit = min(1, MAX_SIDE / max(width, height))
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
        self.size = self.frame_size()
        self.chunks = compute_chunks(text, "%dx%d" % self.size)
        self.ready = {}
        for chunk in self.chunks:
            path = self.path(chunk.key)
            if os.path.exists(path):
                self.ready[chunk.key] = path
                os.utime(path)
        self.up_to_date = True
        self.emit("changed")

        position = self.pipeline.get_position(fails=False) or 0
        missing = missing_from(self.chunks, self.ready, position)
        keys = [chunk.key for chunk in missing]
        if self.process and keys == self.job_keys:
            return
        self.stop_process()
        if not missing:
            return
        job = {"xges": snapshot, "dir": self.folder, "width": self.size[0], "height": self.size[1],
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
            if len(words) == 2 and words[0] == "READY":
                key = words[1]
                if self.up_to_date and any(chunk.key == key for chunk in self.chunks):
                    self.ready[key] = self.path(key)
                    self.emit("changed")
            elif words and words[0] == "ERROR":
                self.warning("The prepared preview failed: %s", line)
        return True

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

    def files_from(self, position: int) -> Optional[Tuple[List[str], int]]:
        """Returns the files from the position to the end, and where they start.

        None unless the timeline did not change since and all are ready.
        """
        if not self.up_to_date or not self.chunks:
            return None
        index = chunk_at(self.chunks, position)
        if index is None:
            return None
        chunks = self.chunks[index:]
        if any(chunk.key not in self.ready for chunk in chunks):
            return None
        return [self.ready[chunk.key] for chunk in chunks], chunks[0].start
