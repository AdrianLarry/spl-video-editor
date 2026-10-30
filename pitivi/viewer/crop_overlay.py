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
"""Cropping the sides of the image of a clip in the viewer.

While cropping, the whole image is shown, the part left out darkened.
The handles crop from their sides, dragging inside moves the part kept.
"""
import cairo
import numpy
from gi.repository import Gdk
from gi.repository import GES
from gi.repository import GObject
from gi.repository import Gtk

from pitivi.clip_properties.crop import apply_crop
from pitivi.clip_properties.crop import Crop
from pitivi.clip_properties.crop import get_crop
from pitivi.clip_properties.crop import MIN_SIZE
from pitivi.undo.timeline import CommitTimelineFinalizingAction
from pitivi.utils.blurfill import get_blur_fill
from pitivi.utils.blurfill import get_blur_fill_position
from pitivi.utils.blurfill import get_fit_rect
from pitivi.utils.blurfill import get_image_size
from pitivi.utils.loggable import Loggable
from pitivi.utils.motion import get_base_position
from pitivi.utils.motion import get_frame_size

# How close to a side the pointer grabs it, in pixels of the viewer.
GRAB_DISTANCE = 12
CORNER_LENGTH = 18
HANDLE_WIDTH = 6
# The orange of the actions, lighter for the handle under the pointer.
HANDLE_COLOR = (0xD9 / 255, 0x53 / 255, 0x1E / 255)
HOVERED_HANDLE_COLOR = (0xFF / 255, 0x8A / 255, 0x5B / 255)

CURSORS = {
    ("left", "top"): "nw-resize",
    ("left", "bottom"): "sw-resize",
    ("right", "top"): "ne-resize",
    ("right", "bottom"): "se-resize",
    ("left",): "w-resize",
    ("right",): "e-resize",
    ("top",): "n-resize",
    ("bottom",): "s-resize",
    (): "move",
}


