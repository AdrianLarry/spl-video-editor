# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2020, Guy Richard <guy.richard99@gmail.com>
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
"""Tests for the pitivi.viewer.viewer module."""
# pylint: disable=protected-access
import locale

from gi.repository import Gst

from pitivi.project import ProjectManager
from pitivi.viewer.viewer import format_time
from pitivi.viewer.viewer import ViewerContainer
from tests import common


class TestViewerContainer(common.TestCase):

    def test_toggle_safe_areas_action(self):
        """Checks the effect of the toggle_safe_areas_action."""
        app = common.create_pitivi_mock()
        app.project_manager = ProjectManager(app)
        viewer_container = ViewerContainer(app)

        project = app.project_manager.new_blank_project()
        viewer_container.set_project(project)
        self.assertFalse(viewer_container.overlay_stack.safe_areas_overlay.get_visible())

        viewer_container.toggle_safe_areas_action.activate()
        self.assertTrue(viewer_container.overlay_stack.safe_areas_overlay.get_visible())

        viewer_container.toggle_safe_areas_action.activate()
        self.assertFalse(viewer_container.overlay_stack.safe_areas_overlay.get_visible())

    def test_format_and_time(self):
        """Checks the format and the time shown with the controls."""
        app = common.create_pitivi_mock()
        app.project_manager = ProjectManager(app)
        viewer_container = ViewerContainer(app)
        project = app.project_manager.new_blank_project()
        viewer_container.set_project(project)

        def get_active():
            return [kind for kind, button in viewer_container.format_buttons.buttons.items()
                    if button.get_active()]

        self.assertEqual(get_active(), ["horizontal"])
        self.assertEqual(viewer_container.format_label.get_text(), "Horizontal · 16:9")

        project.set_video_properties(1080, 1920, project.videorate)
        self.assertEqual(get_active(), ["vertical"])
        self.assertEqual(viewer_container.format_label.get_text(), "Vertical · 9:16")

        # An old project with another shape.
        project.set_video_properties(640, 480, project.videorate)
        self.assertEqual(get_active(), [])
        self.assertEqual(viewer_container.format_label.get_text(), "640 × 480")

        point = locale.localeconv()["decimal_point"]
        viewer_container._duration_changed_cb(None, 90 * Gst.SECOND)
        viewer_container._position_cb(None, 65 * Gst.SECOND + 360 * Gst.MSECOND)
        self.assertEqual(viewer_container.time_label.get_text(),
                         "01:05%s3 / 01:30%s0" % (point, point))

    def test_format_time(self):
        point = locale.localeconv()["decimal_point"]
        self.assertEqual(format_time(0), "00:00%s0" % point)
        self.assertEqual(format_time(-Gst.SECOND), "00:00%s0" % point)
        self.assertEqual(format_time(3725 * Gst.SECOND + 99 * Gst.MSECOND), "1:02:05%s0" % point)

    def test_guides_button(self):
        """Checks the button showing the guides in thirds."""
        app = common.create_pitivi_mock()
        app.project_manager = ProjectManager(app)
        viewer_container = ViewerContainer(app)
        project = app.project_manager.new_blank_project()
        viewer_container.set_project(project)
        overlay = viewer_container.guidelines_popover.overlay
        self.assertFalse(overlay.active_guidelines)

        viewer_container.guides_button.set_active(True)
        self.assertEqual([guideline.name for guideline in overlay.active_guidelines], ["THREE_BY_THREE"])

        # The shortcut updates the button.
        viewer_container.toggle_guidelines_action.activate()
        self.assertFalse(overlay.active_guidelines)
        self.assertFalse(viewer_container.guides_button.get_active())
