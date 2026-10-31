# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2016, Lubosz Sarnecki <lubosz.sarnecki@collabora.co.uk>
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
import numpy
from gi.repository import Gdk
from gi.repository import GES
from gi.repository import GLib
from gi.repository import Gtk

from pitivi.clip_properties.overlay import is_overlay_clip
from pitivi.utils.loggable import Loggable
from pitivi.viewer.clip_toolbar import ClipToolbar
from pitivi.viewer.crop_overlay import CropOverlay
from pitivi.viewer.move_scale_overlay import MoveScaleOverlay
from pitivi.viewer.safe_areas_overlay import SafeAreasOverlay
from pitivi.viewer.shape_overlay import ShapeOverlay
from pitivi.viewer.title_overlay import TitleOverlay


class OverlayStack(Gtk.Overlay, Loggable):
    """Manager for the viewer overlays."""

    def __init__(self, app, sink_widget, guidelines_overlay):
        Gtk.Overlay.__init__(self)
        Loggable.__init__(self)
        self.__overlays = {}
        self.__visible_overlays = []
        self.__hide_all_overlays = False
        self.__last_allocation = None
        self.app = app
        self.window_size = numpy.array([1, 1])
        self.click_position = None
        self.hovered_overlay = None
        self.selected_overlay = None
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                        Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK |
                        Gdk.EventMask.SCROLL_MASK |
                        Gdk.EventMask.ENTER_NOTIFY_MASK |
                        Gdk.EventMask.LEAVE_NOTIFY_MASK |
                        Gdk.EventMask.ALL_EVENTS_MASK)
        self.add(sink_widget)
        self.connect("size-allocate", self.__size_allocate_cb)

        # Whether to show the percent of the size relative to the project size.
        # It is set to false initially because the viewer gets resized
        # while the project is loading and we don't want to show the percent
        # in this case.
        self.__show_resize_status = False
        # ID of resizing timeout callback, so it can be delayed.
        self.__resizing_id = 0
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE)
        self.resize_status = Gtk.Label(name="resize_status")
        self.revealer.add(self.resize_status)
        self.add_overlay(self.revealer)

        self.guidelines_overlay = guidelines_overlay
        self.add_overlay(guidelines_overlay)

        self.safe_areas_overlay = SafeAreasOverlay(self)
        self.add_overlay(self.safe_areas_overlay)

        # SPL: shown while playing waits for the clip edges to be prepared,
        # only if it takes long enough to be noticed.
        self.__preparing_id = 0
        self.preparing_spinner = Gtk.Spinner(name="preparing_spinner",
                                             halign=Gtk.Align.CENTER,
                                             valign=Gtk.Align.CENTER)
        self.preparing_spinner.set_no_show_all(True)
        self.add_overlay(self.preparing_spinner)
        self.set_overlay_pass_through(self.preparing_spinner, True)

        # SPL: cropping the selected clip, from a toolbar over the viewer.
        self.crop_overlay = CropOverlay(self)
        self.add_overlay(self.crop_overlay)
        self.clip_toolbar = ClipToolbar(app, self.crop_overlay)
        self.add_overlay(self.clip_toolbar)

        sink_widget.connect("size-allocate", self.__sink_widget_size_allocate_cb)

    def __size_allocate_cb(self, widget, rectangle):
        self.window_size = numpy.array([rectangle.width,
                                        rectangle.height])
        for overlay in self.__overlays.values():
            overlay.update_from_source()

    def __overlay_for_source(self, source: GES.Source):
        if source in self.__overlays:
            return self.__overlays[source]

        if isinstance(source, GES.TitleSource):
            overlay = TitleOverlay(self, source)
        elif is_overlay_clip(source.get_parent()):
            # SPL: the shape of an overlay.
            overlay = ShapeOverlay(self, self.app.action_log, source)
        else:
            overlay = MoveScaleOverlay(self, self.app.action_log, source)
        self.add_overlay(overlay)
        # SPL: the crop and the toolbar stay on top, the toolbar clickable.
        self.reorder_overlay(self.crop_overlay, -1)
        self.reorder_overlay(self.clip_toolbar, -1)
        self.__overlays[source] = overlay
        return overlay

    def do_event(self, event):
        if self.crop_overlay.active:
            # The crop overlay handles the pointer while cropping.
            return False
        if event.type == Gdk.EventType.BUTTON_RELEASE:
            cursor_position = numpy.array([event.x, event.y])
            if self.click_position is None:
                # SPL: pressed on a widget over the viewer, as the toolbar.
                return False
            self.click_position = None
            if self.selected_overlay:
                self.selected_overlay.on_button_release(cursor_position)
            # reset the cursor if we are outside of the viewer
            if (cursor_position < numpy.zeros(2)).any() or (cursor_position > self.window_size).any():
                self.reset_cursor()
        elif event.type == Gdk.EventType.LEAVE_NOTIFY and event.mode == Gdk.CrossingMode.NORMAL:
            # If we have a click position, the user is dragging, so we don't want to lose focus and return
            if isinstance(self.click_position, numpy.ndarray):
                return False
            for overlay in self.__overlays.values():
                overlay.unhover()
            self.reset_cursor()
        elif event.type == Gdk.EventType.BUTTON_PRESS:
            self.click_position = numpy.array([event.x, event.y])
            if self.hovered_overlay:
                self.hovered_overlay.on_button_press()
            elif self.selected_overlay:
                self.selected_overlay.on_button_press()
        elif event.type == Gdk.EventType.MOTION_NOTIFY:
            cursor_position = numpy.array([event.x, event.y])

            if isinstance(self.click_position, numpy.ndarray):
                if self.selected_overlay:
                    self.selected_overlay.on_motion_notify(cursor_position)
            else:

                # Prioritize Handles
                if isinstance(self.selected_overlay, (MoveScaleOverlay, ShapeOverlay)):
                    if self.selected_overlay.on_hover(cursor_position):
                        if self.selected_overlay.hovered_handle:
                            self.hovered_overlay = self.selected_overlay
                            return False

                for overlay in self.__visible_overlays:
                    if overlay.on_hover(cursor_position):
                        self.hovered_overlay = overlay
                        break
                if not self.hovered_overlay:
                    self.reset_cursor()
        elif event.type == Gdk.EventType.SCROLL:
            # TODO: Viewer zoom
            pass
        return True

    def set_current_sources(self, sources):
        """Sets the sources at the playhead."""
        self.__visible_overlays = []
        # check if source has instanced viewer
        for source in sources:
            overlay = self.__overlay_for_source(source)
            self.__visible_overlays.append(overlay)
        # SPL: the shapes, small and over the video, are hovered first.
        self.__visible_overlays.sort(key=lambda overlay: not isinstance(overlay, ShapeOverlay))
        # check if viewer should be visible
        if not self.__hide_all_overlays and not self.crop_overlay.active:
            for source, overlay in self.__overlays.items():
                if source in sources:
                    overlay.show()
                else:
                    overlay.hide()

    def update(self, source):
        self.__overlays[source].update_from_source()

    def select(self, source):
        """Specifies the selected source between the sources at the playhead."""
        self.clip_toolbar.set_clip(source.get_parent() if source else None)
        if not source:
            self.selected_overlay = None
            return

        self.selected_overlay = self.__overlay_for_source(source)
        self.selected_overlay.queue_draw()

    def set_preparing(self, preparing):
        if self.__preparing_id:
            GLib.source_remove(self.__preparing_id)
            self.__preparing_id = 0
        if preparing:
            self.__preparing_id = GLib.timeout_add(150, self.__show_preparing_cb)
        else:
            self.preparing_spinner.stop()
            self.preparing_spinner.hide()

    def __show_preparing_cb(self):
        self.__preparing_id = 0
        self.preparing_spinner.show()
        self.preparing_spinner.start()
        return False

    def show_source_overlays(self, visible):
        """Shows or hides the overlays of the sources, as while cropping."""
        for overlay in self.__visible_overlays:
            overlay.set_visible(visible and not self.__hide_all_overlays)

    def hide_overlays(self):
        if self.__hide_all_overlays:
            # The overlays are already hidden.
            return

        self.guidelines_overlay.hide()
        for overlay in self.__visible_overlays:
            overlay.hide()
        self.clip_toolbar.stop_cropping()
        self.clip_toolbar.hide()
        self.__hide_all_overlays = True

    def show_overlays(self):
        if not self.__hide_all_overlays:
            # The overlays are already visible.
            return

        self.guidelines_overlay.show()
        for overlay in self.__visible_overlays:
            overlay.show()
        self.clip_toolbar.set_visible(self.clip_toolbar.clip is not None)
        self.__hide_all_overlays = False

    def set_cursor(self, name):
        cursor = None
        display = Gdk.Display.get_default()
        try:
            cursor = Gdk.Cursor.new_from_name(display, name)
        except TypeError:
            self.warning("Cursor '%s' not found.", name)
        self.app.gui.get_window().set_cursor(cursor)

    def reset_cursor(self):
        self.app.gui.get_window().set_cursor(None)

    def get_drag_distance(self, cursor_position):
        return cursor_position - self.click_position

    def get_normalized_drag_distance(self, cursor_position):
        return self.get_drag_distance(cursor_position) / self.window_size

    def get_normalized_cursor_position(self, cursor_position):
        return cursor_position / self.window_size

    def enable_resize_status(self, enabled):
        self.__show_resize_status = enabled

    def __sink_widget_size_allocate_cb(self, unused_widget, allocation):
        previous_allocation = self.__last_allocation
        self.__last_allocation = (allocation.width, allocation.height)
        if previous_allocation == self.__last_allocation:
            # The allocation did not actually change. Ignore the event.
            return

        if not self.__show_resize_status:
            return

        if not self.revealer.get_reveal_child():
            self.revealer.set_transition_duration(10)
            self.revealer.set_reveal_child(True)
            self.hide_overlays()

        video_width = self.app.project_manager.current_project.videowidth
        percent = int(allocation.width / video_width * 100)
        self.resize_status.set_text("{}%".format(percent))

        # Add timeout function to hide the resize percent.
        if self.__resizing_id:
            GLib.source_remove(self.__resizing_id)
        self.__resizing_id = GLib.timeout_add(1000, self.__resizing_timeout_cb, None)

    def __resizing_timeout_cb(self, unused_data):
        self.__resizing_id = 0
        self.revealer.set_transition_duration(500)
        self.revealer.set_reveal_child(False)
        self.show_overlays()
        return False
