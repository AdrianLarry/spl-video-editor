# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (C) 2010 Thibault Saunier <tsaunier@gnome.org>
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
"""Widgets to control clips properties."""
import bisect
import os
from gettext import gettext as _
from typing import Callable
from typing import Dict
from typing import Optional
from typing import Tuple

import cairo
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import GES
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstController
from gi.repository import Gtk
from gi.repository import Pango

from pitivi.check import MISSING_SOFT_DEPS
from pitivi.clip_properties.alignment import AlignmentEditor
from pitivi.clip_properties.color import ColorProperties
from pitivi.clip_properties.compositing import CompositingProperties
from pitivi.clip_properties.markers import ClipMarkersProperties
from pitivi.clip_properties.orientation import get_orientation
from pitivi.clip_properties.orientation import Orientation
from pitivi.clip_properties.orientation import set_orientation
from pitivi.clip_properties.sound import SoundProperties
from pitivi.clip_properties.zoom import ZoomProperties
from pitivi.clip_properties.summary import ClipSummary
from pitivi.clip_properties.title import get_default_font_description
from pitivi.clip_properties.title import TitleProperties
from pitivi.configure import get_ui_dir
from pitivi.configure import in_devel
from pitivi.effects import EffectsPopover
from pitivi.effects import EffectsPropertiesManager
from pitivi.effects import HIDDEN_EFFECTS
from pitivi.trackerperspective import CoverObjectPopover
from pitivi.undo.timeline import CommitTimelineFinalizingAction
from pitivi.utils.blurfill import BLUR_SIGMA_META
from pitivi.utils.blurfill import get_blur_fill
from pitivi.utils.blurfill import get_blur_sigma
from pitivi.utils.blurfill import is_blur_fill_effect
from pitivi.utils.blurfill import set_blur_fill
from pitivi.utils.blurfill import set_blur_sigma
from pitivi.utils.blurfill import update_blur_fill
from pitivi.utils.custom_effect_widgets import create_custom_prop_widget_cb
from pitivi.utils.custom_effect_widgets import create_custom_widget_cb
from pitivi.utils.formats import get_fill_position
from pitivi.utils.loggable import Loggable
from pitivi.utils.misc import disconnect_all_by_func
from pitivi.utils.motion import get_base_position
from pitivi.utils.motion import has_motion
from pitivi.utils.motion import set_base_position
from pitivi.utils.motion import set_zoom
from pitivi.utils.pipeline import PipelineError
from pitivi.utils.timeline import SELECT
from pitivi.utils.transitions import is_white_effect
from pitivi.utils.transitions import sync_pushes
from pitivi.utils.ui import disable_scroll
from pitivi.utils.ui import EFFECT_TARGET_ENTRY
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING

(COL_ACTIVATED,
 COL_TYPE,
 COL_BIN_DESCRIPTION_TEXT,
 COL_NAME_TEXT,
 COL_DESC_TEXT,
 COL_TRACK_EFFECT) = list(range(6))

# Translators: This is the default text of a title clip.
DEFAULT_TEXT = _("Write your text")
FOREGROUND_DEFAULT_COLOR = 0xFFFFFFFF  # White
BACKGROUND_DEFAULT_COLOR = 0x00000000  # Transparent
OUTLINE_DEFAULT_COLOR = 0xFF000000  # Black
# Centered, so the position grid of the title properties shows it.
DEFAULT_VALIGNMENT = "bottom"
DEFAULT_HALIGNMENT = "center"
DEFAULT_DROP_SHADOW = True
DEFAULT_BLENDING = "over"

# Max speed rate we allow to be applied to clips.
# The minimum is 1 / MAX_RATE.
MAX_RATE = 10

# The size of the thumbnails of the applied effects.
EFFECT_THUMBNAIL_WIDTH = 34
EFFECT_THUMBNAIL_HEIGHT = 22


