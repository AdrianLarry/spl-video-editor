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
from pitivi.utils.transitions import get_max_duration
from pitivi.utils.transitions import MIN_DURATION
from pitivi.utils.transitions import remove_transition
from pitivi.utils.transitions import set_transition
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING

# The kinds offered, as in the mockup. The ones without a kind are not
# available yet.
KINDS = ((DISSOLVE, _("Dissolve")),
         (FADE_TO_BLACK, _("Fade to black")),
         (None, _("Fade to white")),
         (None, _("Slide")))


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
            else:
                button.set_sensitive(False)
                button.set_tooltip_text(_("Coming soon"))
            grid.attach(button, index % 2, index // 2, 1, 1)
        self.kind_buttons[contact.kind or DISSOLVE].set_active(True)
        box.pack_start(grid, False, False, 0)

        duration_box = Gtk.Box()
        duration_box.pack_start(Gtk.Label(label=_("Duration")), False, False, 0)
        self.duration_label = Gtk.Label()
        duration_box.pack_end(self.duration_label, False, False, 0)
        box.pack_start(duration_box, False, False, 0)
        max_duration = get_max_duration(contact) / Gst.SECOND
        min_duration = min(MIN_DURATION / Gst.SECOND, max_duration)
        self.duration_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                                       min_duration, max_duration, 0.1)
        self.duration_scale.set_draw_value(False)
        self.duration_scale.connect("value-changed", self.__duration_changed_cb)
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

    def __apply_clicked_cb(self, unused_button):
        duration = round(self.duration_scale.get_value() * 10) * Gst.SECOND // 10
        self.__change(lambda: set_transition(self.contact, self.get_kind(), duration))

    def __remove_clicked_cb(self, unused_button):
        self.__change(lambda: remove_transition(self.contact))