class CropOverlay(Gtk.DrawingArea, Loggable):
    """Edits the crop of a clip, shown over the viewer.

    The whole image is shown by an undoable change, undone when finishing:
    the effects come back as they were, the changes made before them
    still undoable. Undoing it, as with Ctrl+Z, leaves the crop as it was.

    Attributes:
        clip (GES.Clip): The clip being cropped, while cropping.
        crop (Crop): The crop chosen.
    """

    __gsignals__ = {
        # Emitted when cropping ends, applied or not.
        "finished": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, stack):
        Gtk.DrawingArea.__init__(self)
        Loggable.__init__(self)
        self.stack = stack
        self.clip = None
        self.crop = Crop()
        self.__old_crop = Crop()
        self.__action_log = None
        # The change showing the whole image, if any.
        self.__whole_operation = None
        self.__move_handler_id = 0
        self.__image_size = (1, 1)
        # Where the whole image is shown, in pixels of the project.
        self.__whole = None
        self.__grabbed = None
        # The sides under the pointer, if any.
        self.__hovered = None
        self.__grab_crop = None
        self.__click = None
        self.set_no_show_all(True)
        # Shown over the whole viewer while cropping, it gets the events.
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK)
        for signal in ("button-press-event", "motion-notify-event", "button-release-event"):
            self.connect(signal, lambda unused_widget, event: self.handle_event(event))

    @property
    def active(self):
        return self.clip is not None

    def __project(self):
        return self.stack.app.project_manager.current_project

    def start(self, clip: GES.Clip):
        """Shows the whole image of the clip, ready for cropping."""
        if self.clip:
            self.cancel()
        source = clip.find_track_element(None, GES.VideoSource)
        if not source:
            return
        self.clip = clip
        self.__old_crop = get_crop(clip)
        self.__action_log = self.stack.app.action_log
        undo_stacks = self.__action_log.undo_stacks
        operations = len(undo_stacks)
        with self.__action_log.started("crop",
                                       finalizing_action=CommitTimelineFinalizingAction(self.__project().pipeline),
                                       toplevel=True):
            apply_crop(clip, Crop())
        self.__whole_operation = undo_stacks[-1] if len(undo_stacks) > operations else None
        self.__move_handler_id = self.__action_log.connect("move", self.__action_log_move_cb)
        self.__image_size = get_image_size(clip)
        rect = get_blur_fill_position(clip) if get_blur_fill(clip) else get_base_position(source)
        if rect:
            self.__whole = numpy.array([rect["posx"], rect["posy"], rect["width"], rect["height"]],
                                       dtype=float)
        else:
            # A video in front of the fill fits the frame.
            self.__whole = numpy.array(get_fit_rect(clip), dtype=float)
        self.crop = self.__old_crop
        self.stack.show_source_overlays(False)
        self.show()
        self.queue_draw()

    def apply(self):
        """Crops the clip as chosen, as an undoable change."""
        if not self.clip:
            return
        clip, crop = self.clip, self.crop
        action_log = self.__action_log
        self.__finish()
        with action_log.started("crop",
                                finalizing_action=CommitTimelineFinalizingAction(self.__project().pipeline),
                                toplevel=True):
            apply_crop(clip, crop)
        self.emit("finished")

    def cancel(self):
        """Leaves the crop as it was."""
        if not self.clip:
            return
        clip, old_crop = self.clip, self.__old_crop
        action_log = self.__action_log
        self.__finish()
        # Changed after showing the whole image, it is restored by a change.
        with action_log.started("crop",
                                finalizing_action=CommitTimelineFinalizingAction(self.__project().pipeline),
                                toplevel=True):
            apply_crop(clip, old_crop)
        self.emit("finished")

    def __finish(self):
        """Stops cropping, undoing the change showing the whole image."""
        action_log, operation = self.__action_log, self.__whole_operation
        if self.__move_handler_id:
            action_log.disconnect(self.__move_handler_id)
            self.__move_handler_id = 0
        if operation and action_log.undo_stacks and action_log.undo_stacks[-1] is operation:
            action_log.undo()
            self.__forget(operation)
        self.__stop()

    def __forget(self, operation):
        """Removes the undone change showing the whole image, not redoable."""
        action_log = self.__action_log
        if operation in action_log.redo_stacks:
            action_log.redo_stacks.remove(operation)
            # For the undo and redo actions to follow.
            action_log.emit("move", operation)

    def __stop(self):
        self.clip = None
        self.__action_log = None
        self.__whole_operation = None
        self.__grabbed = None
        self.__hovered = None
        self.__click = None
        self.hide()
        self.stack.show_source_overlays(True)
        self.stack.reset_cursor()

    def __action_log_move_cb(self, action_log, operation):
        # Undoing or redoing while cropping, as with Ctrl+Z, stops it.
        action_log.disconnect(self.__move_handler_id)
        self.__move_handler_id = 0
        if operation is self.__whole_operation:
            # Undone, the crop is as it was.
            self.__forget(operation)
        self.__finish()
        self.emit("finished")

    # Geometry, the rects being x, y, width and height.

    def __canvas(self):
        """Returns where the frame is shown in the viewer: offset and scale.

        The video keeps its shape in the viewer, centered, with bars on
        the sides when the viewer has another shape.
        """
        # The frame of the track, as the positions of the sources.
        source = self.clip.find_track_element(None, GES.VideoSource)
        project_size = numpy.array(get_frame_size(source), dtype=float)
        window_size = numpy.array(self.stack.window_size, dtype=float)
        scale = min(window_size / project_size)
        return (window_size - project_size * scale) / 2, scale

    def __scale(self):
        """Returns the size of a pixel of the image, in pixels of the viewer."""
        unused_offset, scale = self.__canvas()
        return self.__whole[2:] / numpy.array(self.__image_size) * scale

    def __whole_window_rect(self):
        offset, scale = self.__canvas()
        return numpy.concatenate([offset + self.__whole[:2] * scale, self.__whole[2:] * scale])

    def __kept_window_rect(self, crop=None):
        crop = crop or self.crop
        x, y, unused_width, unused_height = self.__whole_window_rect()
        scale_x, scale_y = self.__scale()
        width, height = self.__image_size
        return numpy.array([x + crop.left * scale_x, y + crop.top * scale_y,
                            (width - crop.left - crop.right) * scale_x,
                            (height - crop.top - crop.bottom) * scale_y])

    def __sides_at(self, position):
        """Returns the sides grabbed at the position, () inside, None outside."""
        x, y, width, height = self.__kept_window_rect()
        px, py = position
        if not (x - GRAB_DISTANCE <= px <= x + width + GRAB_DISTANCE and
                y - GRAB_DISTANCE <= py <= y + height + GRAB_DISTANCE):
            return None
        sides = []
        if abs(px - x) <= GRAB_DISTANCE:
            sides.append("left")
        elif abs(px - (x + width)) <= GRAB_DISTANCE:
            sides.append("right")
        if abs(py - y) <= GRAB_DISTANCE:
            sides.append("top")
        elif abs(py - (y + height)) <= GRAB_DISTANCE:
            sides.append("bottom")
        return tuple(sides)

    def __dragged_crop(self, position):
        """Returns the crop for the pointer dragged to the position."""
        crop = self.__grab_crop._asdict()
        delta = (numpy.array(position) - self.__click) / self.__scale()
        dx, dy = round(delta[0]), round(delta[1])
        width, height = self.__image_size
        if not self.__grabbed:
            # Moving the part kept, as big.
            dx = max(-crop["left"], min(crop["right"], dx))
            dy = max(-crop["top"], min(crop["bottom"], dy))
            crop["left"] += dx
            crop["right"] -= dx
            crop["top"] += dy
            crop["bottom"] -= dy
            return Crop(**crop)
        for side in self.__grabbed:
            if side == "left":
                crop["left"] = max(0, min(width - crop["right"] - MIN_SIZE, crop["left"] + dx))
            elif side == "right":
                crop["right"] = max(0, min(width - crop["left"] - MIN_SIZE, crop["right"] - dx))
            elif side == "top":
                crop["top"] = max(0, min(height - crop["bottom"] - MIN_SIZE, crop["top"] + dy))
            elif side == "bottom":
                crop["bottom"] = max(0, min(height - crop["top"] - MIN_SIZE, crop["bottom"] - dy))
        return Crop(**crop)

    # Events, while cropping.

    def handle_event(self, event):
        position = numpy.array([event.x, event.y])
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 1:
            sides = self.__sides_at(position)
            if sides is None:
                # A click out of the image applies, as in other editors.
                self.apply()
                return True
            self.__grabbed = sides
            self.__grab_crop = self.crop
            self.__click = position
        elif event.type == Gdk.EventType.MOTION_NOTIFY:
            if self.__click is not None:
                self.crop = self.__dragged_crop(position)
                self.queue_draw()
            else:
                sides = self.__sides_at(position)
                if sides != self.__hovered:
                    self.__hovered = sides
                    self.queue_draw()
                if sides is None:
                    self.stack.reset_cursor()
                else:
                    self.stack.set_cursor(CURSORS[tuple(sorted(sides, key=lambda side: side in ("top", "bottom")))])
        elif event.type == Gdk.EventType.BUTTON_RELEASE:
            self.__click = None
            self.__grabbed = None
            self.queue_draw()
        return True

    def do_draw(self, cr):
        if not self.clip:
            return
        whole = self.__whole_window_rect()
        kept = self.__kept_window_rect()

        # The part left out, darkened.
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(*whole)
        cr.rectangle(*kept)
        cr.set_source_rgba(0, 0, 0, 0.6)
        cr.fill()

        x, y, width, height = kept
        # The thirds, as a guide while dragging.
        if self.__click is not None:
            cr.set_line_width(1)
            cr.set_source_rgba(1, 1, 1, 0.35)
            for third in (1, 2):
                cr.move_to(x + width * third / 3, y)
                cr.line_to(x + width * third / 3, y + height)
                cr.move_to(x, y + height * third / 3)
                cr.line_to(x + width, y + height * third / 3)
            cr.stroke()

        cr.set_line_width(1.5)
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(x, y, width, height)
        cr.stroke()

        # The corners, as an L, and the middle of the sides, in orange.
        length = min(CORNER_LENGTH, width / 3, height / 3)
        active = self.__grabbed if self.__click is not None else self.__hovered
        handles = []
        for cx, cy, sx, sy, sides in ((x, y, 1, 1, ("left", "top")),
                                      (x + width, y, -1, 1, ("right", "top")),
                                      (x, y + height, 1, -1, ("left", "bottom")),
                                      (x + width, y + height, -1, -1, ("right", "bottom"))):
            handles.append((sides, ((cx + sx * length, cy), (cx, cy), (cx, cy + sy * length))))
        for cx, cy, side in ((x + width / 2, y, "top"), (x + width / 2, y + height, "bottom")):
            handles.append(((side,), ((cx - length / 2, cy), (cx + length / 2, cy))))
        for cx, cy, side in ((x, y + height / 2, "left"), (x + width, y + height / 2, "right")):
            handles.append(((side,), ((cx, cy - length / 2), (cx, cy + length / 2))))

        cr.set_line_cap(cairo.LINE_CAP_SQUARE)
        cr.set_line_join(cairo.LINE_JOIN_MITER)
        for sides, points in handles:
            cr.move_to(*points[0])
            for point in points[1:]:
                cr.line_to(*point)
            # A dark edge, to be seen over light images.
            cr.set_line_width(HANDLE_WIDTH + 2)
            cr.set_source_rgba(0, 0, 0, 0.5)
            cr.stroke_preserve()
            cr.set_line_width(HANDLE_WIDTH)
            hovered = active is not None and set(sides) == set(active)
            cr.set_source_rgb(*(HOVERED_HANDLE_COLOR if hovered else HANDLE_COLOR))
            cr.stroke()
