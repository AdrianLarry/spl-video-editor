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
"""Widgets for the transitions where two clips of a layer meet."""
import locale
from gettext import gettext as _

from gi.repository import GLib
from gi.repository import Gst
from gi.repository import Gtk
from gi.repository import Pango

from pitivi.undo.timeline import CommitTimelineFinalizingAction
from pitivi.utils.misc import filename_from_uri
from pitivi.utils.transitions import Contact
from pitivi.utils.transitions import DEFAULT_DURATION
from pitivi.utils.transitions import DISSOLVE
from pitivi.utils.transitions import FADE_TO_BLACK
from pitivi.utils.transitions import BOTTOM
from pitivi.utils.transitions import FADE_TO_WHITE
from pitivi.utils.transitions import LEFT
from pitivi.utils.transitions import RIGHT
from pitivi.utils.transitions import SOFT_WIPE
from pitivi.utils.transitions import TOP
from pitivi.utils.transitions import get_max_duration
from pitivi.utils.transitions import MIN_DURATION
from pitivi.utils.transitions import remove_transition
from pitivi.utils.transitions import set_transition
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING

# The kinds offered, as in the mockup. The ones without a kind are not
# available yet.
KINDS = ((DISSOLVE, _("Dissolve")),
         (SOFT_WIPE, _("Soft wipe")),
         (FADE_TO_BLACK, _("Fade to black")),
         (FADE_TO_WHITE, _("Fade to white")),
         (None, _("Slide")))

# The sides the second clip appears from, with their icons.
DIRECTIONS = ((LEFT, _("Left"), "go-next-symbolic"),
              (RIGHT, _("Right"), "go-previous-symbolic"),
              (TOP, _("Top"), "go-down-symbolic"),
              (BOTTOM, _("Bottom"), "go-up-symbolic"))
# The kinds which have a direction.
DIRECTED_KINDS = (SOFT_WIPE,)


def get_kind_name(kind):
    """Returns the name of a kind of transition."""
    for other_kind, name in KINDS:
        if other_kind == kind:
            return name
    return ""


def format_seconds(duration):
    """Returns a duration in seconds, as "1,5 s"."""
    return locale.format_string("%.1f s", duration / Gst.SECOND)


def create_transition_button(contact: Contact) -> Gtk.Button:
    """Creates the button showing the transition, or for adding one."""
    button = Gtk.Button()
    button.get_style_context().add_class("TransitionButton")
    button.props.focus_on_click = False
    if contact.kind:
        button.set_label(get_kind_name(contact.kind))
        button.set_tooltip_text(_("%s, %s. Click to change or remove it.") %
                                (get_kind_name(contact.kind), format_seconds(contact.duration)))
    else:
        button.set_image(Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.MENU))
        button.set_tooltip_text(_("Add a transition"))
    return button


