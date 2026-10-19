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
"""Tests for the pitivi.export module."""
import os
import tempfile
from unittest import mock
from unittest import skipUnless

from gi.repository import GES
from gi.repository import GLib
from gi.repository import Gst
from gi.repository import Gtk

from pitivi.export import estimate_size
from pitivi.export import ExportDialog
from pitivi.export import format_duration
from pitivi.export import format_size
from pitivi.export import get_file_format
from pitivi.export import get_unique_path
from pitivi.export import HIGH
from pitivi.export import MP4
from pitivi.export import STANDARD
from tests import common

HAS_MP4 = all(Gst.ElementFactory.find(name) for name in MP4[1:])


class ExportHelpersTest(common.TestCase):
    """Tests for the helpers of the export dialog."""

    def test_file_format(self):
        if HAS_MP4:
            self.assertEqual(get_file_format(), MP4)
        self.assertIsNotNone(get_file_format())

    def test_size(self):
        minute = 60 * Gst.SECOND
        standard = estimate_size(1920, 1080, 30, minute, STANDARD)
        high = estimate_size(1920, 1080, 30, minute, HIGH)
        self.assertLess(standard, high)
        self.assertEqual(format_size(standard), "48 MB")
        self.assertEqual(format_size(100000), "less than 1 MB")
        self.assertEqual(format_duration(48 * Gst.SECOND), "0:48")

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = get_unique_path(folder, "Vacaciones", "mp4")
            self.assertEqual(path, os.path.join(folder, "Vacaciones.mp4"))
            open(path, "w").close()
            self.assertEqual(get_unique_path(folder, "Vacaciones", "mp4"),
                             os.path.join(folder, "Vacaciones (2).mp4"))


class ExportDialogTest(common.TestCase):
    """Tests for exporting the video."""

    @skipUnless(HAS_MP4, "The MP4 encoders are not installed")
    @common.setup_timeline
    def test_export(self):
        self._wait_until_project_loaded()
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("flat_colour1_640x480.png"))
        self.layer.add_asset(asset, 0, 0, Gst.SECOND, GES.TrackType.UNKNOWN)
        self.project.pipeline.commit_timeline()

        with tempfile.TemporaryDirectory() as folder:
            self.app.settings.lastExportFolder = folder
            dialog = ExportDialog(self.app, self.project)
            dialog.name_entry.set_text("Mi video")
            self.assertTrue(dialog.export_button.get_sensitive())
            dialog.quality_buttons[HIGH].set_active(True)

            mainloop = common.create_main_loop()
            # The main window is a mock in the tests.
            for patcher in (mock.patch.object(Gtk.Window, "set_transient_for"),
                            mock.patch.object(self.app, "simple_inhibit"),
                            mock.patch.object(self.app, "simple_uninhibit")):
                patcher.start()
                self.addCleanup(patcher.stop)
            dialog.stack.connect("notify::visible-child-name",
                                 lambda stack, unused: stack.get_visible_child_name() == "done" and mainloop.quit())
            dialog.export_button.clicked()
            self.assertEqual(dialog.stack.get_visible_child_name(), "progress")
            mainloop.run(timeout_seconds=60)

            path = os.path.join(folder, "Mi video.mp4")
            self.assertEqual(dialog.path, path)
            self.assertEqual(dialog.done_label.get_text(), path)
            self.assertIsNone(dialog.engine)
            info = GES.UriClipAsset.request_sync(Gst.filename_to_uri(path)).get_info()
            caps = info.get_video_streams()[0].get_caps().to_string()
            self.assertIn("video/x-h264", caps)
            # The editing goes on in the viewer.
            self.assertFalse(self.project.pipeline.rendering())
            GLib.idle_add(dialog.destroy)

    def test_invalid_name(self):
        app = common.create_pitivi_mock()
        from pitivi.project import ProjectManager
        app.project_manager = ProjectManager(app)
        project = app.project_manager.new_blank_project()
        dialog = ExportDialog(app, project)
        dialog.name_entry.set_text("")
        self.assertFalse(dialog.export_button.get_sensitive())
        dialog.name_entry.set_text("a/b")
        self.assertFalse(dialog.export_button.get_sensitive())
        dialog.name_entry.set_text("Vacaciones")
        self.assertEqual(dialog.export_button.get_sensitive(), bool(get_file_format()))
