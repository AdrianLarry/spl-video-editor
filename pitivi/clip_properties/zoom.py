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
"""Widget to make a clip zoom in or out slowly, from its start to its end."""
from gettext import gettext as _
from typing import Optional

from gi.repository import GES
from gi.repository import GLib
from gi.repository import Gtk

from pitivi.undo.timeline import CommitTimelineFinalizingAction
from pitivi.utils.loggable import Loggable
from pitivi.utils.motion import DEFAULT_ANCHOR
from pitivi.utils.motion import DEFAULT_SCALE
from pitivi.utils.motion import get_zoom
from pitivi.utils.motion import is_animated_by_user
from pitivi.utils.motion import MAX_SCALE
from pitivi.utils.motion import MIN_SCALE
from pitivi.utils.motion import set_zoom
from pitivi.utils.motion import Zoom
from pitivi.utils.motion import ZOOM_IN
from pitivi.utils.motion import ZOOM_OUT
from pitivi.utils.transitions import sync_pushes
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING

# The anchors in the grid, by row and column.
ANCHOR_GRID = (("top-left", "top", "top-right"),
               ("left", "center", "right"),
               ("bottom-left", "bottom", "bottom-right"))

ANCHOR_NAMES = {"top-left": _("Top left"), "top": _("Top center"),
                "top-right": _("Top right"), "left": _("Center left"),
                "center": _("Center"), "right": _("Center right"),
                "bottom-left": _("Bottom left"), "bottom": _("Bottom center"),
                "bottom-right": _("Bottom right")}