class TransitionPopover(Gtk.Popover):
    """Popover for choosing the transition where two clips meet.

    Attributes:
        app (Pitivi): The app.
        contact (Contact): The clips and their transition.
    """

    def __init__(self, app, contact: Contact, relative_to: Gtk.Widget):
        Gtk.Popover.__init__(self)
        self.app = app
        self.contact = contact
        self.set_relative_to(relative_to)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        box.props.margin = SPACING

        title = Gtk.Label(xalign=0)
        title.set_markup("<b>%s</b>" % GLib.markup_escape_text(
            _("Change transition") if contact.kind else _("Add transition")))
        box.pack_start(title, False, False, 0)
        names = [filename_from_uri(clip.get_asset().props.id)
                 for clip in (contact.clip_a, contact.clip_b)]
        subtitle = Gtk.Label(label=_("Between «%s» and «%s»") % tuple(names), xalign=0)
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle.set_max_width_chars(36)
        subtitle.get_style_context().add_class("dim-label")
        box.pack_start(subtitle, False, False, 0)

        grid = Gtk.Grid(row_spacing=PADDING, column_spacing=PADDING, column_homogeneous=True)
        self.kind_buttons = {}
        group = None
        for index, (kind, name) in enumerate(KINDS):
            button = Gtk.RadioButton.new_with_label_from_widget(group, name)
            group = group or button
            button.set_mode(False)
            if kind:
                self.kind_buttons[kind] = button
                button.connect("toggled", self.__kind_toggled_cb)
            else:
                button.set_sensitive(False)
                button.set_tooltip_text(_("Coming soon"))
            grid.attach(button, index % 2, index // 2, 1, 1)
        self.kind_buttons[contact.kind or DISSOLVE].set_active(True)
        box.pack_start(grid, False, False, 0)

        self.direction_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PADDING)
        self.direction_box.pack_start(Gtk.Label(label=_("From"), xalign=0), False, False, 0)
        directions_grid = Gtk.Grid(column_spacing=PADDING, column_homogeneous=True)
        self.direction_buttons = {}
        group = None
        for index, (direction, name, icon_name) in enumerate(DIRECTIONS):
            button = Gtk.RadioButton.new_with_label_from_widget(group, name)
            group = group or button
            button.set_mode(False)
            button.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU))
            button.set_always_show_image(True)
            directions_grid.attach(button, index, 0, 1, 1)
            self.direction_buttons[direction] = button
        self.direction_buttons[contact.direction or RIGHT].set_active(True)
        self.direction_box.pack_start(directions_grid, False, False, 0)
        box.pack_start(self.direction_box, False, False, 0)

        duration_box = Gtk.Box()
        duration_box.pack_start(Gtk.Label(label=_("Duration")), False, False, 0)
        self.duration_label = Gtk.Label()
        duration_box.pack_end(self.duration_label, False, False, 0)
        box.pack_start(duration_box, False, False, 0)
        self.duration_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                                       MIN_DURATION / Gst.SECOND,
                                                       MIN_DURATION / Gst.SECOND + 0.1, 0.1)
        self.duration_scale.set_draw_value(False)
        self.duration_scale.connect("value-changed", self.__duration_changed_cb)
        self.__update_duration_range()
        duration = contact.duration if contact.kind else DEFAULT_DURATION
        self.duration_scale.set_value(duration / Gst.SECOND)
        self.__duration_changed_cb(self.duration_scale)
        box.pack_start(self.duration_scale, False, False, 0)

        buttons_box = Gtk.Box(spacing=PADDING)
        if contact.kind:
            self.remove_button = Gtk.Button(label=_("Remove transition"))
            self.remove_button.props.relief = Gtk.ReliefStyle.NONE
            self.remove_button.get_style_context().add_class("spl-danger-text")
            self.remove_button.connect("clicked", self.__remove_clicked_cb)
            buttons_box.pack_start(self.remove_button, False, False, 0)
        self.apply_button = Gtk.Button(label=_("Save") if contact.kind else _("Apply"))
        self.apply_button.get_style_context().add_class("suggested-action")
        self.apply_button.connect("clicked", self.__apply_clicked_cb)
        buttons_box.pack_end(self.apply_button, False, False, 0)
        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", lambda unused_button: self.popdown())
        buttons_box.pack_end(cancel_button, False, False, 0)
        box.pack_start(buttons_box, False, False, 0)

        self.add(box)
        box.show_all()
        self.__update_direction_visibility()

    def __update_direction_visibility(self):
        self.direction_box.set_visible(self.get_kind() in DIRECTED_KINDS)

    def get_direction(self):
        for direction, button in self.direction_buttons.items():
            if button.get_active():
                return direction
        return None

    def __update_duration_range(self):
        """Sets the durations offered, which depend on the kind."""
        max_duration = get_max_duration(self.contact, self.get_kind()) / Gst.SECOND
        min_duration = min(MIN_DURATION / Gst.SECOND, max_duration)
        self.duration_scale.set_range(min_duration, max(max_duration, min_duration))

    def __kind_toggled_cb(self, button):
        if button.get_active() and hasattr(self, "duration_scale"):
            self.__update_duration_range()
        if button.get_active() and hasattr(self, "direction_box"):
            self.__update_direction_visibility()

    def __duration_changed_cb(self, scale):
        self.duration_label.set_markup("<b>%s</b>" % GLib.markup_escape_text(
            format_seconds(scale.get_value() * Gst.SECOND)))

    def get_kind(self):
        for kind, button in self.kind_buttons.items():
            if button.get_active():
                return kind
        return None

    def __change(self, change):
        pipeline = self.app.project_manager.current_project.pipeline
        with self.app.action_log.started("transition",
                                         finalizing_action=CommitTimelineFinalizingAction(pipeline),
                                         toplevel=True):
            change()
        self.popdown()
        # Nothing moves for some transitions, the buttons are updated anyway.
        layer = self.get_relative_to().get_parent()
        if hasattr(layer, "schedule_update_gaps"):
            layer.schedule_update_gaps()

    def __apply_clicked_cb(self, unused_button):
        duration = round(self.duration_scale.get_value() * 10) * Gst.SECOND // 10
        self.__change(lambda: set_transition(self.contact, self.get_kind(), duration,
                                             self.get_direction()))

    def __remove_clicked_cb(self, unused_button):
        self.__change(lambda: remove_transition(self.contact))
