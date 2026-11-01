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
"""UI for choosing and customizing particle effect layers."""
from gettext import gettext as _
from typing import Callable
from typing import Optional

from gi.repository import GES
from gi.repository import Gtk

from pitivi.clip_properties.particles import get_particle_effect
from pitivi.clip_properties.particles import is_particle_clip
from pitivi.clip_properties.particles import PARTICLE_LABELS
from pitivi.undo.timeline import CommitTimelineFinalizingAction
from pitivi.utils.loggable import Loggable
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING

PARTICLE_MENU_ITEMS = [
    ("snow", _("Snow"), "weather-snow-symbolic"),
    ("confetti", _("Confetti"), "starred-symbolic"),
    ("sparkles", _("Sparkles"), "weather-clear-symbolic"),
    ("smoke", _("Smoke"), "weather-fog-symbolic"),
]


class ParticleMenuButton(Gtk.MenuButton):
    """Button offering particle effects to insert as an independent timeline layer."""

    def __init__(self, callback: Callable[[str], None]):
        Gtk.MenuButton.__init__(self)
        self.callback = callback

        box = Gtk.Box(spacing=PADDING)
        icon = Gtk.Image.new_from_icon_name("weather-snow-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        box.pack_start(icon, False, False, 0)
        box.pack_start(Gtk.Label(label=_("Effect")), False, False, 0)
        box.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU),
                       False, False, 0)
        self.add(box)
        self.set_tooltip_text(_("Add a particle effect layer (snow, confetti, sparkles, smoke) over the video"))

        popover = Gtk.Popover()
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        menu_box.props.margin = PADDING

        for effect_name, label, icon_name in PARTICLE_MENU_ITEMS:
            button = Gtk.Button()
            button.set_relief(Gtk.ReliefStyle.NONE)
            row = Gtk.Box(spacing=SPACING)
            row.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU), False, False, 0)
            row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            button.add(row)
            button.connect("clicked", self.__item_clicked_cb, effect_name)
            menu_box.pack_start(button, False, False, 0)

        menu_box.show_all()
        popover.add(menu_box)
        self.set_popover(popover)
        box.show_all()

    def __item_clicked_cb(self, unused_button, effect_name):
        self.get_popover().popdown()
        self.callback(effect_name)


class ParticlesProperties(Gtk.Expander, Loggable):
    """Properties panel expander for customizing particle effect settings."""

    def __init__(self, app):
        Gtk.Expander.__init__(self)
        Loggable.__init__(self)
        self.app = app
        self.clip: Optional[GES.Clip] = None
        self._updating = False

        self.set_expanded(True)
        self.set_label(_("Particles"))

        grid = Gtk.Grid()
        grid.props.column_spacing = SPACING
        grid.props.row_spacing = SPACING
        grid.props.margin = SPACING

        # Amount slider
        lbl_amount = Gtk.Label(label=_("Density"), xalign=0)
        self.amount_adj = Gtk.Adjustment(value=1.0, lower=0.2, upper=3.0, step_increment=0.1)
        self.amount_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.amount_adj)
        self.amount_scale.set_hexpand(True)
        self.amount_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.amount_scale.set_digits(1)
        self.amount_adj.connect("value-changed", self.__prop_changed_cb, "amount")
        grid.attach(lbl_amount, 0, 0, 1, 1)
        grid.attach(self.amount_scale, 1, 0, 1, 1)

        # Speed slider
        lbl_speed = Gtk.Label(label=_("Speed"), xalign=0)
        self.speed_adj = Gtk.Adjustment(value=1.0, lower=0.2, upper=3.0, step_increment=0.1)
        self.speed_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.speed_adj)
        self.speed_scale.set_hexpand(True)
        self.speed_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.speed_scale.set_digits(1)
        self.speed_adj.connect("value-changed", self.__prop_changed_cb, "speed")
        grid.attach(lbl_speed, 0, 1, 1, 1)
        grid.attach(self.speed_scale, 1, 1, 1, 1)

        # Size slider
        lbl_size = Gtk.Label(label=_("Size"), xalign=0)
        self.size_adj = Gtk.Adjustment(value=1.0, lower=0.2, upper=3.0, step_increment=0.1)
        self.size_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.size_adj)
        self.size_scale.set_hexpand(True)
        self.size_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.size_scale.set_digits(1)
        self.size_adj.connect("value-changed", self.__prop_changed_cb, "size")
        grid.attach(lbl_size, 0, 2, 1, 1)
        grid.attach(self.size_scale, 1, 2, 1, 1)

        grid.show_all()
        self.add(grid)
        self.set_visible(False)

    def set_clip(self, clip: Optional[GES.Clip]):
        """Updates the panel with the particle effect properties of the selected clip."""
        self.clip = clip if is_particle_clip(clip) else None
        self.set_visible(self.clip is not None)
        if not self.clip:
            return

        effect = get_particle_effect(self.clip)
        if not effect:
            return

        self._updating = True
        try:
            res, amount = effect.get_child_property("amount")
            if res:
                self.amount_adj.set_value(amount)
            res, speed = effect.get_child_property("speed")
            if res:
                self.speed_adj.set_value(speed)
            res, size = effect.get_child_property("size")
            if res:
                self.size_adj.set_value(size)
        finally:
            self._updating = False

    def __prop_changed_cb(self, adjustment, prop_name):
        if self._updating or not self.clip:
            return
        effect = get_particle_effect(self.clip)
        if not effect:
            return
        val = adjustment.get_value()
        pipeline = self.app.project_manager.current_project.pipeline
        with self.app.action_log.started(f"change {prop_name}",
                                         finalizing_action=CommitTimelineFinalizingAction(pipeline),
                                         toplevel=True):
            effect.set_child_property(prop_name, float(val))