class ZoomProperties(Gtk.Expander, Loggable):
    """Widget for the automatic zoom of a video or an image.

    Attributes:
        app (Pitivi): The app.
        source (Optional[GES.VideoSource]): The source being configured.
    """

    def __init__(self, app):
        Gtk.Expander.__init__(self)
        Loggable.__init__(self)
        self.app = app
        self.source: Optional[GES.VideoSource] = None
        self._updating_ui = False
        self._handler_id = 0

        self.set_label(_("Automatic zoom"))
        self.set_expanded(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PADDING)
        box.props.border_width = SPACING

        hint = Gtk.Label(label=_("The image moves slowly from the start to the end of the clip."),
                         xalign=0)
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)

        kinds = Gtk.Box()
        kinds.get_style_context().add_class("linked")
        self.kind_buttons = {}
        group = None
        for kind, label in ((None, _("No")), (ZOOM_IN, _("Zoom in")), (ZOOM_OUT, _("Zoom out"))):
            button = Gtk.RadioButton.new_with_label_from_widget(group, label)
            group = group or button
            button.set_mode(False)
            button.connect("toggled", self.__changed_cb)
            kinds.pack_start(button, True, True, 0)
            self.kind_buttons[kind] = button
        box.pack_start(kinds, False, False, 0)

        self.settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PADDING)
        heading = Gtk.Label(xalign=0)
        heading.set_markup("<b>%s</b>" % GLib.markup_escape_text(_("Towards")))
        heading.props.margin_top = PADDING
        self.settings_box.pack_start(heading, False, False, 0)

        grid = Gtk.Grid(row_spacing=2, column_spacing=2, halign=Gtk.Align.START)
        self.anchor_buttons = {}
        group = None
        for row, anchors in enumerate(ANCHOR_GRID):
            for column, anchor in enumerate(anchors):
                button = Gtk.RadioButton.new_from_widget(group)
                group = group or button
                button.set_mode(False)
                button.set_size_request(36, 22)
                button.set_tooltip_text(ANCHOR_NAMES[anchor])
                button.connect("toggled", self.__changed_cb)
                grid.attach(button, column, row, 1, 1)
                self.anchor_buttons[anchor] = button
        self.anchor_label = Gtk.Label(xalign=0, yalign=0)
        self.anchor_label.set_line_wrap(True)
        self.anchor_label.get_style_context().add_class("dim-label")
        anchor_box = Gtk.Box(spacing=SPACING)
        anchor_box.pack_start(grid, False, False, 0)
        anchor_box.pack_start(self.anchor_label, True, True, 0)
        self.settings_box.pack_start(anchor_box, False, False, 0)

        scale_header = Gtk.Box()
        scale_header.props.margin_top = PADDING
        scale_header.pack_start(Gtk.Label(label=_("Intensity:"), xalign=0), False, False, 0)
        self.scale_label = Gtk.Label()
        scale_header.pack_end(self.scale_label, False, False, 0)
        self.settings_box.pack_start(scale_header, False, False, 0)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                              MIN_SCALE * 100, MAX_SCALE * 100, 5)
        self.scale.set_draw_value(False)
        self.scale.connect("value-changed", self.__changed_cb)
        self.settings_box.pack_start(self.scale, False, False, 0)
        box.pack_start(self.settings_box, False, False, 0)

        self.custom_label = Gtk.Label(
            label=_("The position of this clip has been animated by hand."), xalign=0)
        self.custom_label.set_line_wrap(True)
        box.pack_start(self.custom_label, False, False, 0)

        self.add(box)
        self.show_all()
        self.custom_label.set_no_show_all(True)
        self.custom_label.hide()
        self.hide()

    def set_source(self, source: Optional[GES.VideoSource]):
        """Sets the video source to configure, or None to hide."""
        if self.source and self._handler_id:
            self.source.disconnect(self._handler_id)
            self._handler_id = 0
        self.source = source
        if not source:
            self.hide()
            return
        # Undoing changes the zoom.
        self._handler_id = source.connect("notify-meta", self.__notify_meta_cb)
        self.update()
        self.show()

    def __notify_meta_cb(self, unused_source, key, unused_value):
        if key.startswith("spl::zoom") and not self._updating_ui:
            GLib.idle_add(self.__update_idle)

    def __update_idle(self):
        if self.source:
            self.update()
        return False

    def update(self):
        """Shows the zoom of the source."""
        zoom = get_zoom(self.source)
        self._updating_ui = True
        try:
            self.kind_buttons[zoom.kind if zoom else None].set_active(True)
            anchor = zoom.anchor if zoom else DEFAULT_ANCHOR
            self.anchor_buttons[anchor].set_active(True)
            self.scale.set_value(round((zoom.scale if zoom else DEFAULT_SCALE) * 100))
        finally:
            self._updating_ui = False
        self.__update_labels()

        custom = is_animated_by_user(self.source)
        for button in self.kind_buttons.values():
            button.set_sensitive(not custom)
        self.custom_label.set_visible(custom)
        self.settings_box.set_sensitive(bool(zoom) and not custom)

    def __update_labels(self):
        self.scale_label.set_markup("<b>%d %%</b>" % round(self.scale.get_value()))
        self.anchor_label.set_text(ANCHOR_NAMES[self.get_anchor()])

    def get_anchor(self):
        for anchor, button in self.anchor_buttons.items():
            if button.get_active():
                return anchor
        return DEFAULT_ANCHOR

    def get_kind(self):
        for kind, button in self.kind_buttons.items():
            if button.get_active():
                return kind
        return None

    def __changed_cb(self, widget):
        if isinstance(widget, Gtk.RadioButton) and not widget.get_active():
            # The other button of the group is toggled too.
            return
        self.__update_labels()
        if self._updating_ui or not self.source:
            return
        kind = self.get_kind()
        zoom = Zoom(kind, self.get_anchor(), self.scale.get_value() / 100) if kind else None
        self.settings_box.set_sensitive(bool(zoom))
        self.set_zoom(zoom, mergeable=widget is self.scale)

    def set_zoom(self, zoom: Optional[Zoom], mergeable=False):
        """Changes the automatic zoom of the source."""
        pipeline = self.app.project_manager.current_project.pipeline
        # Consecutive changes of the intensity are undone together.
        with self.app.action_log.started("Automatic zoom",
                                         finalizing_action=CommitTimelineFinalizingAction(pipeline),
                                         mergeable=mergeable,
                                         toplevel=True):
            set_zoom(self.source, zoom)
            layer = self.source.get_parent().get_layer()
            if layer:
                sync_pushes(layer)