class ClipProperties(Gtk.ScrolledWindow, Loggable):
    """Widget for configuring the selected clip.

    Attributes:
        app (Pitivi): The app.
        effect_expander (EffectProperties): The effects applied to the clip.
            It is packed by the caller when `show_effects` is False.
        summary (ClipSummary): The summary of the selected clip, to be packed
            by the caller.
    """

    def __init__(self, app, show_effects=True):
        Gtk.ScrolledWindow.__init__(self)
        Loggable.__init__(self)
        self.app = app

        # Scroll horizontally too, so the properties fit in a narrow panel.
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        viewport = Gtk.Viewport()
        viewport.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        viewport.show()
        self.add(viewport)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        vbox.show()
        viewport.add(vbox)

        self.clips_box = Gtk.Box()
        self.clips_box.set_orientation(Gtk.Orientation.VERTICAL)
        self.clips_box.show()
        vbox.pack_start(self.clips_box, False, False, 0)

        self.transformation_expander = TransformationProperties(app)
        self.transformation_expander.set_vexpand(False)
        vbox.pack_start(self.transformation_expander, False, False, 0)

        self.zoom_expander = ZoomProperties(app)
        self.zoom_expander.set_vexpand(False)
        vbox.pack_start(self.zoom_expander, False, False, 0)

        self.speed_expander = TimeProperties(app)
        self.speed_expander.set_vexpand(False)
        if in_devel():
            vbox.pack_start(self.speed_expander, False, False, 0)

        self.title_expander = TitleProperties(app)
        self.title_expander.set_vexpand(False)
        vbox.pack_start(self.title_expander, False, False, 0)

        self.color_expander = ColorProperties(app)
        self.color_expander.set_vexpand(False)
        vbox.pack_start(self.color_expander, False, False, 0)

        self.compositing_expander = CompositingProperties(app)
        self.compositing_expander.set_vexpand(False)
        vbox.pack_start(self.compositing_expander, False, False, 0)

        self.sound_expander = SoundProperties(app)
        self.sound_expander.set_vexpand(False)
        vbox.pack_start(self.sound_expander, False, False, 0)

        self.summary = ClipSummary()

        self.effect_expander = EffectProperties(app)
        self.effect_expander.set_vexpand(False)
        if show_effects:
            vbox.pack_start(self.effect_expander, False, False, 0)

        self.marker_expander = ClipMarkersProperties(app)
        self.marker_expander.set_vexpand(False)
        vbox.pack_start(self.marker_expander, False, False, 0)

        self.helper_box = self.create_helper_box()
        self.clips_box.pack_start(self.helper_box, False, False, 0)

        disable_scroll(vbox)

        self.transformation_expander.set_source(None)
        self.zoom_expander.set_source(None)
        self.speed_expander.set_clip(None)
        self.title_expander.set_source(None)
        self.color_expander.set_source(None)
        self.compositing_expander.set_source(None)
        self.sound_expander.set_source(None)
        self.effect_expander.set_clip(None)
        self.marker_expander.set_clip(None)

        self._project = None
        self._selection = None

    def create_helper_box(self):
        """Creates the widgets to display when no clip is selected."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.props.margin = PADDING

        label = Gtk.Label(label=_("Select a clip on the timeline to configure its properties and effects or create a new clip:"))
        label.set_line_wrap(True)
        label.set_xalign(0)
        box.pack_start(label, False, False, SPACING)

        self._title_button = Gtk.Button()
        self._title_button.set_label(_("Create a title clip"))
        self._title_button.connect("clicked", self.create_title_clip_cb)
        box.pack_start(self._title_button, False, False, SPACING)

        self._color_button = Gtk.Button()
        self._color_button.set_label(_("Create a color clip"))
        self._color_button.connect("clicked", self.create_color_clip_cb)
        box.pack_start(self._color_button, False, False, SPACING)

        box.show_all()
        return box

    def create_title_clip_cb(self, unused_button):
        title_clip = GES.TitleClip()
        duration = self.app.settings.titleClipLength * Gst.MSECOND
        title_clip.set_duration(duration)
        with self.app.action_log.started("add title clip",
                                         finalizing_action=CommitTimelineFinalizingAction(self._project.pipeline),
                                         toplevel=True):
            self.app.gui.editor.timeline_ui.insert_clips_on_first_layer([
                title_clip])
            # Now that the clip is inserted in the timeline, it has a source which
            # can be used to set its properties.
            source = title_clip.get_children(False)[0]
            properties = {"text": DEFAULT_TEXT,
                          "foreground-color": BACKGROUND_DEFAULT_COLOR,
                          "color": FOREGROUND_DEFAULT_COLOR,
                          "outline-color": OUTLINE_DEFAULT_COLOR,
                          "font-desc": get_default_font_description(self._project.videoheight),
                          "valignment": DEFAULT_VALIGNMENT,
                          "halignment": DEFAULT_HALIGNMENT,
                          "draw-shadow": DEFAULT_DROP_SHADOW}
            for prop, value in properties.items():
                res = source.set_child_property(prop, value)
                assert res, prop
        self._selection.set_selection([title_clip], SELECT)

    def create_color_clip_cb(self, unused_widget):
        color_clip = GES.TestClip.new()
        duration = self.app.settings.ColorClipLength * Gst.MSECOND
        color_clip.set_duration(duration)
        color_clip.set_vpattern(GES.VideoTestPattern.SOLID_COLOR)
        color_clip.set_supported_formats(GES.TrackType.VIDEO)
        with self.app.action_log.started("add color clip",
                                         finalizing_action=CommitTimelineFinalizingAction(self._project.pipeline),
                                         toplevel=True):
            self.app.gui.editor.timeline_ui.insert_clips_on_first_layer([color_clip])
        self._selection.set_selection([color_clip], SELECT)

    def set_project(self, project, timeline_ui):
        if self._project:
            self._selection.disconnect_by_func(self._selection_changed_cb)
            self._selection = None
        if project:
            self._selection = timeline_ui.timeline.selection
            self._selection.connect("selection-changed", self._selection_changed_cb)
        self._project = project

    def _selection_changed_cb(self, selection):
        ges_clip = selection.get_single_clip()
        self.helper_box.set_visible(not ges_clip)
        self.summary.set_clip(ges_clip)

        video_source = None
        audio_source = None
        title_source = None
        color_clip_source = None
        if ges_clip:
            for child in ges_clip.get_children(False):
                if isinstance(child, GES.VideoSource):
                    video_source = child
                elif isinstance(child, GES.AudioSource):
                    audio_source = child

                if isinstance(child, GES.TitleSource):
                    title_source = child
                elif isinstance(child, GES.VideoTestSource):
                    color_clip_source = child

        self.transformation_expander.set_source(video_source)
        # The zoom is offered for the videos only. The slow zoom on a photo
        # shakes, see section 5 of TRASPASO-SPL.md.
        is_visual = (isinstance(video_source, GES.VideoUriSource) and
                     not ges_clip.get_asset().is_image())
        # The blurred fill covers the source, which zooms.
        if is_visual and get_blur_fill(ges_clip):
            is_visual = False
        self.zoom_expander.set_source(video_source if is_visual else None)
        self.speed_expander.set_clip(ges_clip if (not title_source and not color_clip_source) else None)
        self.title_expander.set_source(title_source)
        self.color_expander.set_source(color_clip_source)
        self.compositing_expander.set_source(video_source)
        self.sound_expander.set_source(audio_source)
        self.effect_expander.set_clip(ges_clip)
        self.marker_expander.set_clip(ges_clip)

        self.app.gui.editor.viewer.overlay_stack.select(video_source)


def is_time_effect(effect):
    return bool(effect.get_meta(TimeProperties.TIME_EFFECT_META)) and in_devel()


class TimeProperties(Gtk.Expander, Loggable):
    """Widget for setting the time related properties of a clip.

    Attributes:
        app (Pitivi): The app.
    """

    TIME_EFFECT_META = "ptv::time-effect"
    TIME_EFFECTS_DEF = {
        GES.TrackType.VIDEO: ("videorate", "rate"),
        GES.TrackType.AUDIO: ("pitch", "tempo"),
    }

    def __init__(self, app: Gtk.Application) -> None:
        super().__init__()
        Loggable.__init__(self)

        self.set_expanded(True)
        self.set_label(_("Time"))

        self.app = app

        self._clip: Optional[GES.Clip] = None
        self._sources: Dict[GES.Track, GES.Source] = {}
        # track -> (effect, rate_changing_property_name)
        self._time_effects: Dict[GES.Track, Tuple[GES.BaseEffect, str]] = {}

        grid = Gtk.Grid.new()
        grid.props.row_spacing = SPACING
        grid.props.column_spacing = SPACING
        grid.props.border_width = SPACING
        self.add(grid)

        self._speed_adjustment = Gtk.Adjustment()
        self._speed_adjustment.props.lower = 1 / MAX_RATE
        self._speed_adjustment.props.upper = MAX_RATE
        self._speed_adjustment.props.value = 1
        self._speed_spin_button = Gtk.SpinButton.new(adjustment=self._speed_adjustment, climb_rate=2, digits=2)
        self._speed_spin_button.set_increments(.1, 1)
        self._speed_spin_button.set_numeric(True)

        self._speed_scale_adjustment = Gtk.Adjustment()
        self._speed_scale_adjustment.props.lower = self._rate_to_linear(1 / MAX_RATE)
        self._speed_scale_adjustment.props.upper = self._rate_to_linear(MAX_RATE)
        self._speed_scale_adjustment.props.value = 1
        self._speed_scale = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL, self._speed_scale_adjustment)
        self._speed_scale.set_size_request(width=200, height=-1)
        self._speed_scale.props.draw_value = False
        self._speed_scale.props.show_fill_level = False

        linear = self._rate_to_linear(1 / 4)
        self._speed_scale.add_mark(linear, Gtk.PositionType.BOTTOM, "¼")
        linear = self._rate_to_linear(1 / 2)
        self._speed_scale.add_mark(linear, Gtk.PositionType.BOTTOM, "½")
        for rate in (1, 2, 4, 8):
            linear = self._rate_to_linear(rate)
            self._speed_scale.add_mark(linear, Gtk.PositionType.BOTTOM, "{}".format(rate))

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        hbox.pack_start(self._speed_spin_button, False, False, PADDING)
        hbox.pack_start(self._speed_scale, False, False, PADDING)
        self.__add_widget_to_grid(grid, _("Speed"), hbox, self._speed_reset_button_clicked_cb, 0)

        self.__setting_rate = False
        self.bind_property("rate",
                           self._speed_adjustment, "value",
                           GObject.BindingFlags.BIDIRECTIONAL)
        self.bind_property("rate_linear",
                           self._speed_scale_adjustment, "value",
                           GObject.BindingFlags.BIDIRECTIONAL)

    def _speed_reset_button_clicked_cb(self, button):
        self._speed_adjustment.props.value = 1
        self._speed_scale_adjustment.props.value = 1

    def __add_widget_to_grid(self, grid: Gtk.Grid, nick: str, widget: Gtk.Widget, reset_func: Callable, y: int) -> None:
        text = _("%(preference_label)s:") % {"preference_label": nick}

        button = Gtk.Button.new_from_icon_name("edit-clear-all-symbolic", Gtk.IconSize.MENU)
        button.set_tooltip_text(_("Reset to default value"))
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.connect("clicked", reset_func)

        label = Gtk.Label(label=text)
        label.props.yalign = 0.5
        grid.attach(label, 0, y, 1, 1)
        grid.attach(widget, 1, y, 1, 1)
        grid.attach(button, 2, y, 1, 1)

    def __get_source_duration(self) -> Tuple[GES.Source, int]:
        assert self._clip is not None

        res = (None, Gst.CLOCK_TIME_NONE)
        for source in self._sources.values():
            internal_duration = self._clip.get_internal_time_from_timeline_time(source, source.props.duration)
            if internal_duration < res[1]:
                res = (source, internal_duration)

        return res

    def _current_rate(self) -> float:
        for effect, propname in self._time_effects.values():
            return effect.get_child_property(propname).value
        return 1

    @staticmethod
    def _rate_to_linear(value: float) -> float:
        if value < 1:
            return value * MAX_RATE - (MAX_RATE - 1)
        else:
            return value

    @staticmethod
    def _linear_to_rate(value: float) -> float:
        if value < 1:
            return (value + MAX_RATE - 1) / MAX_RATE
        else:
            return value

    @GObject.Property(type=float)
    def rate(self):
        value = self._current_rate()
        return value

    @rate.setter  # type: ignore
    def rate(self, value: float) -> None:
        self._set_rate(value)
        # We assume the "rate" has been set as an effect of the binding between
        # the self._speed_adjustment and the "rate" property.
        # Signal the "rate_linear" property is updated so
        # self._speed_scale_adjustment is also updated.
        self.notify("rate_linear")

    @GObject.Property(type=float)
    def rate_linear(self):
        value = self._current_rate()
        return self._rate_to_linear(value)

    @rate_linear.setter  # type: ignore
    def rate_linear(self, linear: float) -> None:
        value = self._linear_to_rate(linear)
        self._set_rate(value)
        # We assume the "rate_linear" has been set as an effect of the binding
        # between the self._speed_scale_adjustment and the "rate" property.
        # Signal the "rate" property is updated so the self._speed_adjustment
        # is also updated.
        self.notify("rate")

    def _set_rate(self, value: float):
        if not self._clip:
            return

        if value != 1:
            self.__ensure_effects()

        prev_rate = self._current_rate()
        if prev_rate == value:
            return

        self.info("Setting speed to %s", value)
        project = self.app.project_manager.current_project
        self.__setting_rate = True
        prev_snapping_distance = project.ges_timeline.props.snapping_distance
        is_auto_clamp = False
        try:
            self.app.action_log.begin("set clip speed",
                                      finalizing_action=CommitTimelineFinalizingAction(project.pipeline),
                                      toplevel=True)
            is_auto_clamp = True
            for track_element in self._clip.get_children(True):
                track_element.set_auto_clamp_control_sources(False)

            source, source_duration = self.__get_source_duration()
            for effect, propname in self._time_effects.values():
                res = effect.set_child_property(propname, value)
                assert res

            new_end = self._clip.get_timeline_time_from_internal_time(source, self._clip.props.start + source_duration)

            # We do not want to snap when setting clip speed
            project.ges_timeline.props.snapping_distance = 0
            self._clip.edit_full(-1, GES.EditMode.TRIM, GES.Edge.END, new_end)
            for track_element in self._clip.get_children(True):
                track_element.set_auto_clamp_control_sources(True)
            is_auto_clamp = False
        except GLib.Error as e:
            self.app.action_log.rollback()
            if e.domain == "GES_ERROR":
                self.error("Error when setting speed: %s", e)

                # At this point the GBinding is frozen (to avoid looping)
                # so even if we notify "rate" at this point, the value wouldn't
                # be reflected, we need to do it manually
                self._speed_adjustment.props.value = prev_rate
                self._speed_scale_adjustment.props.value = self._rate_to_linear(prev_rate)
            else:
                raise e
        except Exception as e:
            self.app.action_log.rollback()
            raise e
        else:
            self.app.action_log.commit("set clip speed")
        finally:
            self.__setting_rate = False
            project.ges_timeline.props.snapping_distance = prev_snapping_distance
            if is_auto_clamp:
                for track_element in self._clip.get_children(True):
                    track_element.set_auto_clamp_control_sources(True)

        self.debug("New value is %s", self.props.rate)

    def __child_property_changed_cb(self, element: GES.TimelineElement, obj: GObject.Object, prop: GObject.ParamSpec) -> None:
        if self.__setting_rate or not isinstance(obj, Gst.Element):
            return

        time_effect_factory_names = [d[0] for d in self.TIME_EFFECTS_DEF.values()]
        if not obj.get_factory().get_name() in time_effect_factory_names:
            return

        rate = None
        for effect, propname in self._time_effects.values():
            if rate and rate != effect.get_child_property(propname).value:
                # Do no notify before all children have they new value set
                return
            rate = effect.get_child_property(propname).value

        self.notify("rate")
        self.notify("rate_linear")

    def set_clip(self, clip):
        if self._clip:
            self._clip.disconnect_by_func(self.__child_property_changed_cb)

        self._clip = clip

        self._sources = {}
        if self._clip:
            for track in self._clip.get_timeline().get_tracks():
                source = self._clip.find_track_element(track, GES.Source)
                if source:
                    self._sources[track] = source

            if not self._sources:
                self._clip = None

        self._time_effects = self.__get_time_effects(self._clip)

        if self._clip:
            # Signal the properties changed so the Adjustments bound to them
            # and the widgets using these are updated.
            self.notify("rate")
            self.notify("rate_linear")

            self._clip.connect("deep-notify", self.__child_property_changed_cb)
            self.show_all()
        else:
            self.hide()

    def __get_time_effects(self, clip):
        if clip is None:
            return {}

        time_effects = {}
        for effect in clip.get_top_effects():
            if not is_time_effect(effect):
                continue

            track = effect.get_track()
            if track in time_effects:
                self.error("Something is wrong as we have several %s time effects", track)
                continue

            time_effects[track] = (effect, self.TIME_EFFECTS_DEF[track.props.track_type][1])

        return time_effects

    def __ensure_effects(self):
        if self._time_effects:
            return

        rate = None
        for track, unused_source in self._sources.items():
            if track not in self._time_effects:
                bindesc, propname = self.TIME_EFFECTS_DEF[track.props.track_type]
                effect = GES.Effect.new(bindesc)
                self._time_effects[track] = (effect, propname)
                effect.set_meta(self.TIME_EFFECT_META, True)
                self._clip.add_top_effect(effect, 0)

            res, tmprate = effect.get_child_property(propname)
            assert res

            if rate:
                if rate != tmprate:
                    self.error("Rate mismatch, going to reset it to %s", rate)
                    self.__setting_rate = True
                    self.set_child_property(propname, rate)
            else:
                rate = tmprate


class EffectProperties(Gtk.Expander, Loggable):
    """Widget for viewing a list of effects and configuring them.

    Attributes:
        app (Pitivi): The app.
        clip (GES.Clip): The clip being configured.
    """

    __gsignals__ = {
        # Emitted when the clip or its effects change.
        "effects-changed": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, app):
        Gtk.Expander.__init__(self)
        Loggable.__init__(self)

        self.set_expanded(True)
        self.set_label(_("Effects"))

        self.app = app
        self.clip = None

        self.effects_properties_manager = EffectsPropertiesManager(app)
        # Set up the effects manager to be able to create custom UI.
        self.effects_properties_manager.connect("create_widget", create_custom_widget_cb)
        self.effects_properties_manager.connect("create_property_widget", create_custom_prop_widget_cb)

        self.expander_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.effects_listbox = Gtk.ListBox()

        self.placeholder_label = Gtk.Label(
            _("To apply an effect to the clip, drag it from the Effect Library "
              "or use the button below."))
        self.placeholder_label.set_line_wrap(True)
        self.placeholder_label.show()
        self.effects_listbox.set_placeholder(self.placeholder_label)

        # Add effect popover button
        self.effect_popover = EffectsPopover(app)
        self.add_effect_button = Gtk.MenuButton(_("Add Effect"))
        self.add_effect_button.set_popover(self.effect_popover)
        self.add_effect_button.props.halign = Gtk.Align.CENTER

        self.object_tracker_box = Gtk.ButtonBox()
        self.object_tracker_box.props.halign = Gtk.Align.CENTER

        self.cover_popover: Optional[Gtk.Popover] = None
        self.cover_object_button: Optional[Gtk.MenuButton] = None
        if "cvtracker" not in MISSING_SOFT_DEPS:
            self.cover_object_button = Gtk.MenuButton(_("Cover Object"))
            self.object_tracker_box.pack_start(self.cover_object_button, False, False, 0)

        self.drag_dest_set(Gtk.DestDefaults.DROP, [EFFECT_TARGET_ENTRY],
                           Gdk.DragAction.COPY)

        self.hint_label = Gtk.Label(label=_("Deactivate one to compare without losing it."))
        self.hint_label.set_line_wrap(True)
        self.hint_label.set_xalign(0)
        self.hint_label.get_style_context().add_class("dim-label")
        self.hint_label.set_no_show_all(True)

        self.expander_box.pack_start(self.hint_label, False, False, PADDING)
        self.expander_box.pack_start(self.effects_listbox, False, False, 0)
        self.expander_box.pack_start(self.add_effect_button, False, False, PADDING)
        self.expander_box.pack_start(self.object_tracker_box, False, False, PADDING)

        self.add(self.expander_box)

        # Connect all the widget signals
        self.connect("drag-motion", self._drag_motion_cb)
        self.connect("drag-leave", self._drag_leave_cb)
        self.connect("drag-data-received", self._drag_data_received_cb)

        self.add_effect_button.connect("toggled", self._add_effect_button_toggled_cb)
        if self.cover_object_button:
            self.cover_object_button.connect("toggled", self._cover_object_button_toggled_cb)

        self.show_all()

    def _add_effect_button_toggled_cb(self, button):
        # MenuButton interacts directly with the popover, bypassing our subclassed method
        if button.props.active:
            self.effect_popover.search_entry.set_text("")

    def _cover_object_button_toggled_cb(self, button):
        if button.props.active:
            self.cover_popover.update_object_list()

    def _create_effect_row(self, effect):
        if is_time_effect(effect) or effect.props.bin_description in HIDDEN_EFFECTS or \
                is_white_effect(effect) or is_blur_fill_effect(effect):
            # The fade to white of a transition is not an effect for the user.
            return None

        effect_info = self.app.effects.get_info(effect)
        thumbnail = Gtk.Image.new_from_pixbuf(effect_info.icon.scale_simple(
            EFFECT_THUMBNAIL_WIDTH, EFFECT_THUMBNAIL_HEIGHT, GdkPixbuf.InterpType.BILINEAR))
        thumbnail.props.valign = Gtk.Align.CENTER

        name_label = Gtk.Label(label=effect_info.human_name)
        name_label.set_xalign(0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        state_label = Gtk.Label()
        state_label.set_xalign(0)
        state_label.get_style_context().add_class("dim-label")
        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        name_box.pack_start(name_label, False, False, 0)
        name_box.pack_start(state_label, False, False, 0)
        name_box.set_tooltip_text(effect_info.description)

        # The settings of the effect are shown when clicking its name.
        effect_config_ui = self.effects_properties_manager.get_effect_configuration_ui(effect)
        # The settings can be wider than the panel, without widening it.
        config_ui_scrolled = Gtk.ScrolledWindow()
        config_ui_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        config_ui_scrolled.props.propagate_natural_height = True
        config_ui_scrolled.add(effect_config_ui)
        config_ui_revealer = Gtk.Revealer()
        config_ui_revealer.add(config_ui_scrolled)

        expander = Gtk.Expander()
        expander.set_label_widget(name_box)
        expander.props.valign = Gtk.Align.CENTER

        expander.connect("notify::expanded", self._toggle_expander_cb, config_ui_revealer)

        active_button = Gtk.Button()
        remove_effect_button = Gtk.Button(label=_("Remove"))
        remove_effect_button.props.relief = Gtk.ReliefStyle.NONE
        remove_effect_button.get_style_context().add_class("spl-danger-text")

        row_widgets_box = Gtk.Box(spacing=PADDING)
        row_widgets_box.props.margin = PADDING
        row_widgets_box.pack_start(thumbnail, False, False, 0)
        row_widgets_box.pack_start(expander, True, True, 0)
        row_widgets_box.pack_start(active_button, False, False, 0)
        row_widgets_box.pack_start(remove_effect_button, False, False, 0)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.pack_start(row_widgets_box, False, False, 0)
        vbox.pack_start(config_ui_revealer, False, False, 0)

        event_box = Gtk.EventBox()
        event_box.add(vbox)

        row = Gtk.ListBoxRow(selectable=False, activatable=False)
        row.effect = effect
        row.active_button = active_button
        row.state_label = state_label
        row.dimmed_widgets = (thumbnail, name_box)
        row.add(event_box)
        self.__update_row_active_state(row)

        # Set up drag&drop
        event_box.drag_source_set(Gdk.ModifierType.BUTTON1_MASK,
                                  [EFFECT_TARGET_ENTRY], Gdk.DragAction.MOVE)
        event_box.connect("drag-begin", self._drag_begin_cb)
        event_box.connect("drag-data-get", self._drag_data_get_cb)

        row.drag_dest_set(Gtk.DestDefaults.ALL, [EFFECT_TARGET_ENTRY],
                          Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        row.connect("drag-data-received", self._drag_data_received_cb)

        remove_effect_button.connect("clicked", self._remove_button_cb, row)
        active_button.connect("clicked", self._effect_active_button_cb, row)

        return row

    @staticmethod
    def __update_row_active_state(row):
        """Shows whether the effect of the row is active."""
        active = row.effect.props.active
        row.active_button.set_label(_("Deactivate") if active else _("Activate"))
        row.state_label.set_text(_("Active") if active else _("Deactivated"))
        for widget in row.dimmed_widgets:
            widget.set_opacity(1 if active else 0.45)

    def _update_listbox(self):
        for row in self.effects_listbox.get_children():
            self.effects_listbox.remove(row)

        for effect in self.clip.get_top_effects():
            effect_row = self._create_effect_row(effect)
            if effect_row:
                self.effects_listbox.add(effect_row)

        self.effects_listbox.show_all()
        self.__update_hint()

    def __update_hint(self):
        self.hint_label.set_visible(bool(self.effects_listbox.get_children()))
        self.emit("effects-changed")

    def _toggle_expander_cb(self, expander, unused_prop, revealer):
        revealer.props.reveal_child = expander.props.expanded

    def _get_effect_row(self, effect):
        for row in self.effects_listbox.get_children():
            if row.effect == effect:
                return row
        return None

    def _add_effect_row(self, effect):
        row = self._create_effect_row(effect)
        if not row:
            return

        self.effects_listbox.add(row)
        self.effects_listbox.show_all()
        self.__update_hint()

    def _remove_effect_row(self, effect):
        row = self._get_effect_row(effect)
        if row:
            self.effects_listbox.remove(row)
            self.__update_hint()

    def _move_effect_row(self, effect, new_index):
        row = self._get_effect_row(effect)
        self.effects_listbox.remove(row)
        self.effects_listbox.insert(row, new_index)

    def _remove_button_cb(self, button, row):
        effect = row.effect
        self._remove_effect(effect)

    def _remove_effect(self, effect):
        pipeline = self.app.project_manager.current_project.pipeline
        with self.app.action_log.started("remove effect",
                                         finalizing_action=CommitTimelineFinalizingAction(pipeline),
                                         toplevel=True):
            effect.get_parent().remove(effect)

    def _effect_active_button_cb(self, unused_button, row):
        effect = row.effect
        pipeline = self.app.project_manager.current_project.pipeline
        with self.app.action_log.started("change active state",
                                         finalizing_action=CommitTimelineFinalizingAction(pipeline),
                                         toplevel=True):
            effect.props.active = not effect.props.active

    def set_clip(self, clip):
        if self.clip:
            self.clip.disconnect_by_func(self._track_element_added_cb)
            self.clip.disconnect_by_func(self._track_element_removed_cb)
            for effect in self.clip.get_top_effects():
                if is_time_effect(effect):
                    continue
                self._disconnect_from_track_element(effect)

        self.clip = clip
        if self.clip:
            cover_object_button_show = False
            self.clip.connect("child-added", self._track_element_added_cb)
            self.clip.connect("child-removed", self._track_element_removed_cb)
            for track_element in self.clip.get_children(recursive=True):
                if isinstance(track_element, GES.BaseEffect):
                    if is_time_effect(track_element):
                        continue
                    self._connect_to_track_element(track_element)
                if isinstance(track_element, GES.VideoUriSource) and not clip.asset.is_image():
                    cover_object_button_show = True
            if self.cover_object_button:
                self.cover_object_button.set_visible(cover_object_button_show)
                if cover_object_button_show:
                    self.cover_popover = CoverObjectPopover(self.app, self.clip)
                    self.cover_object_button.set_popover(self.cover_popover)
            self._update_listbox()

        self.props.visible = bool(self.clip)
        self.emit("effects-changed")

    def _track_element_added_cb(self, unused_clip, track_element):
        if isinstance(track_element, GES.BaseEffect):
            self._connect_to_track_element(track_element)
            self._add_effect_row(track_element)

    def _connect_to_track_element(self, track_element):
        track_element.connect("notify::active", self._notify_active_cb)
        track_element.connect("notify::priority", self._notify_priority_cb)

    def _disconnect_from_track_element(self, track_element):
        track_element.disconnect_by_func(self._notify_active_cb)
        track_element.disconnect_by_func(self._notify_priority_cb)

    def _notify_active_cb(self, track_element, unused_param_spec):
        row = self._get_effect_row(track_element)
        if row:
            self.__update_row_active_state(row)

    def _notify_priority_cb(self, track_element, unused_param_spec):
        if not self._get_effect_row(track_element):
            return

        # Some effects are not listed.
        listed_effects = [effect for effect in self.clip.get_top_effects()
                          if self._get_effect_row(effect)]
        index = listed_effects.index(track_element)
        row = self.effects_listbox.get_row_at_index(index)

        if not row:
            return

        if row.effect != track_element:
            self._move_effect_row(track_element, index)

    def _track_element_removed_cb(self, unused_clip, track_element):
        if isinstance(track_element, GES.BaseEffect):
            self._disconnect_from_track_element(track_element)
            self._remove_effect_row(track_element)

    def _drag_begin_cb(self, eventbox, context):
        """Draws the drag icon."""
        row = eventbox.get_parent()
        alloc = row.get_allocation()

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, alloc.width, alloc.height)
        ctx = cairo.Context(surface)

        row.draw(ctx)
        ctx.paint_with_alpha(0.35)

        Gtk.drag_set_icon_surface(context, surface)

    def _drag_data_get_cb(self, eventbox, drag_context, selection_data, unused_info, unused_timestamp):
        row = eventbox.get_parent()
        effect_info = self.app.effects.get_info(row.effect)
        effect_name = effect_info.human_name

        data = bytes(effect_name, "UTF-8")
        selection_data.set(drag_context.list_targets()[0], 0, data)

    def _drag_motion_cb(self, unused_widget, unused_drag_context, unused_x, y, unused_timestamp):
        """Highlights some widgets to indicate it can receive drag&drop."""
        self.debug(
            "Something is being dragged in the clip properties' effects list")
        row = self.effects_listbox.get_row_at_y(y)
        if row:
            self.effects_listbox.drag_highlight_row(row)
            self.expander_box.drag_unhighlight()
        else:
            self.effects_listbox.drag_highlight()

    def _drag_leave_cb(self, unused_widget, drag_context, unused_timestamp):
        """Unhighlights the widgets which can receive drag&drop."""
        self.debug(
            "The item being dragged has left the clip properties' effects list")

        self.effects_listbox.drag_unhighlight_row()
        self.effects_listbox.drag_unhighlight()

    def __get_time_effects(self):
        return [effect for effect in self.clip.get_top_effects() if is_time_effect(effect)]

    def _drag_data_received_cb(self, widget, drag_context, x, y, selection_data, unused_info, timestamp):
        if not self.clip:
            # Indicate that a drop will not be accepted.
            Gdk.drag_status(drag_context, 0, timestamp)
            return

        if self.effects_listbox.get_row_at_y(y):
            # Drop happened inside the lisbox
            drop_index = widget.get_index()
        else:
            drop_index = len(self.effects_listbox.get_children())

        if drag_context.get_suggested_action() == Gdk.DragAction.COPY:
            # An effect dragged probably from the effects list.
            factory_name = str(selection_data.get_data(), "UTF-8")

            top_effect_index = drop_index + len(self.__get_time_effects())
            self.debug("Effect dragged at position %s - computed top effect index %s",
                       drop_index, top_effect_index)
            effect_info = self.app.effects.get_info(factory_name)
            pipeline = self.app.project_manager.current_project.pipeline
            with self.app.action_log.started("add effect",
                                             finalizing_action=CommitTimelineFinalizingAction(
                                                 pipeline),
                                             toplevel=True):
                effect = self.clip.ui.add_effect(effect_info)
                if effect:
                    self.clip.set_top_effect_index(effect, top_effect_index)

        elif drag_context.get_suggested_action() == Gdk.DragAction.MOVE:
            # An effect dragged from the same listbox to change its position.
            source_eventbox = Gtk.drag_get_source_widget(drag_context)
            source_row = source_eventbox.get_parent()
            source_index = source_row.get_index()

            self._move_effect(self.clip, source_index, drop_index)

        drag_context.finish(True, False, timestamp)

    def _move_effect(self, clip, source_index, drop_index):
        # Handle edge cases
        drop_index = min(max(0, drop_index), len(clip.get_top_effects()) - 1)
        if source_index == drop_index:
            # Noop.
            return

        time_effects = self.__get_time_effects()
        effect_index = source_index + len(time_effects)
        wanted_index = drop_index + len(time_effects)
        effects = clip.get_top_effects()
        effect = effects[effect_index]
        pipeline = self.app.project_manager.current_project.pipeline

        with self.app.action_log.started("move effect",
                                         finalizing_action=CommitTimelineFinalizingAction(
                                             pipeline),
                                         toplevel=True):
            clip.set_top_effect_index(effect, wanted_index)


class TransformationProperties(Gtk.Expander, Loggable):
    """Widget for configuring the placement and size of the clip."""

    def __init__(self, app):
        Gtk.Expander.__init__(self)
        Loggable.__init__(self)
        self.app = app
        self._project = None
        self.source = None
        self.spin_buttons = {}
        self.spin_buttons_handler_ids = {}
        self.set_label(_("Framing"))
        self.set_expanded(True)
        self._aspect_ratio: Optional[Gst.Fraction] = None

        self.builder = Gtk.Builder()
        self.builder.add_from_file(os.path.join(get_ui_dir(),
                                                "cliptransformation.ui"))

        alignment_editor_container = self.builder.get_object("clip_alignment")
        self.alignment_editor = AlignmentEditor()
        self.alignment_editor.connect("align", self.__alignment_editor_align_cb)
        alignment_editor_container.pack_start(self.alignment_editor, True, True, 0)

        self.__control_bindings = {}
        # Used to make sure self.__control_bindings_changed doesn't get called
        # when bindings are changed from this class
        self.__own_bindings_change = False
        self._updating_framing_ui = False
        self._notify_meta_id = 0

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        self._framing_box = self.__create_framing_buttons()
        box.pack_start(self._framing_box, False, False, 0)
        self.blur_box = self.__create_blur_box()
        box.pack_start(self.blur_box, False, False, 0)
        self._orientation_box = self.__create_orientation_buttons()
        box.pack_start(self._orientation_box, False, False, 0)
        # The position and size fields are not for beginners: the clip can
        # be placed by dragging it in the viewer. They are kept hidden
        # because they reflect the state of the source.
        transform_box = self.builder.get_object("transform_box")
        transform_box.set_no_show_all(True)
        transform_box.hide()
        box.pack_start(transform_box, False, False, 0)
        self.add(box)

        self._init_buttons()
        self.show_all()
        self.hide()

        self.app.project_manager.connect_after(
            "new-project-loaded", self._new_project_loaded_cb)
        self.app.project_manager.connect_after(
            "project-closed", self.__project_closed_cb)

    def __create_framing_buttons(self):
        """Creates the buttons to fit or fill the frame with the clip."""
        self.fit_button = Gtk.ToggleButton(label=_("Fit"))
        self.fit_button.set_tooltip_text(
            _("Show the whole image. There can be bars on the sides."))
        self.fit_button.connect("clicked", self.__framing_button_clicked_cb, False)

        self.fill_button = Gtk.ToggleButton(label=_("Fill"))
        self.fill_button.set_tooltip_text(
            _("Cover the whole frame. Part of the image can be left out."))
        self.fill_button.connect("clicked", self.__framing_button_clicked_cb, True)

        self.blur_fill_button = Gtk.ToggleButton(label=_("Blurred fill"))
        self.blur_fill_button.set_tooltip_text(
            _("Show the whole image, over a blurred copy filling the frame."))
        self.blur_fill_button.connect("clicked", self.__blur_fill_button_clicked_cb)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.get_style_context().add_class("linked")
        box.props.halign = Gtk.Align.START
        box.props.margin_start = SPACING
        box.pack_start(self.fit_button, False, False, 0)
        box.pack_start(self.fill_button, False, False, 0)
        box.pack_start(self.blur_fill_button, False, False, 0)
        return box

    def __create_blur_box(self):
        """Creates the slider to regulate the blur of the blurred fill."""
        blur_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        blur_box.props.margin_start = SPACING
        blur_box.props.margin_end = SPACING
        blur_box.props.margin_top = 2
        blur_box.props.margin_bottom = 2

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.pack_start(Gtk.Label(label=_("Blur:"), xalign=0), True, True, 0)
        self.blur_value_label = Gtk.Label(halign=Gtk.Align.END)
        header.pack_end(self.blur_value_label, False, False, 0)
        blur_box.pack_start(header, False, False, 0)

        self.blur_adjustment = Gtk.Adjustment(
            value=30, lower=5, upper=100, step_increment=1, page_increment=5, page_size=0)
        self.blur_value_label.set_markup("<b>%d %%</b>" % round(self.blur_adjustment.props.value))
        self.blur_scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.blur_adjustment)
        self.blur_scale.set_draw_value(False)
        self.blur_scale.set_hexpand(True)
        self.blur_scale.connect("value-changed", self.__blur_scale_value_changed_cb)
        blur_box.pack_start(self.blur_scale, False, False, 0)

        blur_box.show_all()
        blur_box.set_no_show_all(True)
        blur_box.hide()
        return blur_box

    def __blur_scale_value_changed_cb(self, scale):
        val = scale.get_value()
        self.blur_value_label.set_markup("<b>%d %%</b>" % round(val))
        if self._updating_framing_ui or not self.source:
            return
        sigma = val * 0.2
        pipeline = self._project.pipeline if self._project else None
        finalizing_action = CommitTimelineFinalizingAction(pipeline) if pipeline else None
        with self.app.action_log.started("Blurred fill",
                                         finalizing_action=finalizing_action,
                                         mergeable=True,
                                         toplevel=True):
            set_blur_sigma(self.source, sigma)

    def __notify_meta_cb(self, unused_source, key, unused_value):
        if key == BLUR_SIGMA_META and not self._updating_framing_ui and self.source:
            self._updating_framing_ui = True
            try:
                sigma = get_blur_sigma(self.source)
                self.blur_adjustment.props.value = round(sigma / 0.2)
                self.blur_value_label.set_markup("<b>%d %%</b>" % round(self.blur_adjustment.props.value))
                clip = self.source.get_parent()
                if clip:
                    effect = get_blur_fill(clip)
                    if effect:
                        effect.set_child_property("sigma", float(sigma))
            finally:
                self._updating_framing_ui = False

    def __update_framing_buttons(self):
        if not self.source:
            self._updating_framing_ui = True
            try:
                self.fit_button.set_active(False)
                self.fill_button.set_active(False)
                self.blur_fill_button.set_active(False)
                self.blur_box.hide()
            finally:
                self._updating_framing_ui = False
            return

        clip = self.source.get_parent()
        has_blur = bool(clip and get_blur_fill(clip))

        self._updating_framing_ui = True
        try:
            if has_blur:
                self.fit_button.set_active(False)
                self.fill_button.set_active(False)
                self.blur_fill_button.set_active(True)
                self.blur_box.show()
                sigma = get_blur_sigma(self.source)
                self.blur_adjustment.props.value = round(sigma / 0.2)
                self.blur_value_label.set_markup("<b>%d %%</b>" % round(self.blur_adjustment.props.value))
            else:
                self.blur_fill_button.set_active(False)
                self.blur_box.hide()
                pos = self.__get_position()
                fit_pos = self.get_framing_position(False)
                fill_pos = self.get_framing_position(True)
                if fit_pos and fill_pos:
                    is_fill = (pos == fill_pos and fill_pos != fit_pos)
                    is_fit = (pos == fit_pos)
                else:
                    is_fill = False
                    is_fit = False
                self.fit_button.set_active(is_fit)
                self.fill_button.set_active(is_fill)
        finally:
            self._updating_framing_ui = False

    def __blur_fill_button_clicked_cb(self, unused_button):
        if self._updating_framing_ui or not self.source:
            return
        clip = self.source.get_parent()
        if not clip:
            return
        with self.app.action_log.started("Blurred fill",
                                         finalizing_action=CommitTimelineFinalizingAction(
                                             self._project.pipeline),
                                         toplevel=True):
            # The zoom moves the source, which the blurred fill covers.
            set_zoom(self.source, None)
            set_blur_fill(clip, True)
            layer = clip.get_layer()
            if layer:
                sync_pushes(layer)
        self.__update_keyframes_ui()
        self.__update_framing_buttons()
        zoom_expander = getattr(self.app.gui.editor.clipconfig, "zoom_expander", None) \
            if hasattr(self.app.gui, "editor") else None
        if isinstance(zoom_expander, Gtk.Widget):
            zoom_expander.set_source(None)

    def __create_orientation_buttons(self):
        """Creates the buttons to rotate and mirror the clip."""
        def create_button(icon_name, tooltip, turn):
            button = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
            button.set_tooltip_text(tooltip)
            button.connect("clicked", self.__orientation_button_clicked_cb, turn)
            return button

        self.rotate_left_button = create_button(
            "object-rotate-left-symbolic", _("Rotate left"),
            lambda orientation: orientation.rotated(-90))
        self.rotate_right_button = create_button(
            "object-rotate-right-symbolic", _("Rotate right"),
            lambda orientation: orientation.rotated(90))
        self.mirror_horizontally_button = create_button(
            "object-flip-horizontal-symbolic", _("Mirror horizontally"),
            Orientation.mirrored_horizontally)
        self.mirror_vertically_button = create_button(
            "object-flip-vertical-symbolic", _("Mirror vertically"),
            Orientation.mirrored_vertically)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACING)
        box.props.halign = Gtk.Align.START
        box.props.margin_start = SPACING
        for buttons in ((self.rotate_left_button, self.rotate_right_button),
                        (self.mirror_horizontally_button, self.mirror_vertically_button)):
            linked_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            linked_box.get_style_context().add_class("linked")
            for button in buttons:
                linked_box.pack_start(button, False, False, 0)
            box.pack_start(linked_box, False, False, 0)
        return box

    def __orientation_button_clicked_cb(self, unused_button, turn):
        if not self.source:
            return
        clip = self.source.get_parent()
        if not clip:
            return
        orientation = get_orientation(clip)
        new_orientation = turn(orientation)
        # Keep filling the frame if it was filled, otherwise fit the clip.
        fill_position = self.get_framing_position(True)
        fill = self.__get_position() == fill_position != self.get_framing_position(False)
        with self.app.action_log.started("Transformation orientation",
                                         finalizing_action=CommitTimelineFinalizingAction(
                                             self._project.pipeline),
                                         toplevel=True):
            set_orientation(clip, new_orientation)
            if get_blur_fill(clip):
                # The blurred fill is made again for the turned image.
                update_blur_fill(clip)
            elif new_orientation.swaps_dimensions != orientation.swaps_dimensions:
                # The image keeps its aspect ratio, so it has to be framed again.
                self.__set_framing(self.get_framing_position(fill))

        self.__update_keyframes_ui()
        self.__update_framing_buttons()

    def __get_position(self):
        return get_base_position(self.source)

    def get_framing_position(self, fill):
        """Returns the position for fitting or filling the frame with the clip.

        Args:
            fill (bool): Whether the clip should cover the whole frame,
                otherwise the whole clip is shown.
        """
        # The default position fits the clip, keeping its aspect ratio.
        ui = getattr(self.source, "ui", None)
        if not ui or not hasattr(ui, "default_position"):
            return None
        position = dict(ui.default_position)
        asset = self.source.get_asset()
        stream_info = asset.get_stream_info() \
            if isinstance(asset, GES.UriSourceAsset) else None
        if not fill or not stream_info:
            # Titles and color clips always cover the whole frame.
            return position

        return get_fill_position(position, self._project.videowidth, self._project.videoheight)

    def __set_framing(self, position):
        """Places the source, keeping its zoom and its pushes, if any."""
        if has_motion(self.source):
            set_base_position(self.source, position)
            clip = self.source.get_parent()
            layer = clip.get_layer() if clip else None
            if layer:
                sync_pushes(layer)
            return

        if self.__source_uses_keyframes():
            self.__remove_control_bindings()
        for prop, value in position.items():
            self.source.set_child_property(prop, value)

    def __framing_button_clicked_cb(self, unused_button, fill):
        if self._updating_framing_ui or not self.source:
            return
        position = self.get_framing_position(fill)
        if not position:
            return
        with self.app.action_log.started("Transformation framing",
                                         finalizing_action=CommitTimelineFinalizingAction(
                                             self._project.pipeline),
                                         toplevel=True):
            clip = self.source.get_parent()
            if clip and get_blur_fill(clip):
                set_blur_fill(clip, False)
                zoom_expander = getattr(self.app.gui.editor.clipconfig, "zoom_expander", None) \
                    if hasattr(self.app.gui, "editor") else None
                if isinstance(zoom_expander, Gtk.Widget):
                    zoom_expander.set_source(self.source)
            self.__set_framing(position)

        self.__update_keyframes_ui()
        self.__update_framing_buttons()

    def _new_project_loaded_cb(self, unused_project_manager, project):
        if self._project:
            self._project.pipeline.disconnect_by_func(self._position_cb)

        self._project = project
        if project:
            self._project.pipeline.connect("position", self._position_cb)

    def __project_closed_cb(self, unused_project_manager, unused_project):
        self._project = None

    def __alignment_editor_align_cb(self, widget):
        """Callback method to align a clip from the AlignmentEditor widget."""
        x, y = self.alignment_editor.get_clip_position(self._project, self.source)
        with self.app.action_log.started("Position change",
                                         finalizing_action=CommitTimelineFinalizingAction(self._project.pipeline),
                                         toplevel=True):
            self.__set_prop("posx", x)
            self.__set_prop("posy", y)

    def _update_aspect_ratio_button_image(self):
        image = self.builder.get_object("aspect_ratio_image")
        if self._aspect_ratio is not None:
            icon_name = "chain-connected-symbolic"
        else:
            icon_name = "chain-broken-symbolic"
        image.props.icon_name = icon_name

    def _init_buttons(self):
        clear_button = self.builder.get_object("clear_button")
        clear_button.connect("clicked", self._default_values_cb)

        self._activate_keyframes_btn = self.builder.get_object(
            "activate_keyframes_button")
        self._activate_keyframes_btn.connect(
            "toggled", self.__show_keyframes_toggled_cb)

        self._next_keyframe_btn = self.builder.get_object(
            "next_keyframe_button")
        self._next_keyframe_btn.connect(
            "clicked", self.__go_to_keyframe_cb, True)
        self._next_keyframe_btn.set_sensitive(False)

        self._prev_keyframe_btn = self.builder.get_object(
            "prev_keyframe_button")
        self._prev_keyframe_btn.connect(
            "clicked", self.__go_to_keyframe_cb, False)
        self._prev_keyframe_btn.set_sensitive(False)

        self.__setup_spin_button("xpos_spinbtn", "posx")
        self.__setup_spin_button("ypos_spinbtn", "posy")

        self.__setup_spin_button("width_spinbtn", "width")
        self.__setup_spin_button("height_spinbtn", "height")

        self.aspect_ratio_button = self.builder.get_object("aspect_ratio_button")
        self.aspect_ratio_button.connect("clicked", self._aspect_ratio_button_clicked_cb)
        self._update_aspect_ratio_button_image()

    def __get_keyframes_timestamps(self):
        keyframes_ts = []
        for prop in ["posx", "posy", "width", "height"]:
            prop_keyframes = self.__control_bindings[prop].props.control_source.get_all(
            )
            keyframes_ts.extend(
                [keyframe.timestamp for keyframe in prop_keyframes])

        return sorted(set(keyframes_ts))

    def __go_to_keyframe_cb(self, unused_button, next_keyframe):
        assert self.__control_bindings
        start = self.source.props.start
        in_point = self.source.props.in_point
        pipeline = self._project.pipeline
        position = pipeline.get_position() - start + in_point
        keyframes_ts = self.__get_keyframes_timestamps()
        if next_keyframe:
            i = bisect.bisect_right(keyframes_ts, position)
        else:
            i = bisect.bisect_left(keyframes_ts, position) - 1
        i = max(0, min(i, len(keyframes_ts) - 1))
        seekval = keyframes_ts[i] + start - in_point
        pipeline.simple_seek(seekval)

    def __show_keyframes_toggled_cb(self, unused_button):
        if self._activate_keyframes_btn.props.active:
            self.__set_control_bindings()
        self.__update_keyframes_ui()

    def __update_keyframes_ui(self):
        if self.__source_uses_keyframes():
            self._activate_keyframes_btn.props.label = "◆"
        else:
            self._activate_keyframes_btn.props.label = "◇"
            self._activate_keyframes_btn.props.active = False

        if not self._activate_keyframes_btn.props.active:
            self._prev_keyframe_btn.set_sensitive(False)
            self._next_keyframe_btn.set_sensitive(False)
            if self.__source_uses_keyframes():
                self._activate_keyframes_btn.set_tooltip_text(
                    _("Show keyframes"))
            else:
                self._activate_keyframes_btn.set_tooltip_text(
                    _("Activate keyframes"))
            self.source.ui.show_default_keyframes()
        else:
            self._prev_keyframe_btn.set_sensitive(True)
            self._next_keyframe_btn.set_sensitive(True)
            self._activate_keyframes_btn.set_tooltip_text(_("Hide keyframes"))
            self.source.ui.show_multiple_keyframes(
                list(self.__control_bindings.values()))

    def __update_control_bindings(self):
        self.__control_bindings = {}
        if self.__source_uses_keyframes():
            self.__set_control_bindings()

    def __source_uses_keyframes(self):
        if self.source is None:
            return False

        for prop in ["posx", "posy", "width", "height"]:
            binding = self.source.get_control_binding(prop)
            if binding is None:
                return False

        return True

    def __remove_control_bindings(self):
        for propname, binding in self.__control_bindings.items():
            control_source = binding.props.control_source
            # control_source.unset_all() can't be used here as it doesn't emit
            # the 'value-removed' signal, so the undo system wouldn't notice
            # the removed keyframes
            keyframes_ts = [
                keyframe.timestamp for keyframe in control_source.get_all()]
            for ts in keyframes_ts:
                control_source.unset(ts)
            self.__own_bindings_change = True
            self.source.remove_control_binding(propname)
            self.__own_bindings_change = False
        self.__control_bindings = {}

    def __set_control_bindings(self):
        adding_kfs = not self.__source_uses_keyframes()

        if adding_kfs:
            self.app.action_log.begin("Transformation properties keyframes activate",
                                      toplevel=True)

        for prop in ["posx", "posy", "width", "height"]:
            binding = self.source.get_control_binding(prop)

            if not binding:
                control_source = GstController.InterpolationControlSource()
                control_source.props.mode = GstController.InterpolationMode.LINEAR
                self.__own_bindings_change = True
                try:
                    self.source.set_control_source(control_source, prop, "direct-absolute")
                finally:
                    self.__own_bindings_change = False
                self.__set_default_keyframes_values(control_source, prop)

                binding = self.source.get_control_binding(prop)
            self.__control_bindings[prop] = binding

        if adding_kfs:
            self.app.action_log.commit(
                "Transformation properties keyframes activate")

    def __set_default_keyframes_values(self, control_source, prop):
        res, val = self.source.get_child_property(prop)
        assert res
        control_source.set(self.source.props.in_point, val)
        control_source.set(self.source.props.in_point +
                           self.source.props.duration, val)

    def _default_values_cb(self, unused_widget):
        with self.app.action_log.started("Transformation properties reset default",
                                         finalizing_action=CommitTimelineFinalizingAction(
                                             self._project.pipeline),
                                         toplevel=True):
            if self.__source_uses_keyframes():
                self.__remove_control_bindings()

            for prop in ["posx", "posy", "width", "height"]:
                self.source.set_child_property(
                    prop, self.source.ui.default_position[prop])

        self.__update_keyframes_ui()
        self.__update_framing_buttons()

    def __get_source_property(self, prop):
        if self.__source_uses_keyframes():
            try:
                position = self._project.pipeline.get_position()
                start = self.source.props.start
                in_point = self.source.props.in_point
                duration = self.source.props.duration

                # If the position is outside of the clip, take the property
                # value at the start/end (whichever is closer) of the clip.
                source_position = max(
                    0, min(position - start, duration - 1)) + in_point
                value = self.__control_bindings[prop].get_value(
                    source_position)
                res = value is not None
                return res, value
            except PipelineError:
                pass

        return self.source.get_child_property(prop)

    def _position_cb(self, unused_pipeline, unused_position):
        if not self.__source_uses_keyframes():
            return

        for prop in ["posx", "posy", "width", "height"]:
            self.__update_spin_btn(prop)
        # Keep the overlay stack in sync with the spin buttons values
        self.app.gui.editor.viewer.overlay_stack.update(self.source)

    def __source_property_changed_cb(self, unused_source, unused_element, param):
        self.__update_spin_btn(param.name)
        if param.name in ("posx", "posy", "width", "height"):
            self.__update_framing_buttons()

    def __update_spin_btn(self, prop):
        assert self.source

        try:
            spin = self.spin_buttons[prop]
            spin_handler_id = self.spin_buttons_handler_ids[prop]
        except KeyError:
            return

        res, value = self.__get_source_property(prop)
        assert res
        if spin.get_value() != value:
            # Make sure self._on_value_changed_cb doesn't get called here. If that
            # happens, we might have unintended keyframes added.
            with spin.handler_block(spin_handler_id):
                spin.set_value(value)

    def _control_bindings_changed(self, unused_track_element, unused_binding):
        if self.__own_bindings_change:
            # Do nothing if the change occurred from this class
            return

        self.__update_control_bindings()
        self.__update_keyframes_ui()

    def __set_prop(self, prop, value):
        assert self.source

        if self.__source_uses_keyframes():
            try:
                position = self._project.pipeline.get_position()
                start = self.source.props.start
                in_point = self.source.props.in_point
                duration = self.source.props.duration
                if position < start or position > start + duration:
                    return
                source_position = position - start + in_point

                self.__control_bindings[prop].props.control_source.set(
                    source_position, value)
            except PipelineError:
                self.warning("Could not get pipeline position")
                return
        else:
            self.source.set_child_property(prop, value)

    def __setup_spin_button(self, widget_name, property_name):
        """Creates a SpinButton for editing a property value."""
        spinbtn = self.builder.get_object(widget_name)
        handler_id = spinbtn.connect(
            "value-changed", self._on_value_changed_cb, property_name)
        self.spin_buttons[property_name] = spinbtn
        self.spin_buttons_handler_ids[property_name] = handler_id

    def _aspect_ratio_button_clicked_cb(self, aspect_ratio_button):
        if self._aspect_ratio is None:
            res, width = self.__get_source_property("width")
            assert res
            res, height = self.__get_source_property("height")
            assert res
            self._aspect_ratio = Gst.Fraction(width, height)
        else:
            self._aspect_ratio = None
        self._update_aspect_ratio_button_image()

    def _on_value_changed_cb(self, spinbtn, prop):
        if not self.source:
            return

        value = int(spinbtn.get_value())
        res, cvalue = self.__get_source_property(prop)
        if not res:
            return

        if value != cvalue:
            with self.app.action_log.started("Transformation property change",
                                             finalizing_action=CommitTimelineFinalizingAction(self._project.pipeline),
                                             toplevel=True):
                self.__set_prop(prop, value)
                if self._aspect_ratio is not None:
                    if prop == "width":
                        fraction = value / self._aspect_ratio
                        height = int(fraction.num / fraction.denom)
                        self.__set_prop("height", height)
                    if prop == "height":
                        fraction = value * self._aspect_ratio
                        width = int(fraction.num / fraction.denom)
                        self.__set_prop("width", width)
            self.app.gui.editor.viewer.overlay_stack.update(self.source)

    def set_source(self, source):
        self.debug("Setting source to %s", source)

        if self.source:
            self.source.disconnect_by_func(self.__source_property_changed_cb)
            if self._notify_meta_id:
                self.source.disconnect(self._notify_meta_id)
                self._notify_meta_id = 0
            disconnect_all_by_func(self.source, self._control_bindings_changed)

        self.source = source

        if self.source:
            self.__update_control_bindings()
            for prop in self.spin_buttons:
                self.__update_spin_btn(prop)
            self.__update_keyframes_ui()
            self.source.connect("deep-notify", self.__source_property_changed_cb)
            self._notify_meta_id = self.source.connect("notify-meta", self.__notify_meta_cb)
            self.source.connect("control-binding-added", self._control_bindings_changed)
            self.source.connect("control-binding-removed", self._control_bindings_changed)

        self.__update_framing_buttons()

        # Titles and color clips always cover the whole frame, so there is
        # nothing to choose for them.
        self.set_visible(bool(self.source) and
                         isinstance(self.source.get_asset(), GES.UriSourceAsset))
