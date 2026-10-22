# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2005, Edward Hervey <bilboed@bilboed.com>
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
import math
import os
from gettext import gettext as _
from time import time
from urllib.parse import unquote

import cairo
from gi.repository import Gdk
from gi.repository import GES
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Pango

from pitivi.clipproperties import ClipProperties
from pitivi.configure import APPNAME
from pitivi.configure import get_ui_dir
from pitivi.dialogs.missingasset import MissingAssetDialog
from pitivi.dialogs.projectsettings import ProjectSettingsDialog
from pitivi.editorstate import EditorState
from pitivi.effects import EffectListWidget
from pitivi.effects import SimpleEffectsCatalog
from pitivi.interactiveintro import InteractiveIntro
from pitivi.mediafilespreviewer import PreviewWidget
from pitivi.medialibrary import MediaLibraryWidget
from pitivi.perspective import Perspective
from pitivi.settings import GlobalSettings
from pitivi.tabsmanager import BaseTabs
from pitivi.timeline.previewers import ThumbnailCache
from pitivi.timeline.timeline import TimelineContainer
from pitivi.timeline.transitions import TransitionPropertiesWidget
from pitivi.utils.loggable import Loggable
from pitivi.utils.misc import path_from_uri
from pitivi.utils.misc import with_build_label
from pitivi.utils.ui import beautify_time_delta
from pitivi.utils.ui import EDITOR_PERSPECTIVE_CSS
from pitivi.utils.ui import info_name
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING
from pitivi.viewer.viewer import ViewerContainer


GlobalSettings.add_config_section("main-window")
GlobalSettings.add_config_option('timelinePanelHeight',
                                 section="main-window",
                                 key="timeline-panel-height",
                                 type_=int)
GlobalSettings.add_config_option('filesPanelWidth',
                                 section="main-window",
                                 key="files-panel-width",
                                 type_=int)
GlobalSettings.add_config_option('propertiesPanelWidth',
                                 section="main-window",
                                 key="properties-panel-width",
                                 type_=int)
GlobalSettings.add_config_option('propertiesPanelCollapsed',
                                 section="main-window",
                                 key="properties-panel-collapsed",
                                 default=False)
GlobalSettings.add_config_option('lastProjectFolder',
                                 section="main-window",
                                 key="last-folder",
                                 environment="PITIVI_PROJECT_FOLDER",
                                 default=os.path.expanduser("~"))


class EditorPerspective(Perspective, Loggable):
    """Pitivi's Editor perspective.

    Attributes:
        app (Pitivi): The app.
    """

    def __init__(self, app):
        Perspective.__init__(self)
        Loggable.__init__(self)

        self.app = app
        self.settings = app.settings

        self.builder = Gtk.Builder()
        self.editor_state = EditorState(app.project_manager)

        pm = self.app.project_manager
        pm.connect("new-project-loaded",
                   self._project_manager_new_project_loaded_cb)
        pm.connect("save-project-failed",
                   self._project_manager_save_project_failed_cb)
        pm.connect("project-saved", self._project_manager_project_saved_cb)
        pm.connect("closing-project", self._project_manager_closing_project_cb)
        pm.connect("reverting-to-saved",
                   self._project_manager_reverting_to_saved_cb)
        pm.connect("project-closed", self._project_manager_project_closed_cb)
        pm.connect("missing-uri", self._project_manager_missing_uri_cb)

    def setup_ui(self):
        """Sets up the UI."""
        self.__setup_css()
        self._create_ui()
        self.app.gui.connect("focus-in-event", self.__focus_in_event_cb)
        self.app.gui.connect("destroy", self._destroyed_cb)

    def activate_compact_mode(self):
        """Shrinks widgets to suit better a small screen."""
        self.medialibrary.activate_compact_mode()
        self.viewer.activate_compact_mode()

    def refresh(self):
        """Refreshes the perspective."""
        self.timeline_ui.restore_state()
        self.focus_timeline()

    def __setup_css(self):
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(EDITOR_PERSPECTIVE_CSS.encode("UTF-8"))
        screen = Gdk.Screen.get_default()
        style_context = self.app.gui.get_style_context()
        style_context.add_provider_for_screen(screen, css_provider,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def __focus_in_event_cb(self, unused_widget, unused_event):
        ges_timeline = self.timeline_ui.timeline.ges_timeline
        if not ges_timeline:
            # Nothing to work with, Pitivi is starting up.
            return

        if self.app.project_manager.current_project.pipeline.rendering():
            return

        # Commit the timeline so its nested timelines assets are refreshed.
        ges_timeline.commit()

        # We need to track the changed assets ourselves.
        changed_files_uris = ThumbnailCache.update_caches()
        if changed_files_uris:
            self.medialibrary.update_asset_thumbs(changed_files_uris)

            for ges_layer in ges_timeline.get_layers():
                for ges_clip in ges_layer.get_clips():
                    if ges_clip.get_asset().props.id in changed_files_uris:
                        if ges_clip.ui.audio_widget:
                            ges_clip.ui.audio_widget.update_previewer()
                        if ges_clip.ui.video_widget:
                            ges_clip.ui.video_widget.update_previewer()

    def _destroyed_cb(self, unused_main_window):
        """Cleanup before destroying this window."""
        pm = self.app.project_manager
        pm.disconnect_by_func(self._project_manager_new_project_loaded_cb)
        pm.disconnect_by_func(self._project_manager_save_project_failed_cb)
        pm.disconnect_by_func(self._project_manager_project_saved_cb)
        pm.disconnect_by_func(self._project_manager_closing_project_cb)
        pm.disconnect_by_func(self._project_manager_reverting_to_saved_cb)
        pm.disconnect_by_func(self._project_manager_project_closed_cb)
        pm.disconnect_by_func(self._project_manager_missing_uri_cb)
        self.toplevel_widget.remove(self.timeline_ui)
        self.timeline_ui.destroy()

    def _render_cb(self, unused_button):
        """Shows the dialog for exporting the video, as in the mockup."""
        from pitivi.export import ExportDialog

        project = self.app.project_manager.current_project
        dialog = ExportDialog(self.app, project)
        dialog.show()

    def _create_ui(self):
        """Creates the graphical interface.

        The rough hierarchy is:
        vpaned:
        - mainhpaned(files_panel, center_box(propshpaned(viewer, props_panel), props_rail))
        - timeline_ui

        The full hierarchy can be admired by starting the GTK+ Inspector
        with Ctrl+Shift+I.
        """
        # pylint: disable=attribute-defined-outside-init
        # Main "toolbar" (using client-side window decorations with HeaderBar)
        self.headerbar = self.__create_headerbar()

        # Set up our main containers, in the order documented above

        # Separates the panels+viewer from the timeline
        self.toplevel_widget = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        # Separates the files panel from the viewer and the properties
        self.mainhpaned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        # Separates the viewer from the properties panel
        self.propshpaned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        for paned in (self.toplevel_widget, self.mainhpaned, self.propshpaned):
            paned.get_style_context().add_class("spl-paned")
        self.toplevel_widget.pack1(self.mainhpaned, resize=True, shrink=False)
        self.toplevel_widget.show()
        self.mainhpaned.show()
        self.propshpaned.show()

        # Files panel, always visible on the left
        self.main_tabs = BaseTabs(self.app, detachable=False)
        self.medialibrary = MediaLibraryWidget(self.app)
        self.main_tabs.append_page("Media Library",
                                   self.medialibrary, Gtk.Label(label=_("Media Library")))
        # The panel header already says what it contains.
        self.main_tabs.set_show_tabs(False)
        self.medialibrary.connect('play', self._media_library_play_cb)
        self.medialibrary.show()
        self.main_tabs.show()

        self.add_text_button = Gtk.Button.new_from_icon_name(
            "insert-text-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        self.add_text_button.set_always_show_image(True)
        self.add_text_button.set_label(_("Add text"))
        self.add_text_button.set_tooltip_text(
            _("Create a title clip and edit it in Properties"))
        self.add_text_button.set_sensitive(False)
        self.add_text_button.connect("clicked", self.__add_text_cb)
        self.files_panel = self.__create_side_panel(
            _("Files"), "view-grid-symbolic", self.add_text_button, self.main_tabs)
        self.mainhpaned.pack1(self.files_panel, resize=False, shrink=False)

        # Properties panel on the right, which can be collapsed
        # The pages keep their numbers: 0 for the clip settings, 1 for the
        # transition, which is shown only when a transition is selected,
        # and 2 for the effects.
        self.context_tabs = BaseTabs(self.app, detachable=False)
        # Created first, because the effect expander of the clip properties
        # uses it to list the effects.
        self.effectlist = EffectListWidget(self.app)
        self.clipconfig = ClipProperties(self.app, show_effects=False)
        self.trans_list = TransitionPropertiesWidget(self.app)
        self.effects_page = self.__create_effects_page()
        self.context_tabs.append_page("Clip",
                                      self.clipconfig, Gtk.Label(label=_("Settings")))
        self.context_tabs.append_page("Transition",
                                      self.trans_list, Gtk.Label(label=_("Transition")))
        self.context_tabs.append_page("Effects",
                                      self.effects_page, Gtk.Label(label=_("Effects")))
        self.trans_list.hide()
        self.context_tabs.set_current_page(0)
        self.context_tabs.show()

        collapse_button = Gtk.Button.new_from_icon_name(
            "go-next-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        collapse_button.set_always_show_image(True)
        collapse_button.set_image_position(Gtk.PositionType.RIGHT)
        collapse_button.set_label(_("Collapse"))
        collapse_button.set_relief(Gtk.ReliefStyle.NONE)
        collapse_button.set_tooltip_text(
            _("Hide the properties panel to make the viewer bigger"))
        collapse_button.connect("clicked", self.__collapse_properties_cb)
        props_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        props_content.pack_start(self.clipconfig.summary, False, False, 0)
        props_content.pack_start(self.context_tabs, True, True, 0)
        props_content.show()
        self.props_panel = self.__create_side_panel(
            _("Properties"), "document-properties-symbolic", collapse_button,
            props_content)
        self.props_rail = self.__create_properties_rail()

        # Viewer, docked in the center
        self.viewer = ViewerContainer(self.app, undockable=False)
        self.viewer.get_style_context().add_class("spl-viewer")
        self.propshpaned.pack1(self.viewer, resize=True, shrink=False)
        self.propshpaned.pack2(self.props_panel, resize=False, shrink=False)

        center_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        center_box.pack_start(self.propshpaned, True, True, 0)
        center_box.pack_start(self.props_rail, False, False, 0)
        center_box.show()
        self.mainhpaned.pack2(center_box, resize=True, shrink=False)

        # Now, the lower part: the timeline, using the full width
        self.timelinepaned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.timelinepaned.get_style_context().add_class("spl-timeline")

        self.timeline_ui = TimelineContainer(self.app, self.editor_state)
        self.timeline_ui.get_style_context().add_class("spl-timeline")
        self.mini_timeline_ui = self.timeline_ui.timeline.mini_layout_container

        self.timelinepaned.pack1(self.mini_timeline_ui, resize=False, shrink=False)
        self.timelinepaned.pack2(self.timeline_ui, resize=False, shrink=False)
        self.timelinepaned.show_all()

        self.toplevel_widget.pack2(self.timelinepaned, resize=False, shrink=False)

        self.intro = InteractiveIntro(self.app)
        self.headerbar.pack_end(self.intro.intro_button)

        # Setup shortcuts for HeaderBar buttons and menu items.
        self._create_actions()

        # Identify widgets for AT-SPI, making our test suite easier to develop
        # These will show up in sniff, accerciser, etc.
        self.headerbar.get_accessible().set_name("editor_headerbar")
        self.menu_button.get_accessible().set_name("main menu button")
        self.toplevel_widget.get_accessible().set_name("contents")
        self.mainhpaned.get_accessible().set_name("upper half")
        self.files_panel.get_accessible().set_name("files panel")
        self.props_panel.get_accessible().set_name("properties panel")
        self.main_tabs.get_accessible().set_name("primary tabs")
        self.context_tabs.get_accessible().set_name("secondary tabs")
        self.viewer.get_accessible().set_name("viewer")
        self.timeline_ui.get_accessible().set_name("timeline area")

        # Restore the collapsed state. The sizes are applied once the window
        # has its real size, and again whenever it changes, so that the
        # viewer is the one which grows or shrinks.
        self.props_panel.set_visible(not self.settings.propertiesPanelCollapsed)
        self.props_rail.set_visible(self.settings.propertiesPanelCollapsed)
        self.__panel_sizes = None
        self.__allocated_size = None
        self.__applying_sizes = False
        # The visibility of the widgets hidden while the viewer is fullscreen.
        self.__fullscreen_hidden = None
        self.toplevel_widget.connect("size-allocate", self.__toplevel_size_allocate_cb)
        self.__propshpaned_width = None
        self.propshpaned.connect("size-allocate", self.__propshpaned_size_allocate_cb)
        for paned in (self.toplevel_widget, self.mainhpaned, self.propshpaned):
            paned.connect("notify::position", self.__paned_position_changed_cb)

    def toggle_viewer_fullscreen(self):
        """Shows only the viewer and its controls in fullscreen, or everything back."""
        fullscreen = self.__fullscreen_hidden is None
        if fullscreen:
            widgets = (self.files_panel, self.props_panel, self.props_rail, self.timelinepaned)
            self.__fullscreen_hidden = {widget: widget.get_visible() for widget in widgets}
            for widget in widgets:
                widget.hide()
            self.app.gui.connect("key-press-event", self.__fullscreen_key_press_cb)
            self.app.gui.fullscreen()
        else:
            for widget, visible in self.__fullscreen_hidden.items():
                widget.set_visible(visible)
            self.__fullscreen_hidden = None
            self.app.gui.disconnect_by_func(self.__fullscreen_key_press_cb)
            self.app.gui.unfullscreen()
        self.viewer.set_fullscreen_state(fullscreen)

    def __fullscreen_key_press_cb(self, unused_window, event):
        if event.keyval == Gdk.KEY_Escape:
            self.toggle_viewer_fullscreen()
            return True
        return False

    def __create_side_panel(self, title, icon_name, action_widget, content):
        """Creates an integrated panel with a header and the specified content."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACING)
        header.get_style_context().add_class("spl-panel-header")
        header.props.margin_start = SPACING
        header.props.margin_end = SPACING
        image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
        header.pack_start(image, False, False, 0)
        label = Gtk.Label(label=title)
        label.set_xalign(0)
        label.get_style_context().add_class("spl-panel-title")
        header.pack_start(label, True, True, 0)
        action_widget.props.valign = Gtk.Align.CENTER
        header.pack_end(action_widget, False, False, 0)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.get_style_context().add_class("spl-panel")
        panel.pack_start(header, False, False, 0)
        panel.pack_start(content, True, True, 0)
        # The content manages the visibility of its own children.
        header.show_all()
        panel.show()
        return panel

    def __create_effects_page(self):
        """Creates the page with the effects of the clip and the effect catalog."""
        effect_expander = self.clipconfig.effect_expander
        effect_expander.set_label(_("Applied effects"))
        effect_expander.set_expanded(True)
        # The catalog below replaces the "Add Effect" popover.
        effect_expander.add_effect_button.set_no_show_all(True)
        effect_expander.add_effect_button.hide()
        effect_expander.placeholder_label.set_text(
            _("This clip has no effects. Choose one from the catalog."))

        catalog_label = Gtk.Label()
        catalog_label.set_markup("<b>%s</b>" % GLib.markup_escape_text(_("Effect catalog")))
        catalog_label.set_xalign(0)
        catalog_label.get_style_context().add_class("spl-section-title")
        catalog_label.props.margin_start = SPACING
        catalog_label.props.margin_top = SPACING
        separator = Gtk.Separator()

        # As in the mockup, a few simple effects which work with any video,
        # instead of the long catalog of GStreamer, where some crash the app.
        self.effects_catalog = SimpleEffectsCatalog(self.app)
        self.effects_catalog.props.margin = SPACING
        self.effects_catalog.props.margin_top = 0
        effect_expander.connect("effects-changed",
                                lambda expander: self.effects_catalog.update(expander.clip))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PADDING)
        box.pack_start(effect_expander, False, False, 0)
        box.pack_start(separator, False, False, 0)
        box.pack_start(catalog_label, False, False, 0)
        box.pack_start(self.effects_catalog, False, False, 0)

        # The settings of the applied effects can be taller than the panel.
        page = Gtk.ScrolledWindow()
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page.add(box)
        # The visibility of the effect expander depends on the selection.
        for widget in (separator, catalog_label, box, page.get_child(), page):
            widget.show()
        return page

    def __create_properties_rail(self):
        """Creates the thin bar shown instead of the collapsed properties panel."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        image = Gtk.Image.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.MENU)
        box.pack_start(image, False, False, 0)
        label = Gtk.Label(label=_("Properties"))
        label.set_angle(90)
        box.pack_start(label, False, False, 0)

        rail = Gtk.Button()
        rail.add(box)
        rail.set_relief(Gtk.ReliefStyle.NONE)
        rail.set_valign(Gtk.Align.FILL)
        rail.get_style_context().add_class("spl-rail")
        rail.set_tooltip_text(_("Show properties"))
        rail.connect("clicked", self.__expand_properties_cb)
        rail.show_all()
        rail.set_no_show_all(True)
        rail.get_accessible().set_name("show properties")
        return rail

    def __toplevel_size_allocate_cb(self, widget, allocation):
        size = (allocation.width, allocation.height)
        if size == self.__allocated_size or allocation.width < 400:
            return
        self.__allocated_size = size
        # Changing positions during an allocation is not reliable.
        self.__applying_sizes = True
        GLib.idle_add(self.__apply_panel_sizes)

    def __apply_panel_sizes(self):
        width = self.toplevel_widget.get_allocated_width()
        height = self.toplevel_widget.get_allocated_height()
        if self.__panel_sizes is None:
            # Sizes chosen by the user. The missing ones follow the window
            # size, approximating the approved mockup.
            self.__panel_sizes = {
                "files": self.settings.filesPanelWidth,
                "properties": self.settings.propertiesPanelWidth,
                "timeline": self.settings.timelinePanelHeight,
            }
        sizes = self.__panel_sizes
        files_width = sizes["files"] or int(min(max(width * 0.22, 290), 360))
        files_width = max(files_width, self.files_panel.get_preferred_width()[0])
        timeline_height = sizes["timeline"] or int(min(max(height * 0.38, 260), 420))

        self.__applying_sizes = True
        self.toplevel_widget.set_position(
            height - self.__handle_size(self.toplevel_widget) - timeline_height)
        self.mainhpaned.set_position(files_width)
        self.__applying_sizes = False
        # The properties width is applied once the viewer and the properties
        # have their new size, see __propshpaned_size_allocate_cb.
        self.__apply_properties_width()
        return False

    def __propshpaned_size_allocate_cb(self, widget, allocation):
        if allocation.width == self.__propshpaned_width:
            return
        self.__propshpaned_width = allocation.width
        GLib.idle_add(self.__apply_properties_width)

    def __apply_properties_width(self):
        if not self.props_panel.get_visible() or self.__panel_sizes is None:
            return False
        width = self.propshpaned.get_allocated_width()
        props_width = self.__panel_sizes["properties"] or int(
            min(max(self.toplevel_widget.get_allocated_width() * 0.24, 320), 380))
        self.__applying_sizes = True
        self.propshpaned.set_position(width - self.__handle_size(self.propshpaned) - props_width)
        self.__applying_sizes = False
        return False

    @staticmethod
    def __handle_size(paned):
        """Returns the actual size of the handle of the specified paned."""
        child1 = paned.get_child1()
        child2 = paned.get_child2()
        if paned.get_orientation() == Gtk.Orientation.HORIZONTAL:
            size = paned.get_allocated_width() - child1.get_allocated_width() - child2.get_allocated_width()
        else:
            size = paned.get_allocated_height() - child1.get_allocated_height() - child2.get_allocated_height()
        if not child1.get_visible() or not child2.get_visible() or size <= 0:
            # Not measurable now.
            return paned.style_get_property("handle-size")
        return size

    def __paned_position_changed_cb(self, paned, unused_pspec):
        """Remembers the sizes chosen by the user by dragging the handles."""
        if self.__applying_sizes or self.__panel_sizes is None:
            return
        # GTK also moves the handles when allocating the panels, which
        # should not be taken as the user's choice.
        event = Gtk.get_current_event()
        if not event or event.type != Gdk.EventType.MOTION_NOTIFY:
            return
        handle = self.__handle_size(paned)
        if paned is self.mainhpaned:
            self.__panel_sizes["files"] = paned.get_position()
        elif paned is self.propshpaned:
            if self.props_panel.get_visible():
                self.__panel_sizes["properties"] = (
                    paned.get_allocated_width() - paned.get_position() - handle)
        else:
            self.__panel_sizes["timeline"] = (
                paned.get_allocated_height() - paned.get_position() - handle)

    def save_layout(self):
        """Saves the sizes of the panels in the settings."""
        if self.__panel_sizes:
            # Only the sizes chosen by the user, the others follow the window.
            self.settings.filesPanelWidth = self.__panel_sizes["files"]
            self.settings.propertiesPanelWidth = self.__panel_sizes["properties"]
            self.settings.timelinePanelHeight = self.__panel_sizes["timeline"]
        self.settings.propertiesPanelCollapsed = not self.props_panel.get_visible()

    def collapse_properties(self):
        """Hides the properties panel, leaving a thin bar to show it again."""
        if not self.props_panel.get_visible():
            return
        self.settings.propertiesPanelCollapsed = True
        self.props_panel.hide()
        self.props_rail.show()

    def expand_properties(self):
        """Shows the properties panel with its previous width."""
        self.settings.propertiesPanelCollapsed = False
        if self.props_panel.get_visible():
            return
        self.props_rail.hide()
        self.props_panel.show()
        self.__applying_sizes = True
        GLib.idle_add(self.__apply_panel_sizes)

    def __collapse_properties_cb(self, unused_button):
        self.collapse_properties()

    def __expand_properties_cb(self, unused_button):
        self.expand_properties()

    def __add_text_cb(self, unused_button):
        self.expand_properties()
        self.context_tabs.set_current_page(0)
        self.clipconfig.create_title_clip_cb(None)

    def switch_context_tab(self, ges_clip):
        """Activates the appropriate tab on the second set of tabs.

        Args:
            ges_clip (GES.SourceClip): The clip which has been focused.
        """
        if isinstance(ges_clip, GES.TransitionClip):
            self.trans_list.show()
            self.context_tabs.set_current_page(1)
            for child in ges_clip.get_children(False):
                if isinstance(child, GES.VideoTransition):
                    self.trans_list.activate(child)
                    break
        elif isinstance(ges_clip, (GES.TitleClip, GES.SourceClip, GES.TestClip)):
            # Stay on the effects page if it's the current one.
            if self.context_tabs.get_current_page() == 1:
                self.context_tabs.set_current_page(0)
            self.trans_list.hide()
        else:
            self.warning("Unknown clip type: %s", ges_clip)

    def focus_timeline(self):
        layers_representation = self.timeline_ui.timeline.layout
        # Check whether it has focus already, grab_focus always emits an event.
        if not layers_representation.props.is_focus:
            layers_representation.grab_focus()

    def __home_clicked_cb(self, unused_button):
        self.app.project_manager.close_running_project()

    def __create_headerbar(self):
        headerbar = Gtk.HeaderBar()
        headerbar.set_show_close_button(True)
        headerbar.get_style_context().add_class("spl-headerbar")
        headerbar.set_custom_title(self.__create_title())

        undo_button = Gtk.Button.new_from_icon_name(
            "edit-undo-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        undo_button.set_always_show_image(True)
        undo_button.set_label(_("Undo"))
        undo_button.set_action_name("app.undo")
        undo_button.set_use_underline(True)

        redo_button = Gtk.Button.new_from_icon_name(
            "edit-redo-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        redo_button.set_always_show_image(True)
        redo_button.set_action_name("app.redo")
        redo_button.set_use_underline(True)

        # pylint: disable=attribute-defined-outside-init
        self.save_button = Gtk.Button.new_with_label(_("Save"))
        self.save_button.set_focus_on_click(False)

        self.render_button = Gtk.Button.new_from_icon_name(
            "document-send-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        self.render_button.set_always_show_image(True)
        self.render_button.set_label(_("Export video"))
        self.render_button.get_style_context().add_class("spl-accent")
        self.render_button.get_style_context().add_class("spl-accent-main")
        self.render_button.set_tooltip_text(
            _("Export your project as a finished movie"))
        self.render_button.set_sensitive(False)  # The only one we have to set.
        self.render_button.connect("clicked", self._render_cb)

        # Closes the project, asking to save the changes, and shows the
        # start screen.
        home_button = Gtk.Button.new_from_icon_name("go-home-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        home_button.set_tooltip_text(_("Go to the start screen"))
        home_button.connect("clicked", self.__home_clicked_cb)
        headerbar.pack_start(home_button)

        undo_redo_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        undo_redo_box.get_style_context().add_class("linked")
        undo_redo_box.pack_start(undo_button, expand=False, fill=False, padding=0)
        undo_redo_box.pack_start(redo_button, expand=False, fill=False, padding=0)
        headerbar.pack_start(undo_redo_box)

        self.builder.add_from_file(
            os.path.join(get_ui_dir(), "mainmenubutton.ui"))

        self.menu_button = self.builder.get_object("menubutton")
        self.keyboard_shortcuts_button = self.builder.get_object("menu_shortcuts")
        # SPL: the format is chosen in the viewer and the frame rate follows
        # the clips, the other settings and the manual are for professionals.
        for name in ("menu_revert_to_saved", "menu_export_tarball", "menu_sep3",
                     "menu_project_settings", "menu_preferences", "menu_help",
                     "menu_interactive_intro"):
            item = self.builder.get_object(name)
            item.hide()
            item.set_no_show_all(True)

        headerbar.pack_end(self.menu_button)
        headerbar.pack_end(self.save_button)
        headerbar.pack_end(self.render_button)
        headerbar.show_all()

        return headerbar

    def __create_title(self):
        """Creates the title with the logo, as in the mockup."""
        logo = Gtk.DrawingArea()
        logo.set_size_request(30, 30)
        logo.props.valign = Gtk.Align.CENTER
        logo.connect("draw", self.__draw_logo_cb)

        # pylint: disable=attribute-defined-outside-init
        self.project_name_label = Gtk.Label()
        self.project_name_label.get_style_context().add_class("spl-project-name")
        self.project_name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.build_label = Gtk.Label()
        self.build_label.get_style_context().add_class("dim-label")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACING * 2)
        box.pack_start(logo, False, False, 0)
        box.pack_start(self.project_name_label, False, False, 0)
        box.pack_start(self.build_label, False, False, 0)
        box.show_all()
        return box

    @staticmethod
    def __draw_logo_cb(widget, cr):
        """Draws an accent rounded square with a play symbol."""
        size = min(widget.get_allocated_width(), widget.get_allocated_height())
        radius = size * 0.3
        cr.new_sub_path()
        cr.arc(size - radius, radius, radius, -math.pi / 2, 0)
        cr.arc(size - radius, size - radius, radius, 0, math.pi / 2)
        cr.arc(radius, size - radius, radius, math.pi / 2, math.pi)
        cr.arc(radius, radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()
        gradient = cairo.LinearGradient(0, 0, size, size)
        gradient.add_color_stop_rgb(0, 1, 0.616, 0.424)
        gradient.add_color_stop_rgb(1, 0.941, 0.376, 0.239)
        cr.set_source(gradient)
        cr.fill()

        # The play symbol, centered, slightly to the right as it looks better.
        scale = size / 24
        cr.move_to(9.5 * scale, 7 * scale)
        cr.line_to(17.5 * scale, 12 * scale)
        cr.line_to(9.5 * scale, 17 * scale)
        cr.close_path()
        cr.set_source_rgb(1, 1, 1)
        cr.fill()
        return False

    def _create_actions(self):
        group = Gio.SimpleActionGroup()
        self.toplevel_widget.insert_action_group("editor", group)
        self.headerbar.insert_action_group("editor", group)

        # pylint: disable=attribute-defined-outside-init
        self.save_action = Gio.SimpleAction.new("save", None)
        self.save_action.connect("activate", self.__save_project_cb)
        group.add_action(self.save_action)
        self.app.shortcuts.add("editor.save", ["<Primary>s"], self.save_action,
                               _("Save the current project"), group="win")
        self.save_button.set_action_name("editor.save")

        self.save_as_action = Gio.SimpleAction.new("save-as", None)
        self.save_as_action.connect("activate", self.__save_project_as_cb)
        group.add_action(self.save_as_action)
        self.app.shortcuts.add("editor.save-as", ["<Primary><Shift>s"],
                               self.save_as_action,
                               _("Save the current project as"), group="win")

        self.revert_to_saved_action = Gio.SimpleAction.new("revert-to-saved", None)
        self.revert_to_saved_action.connect("activate", self.__revert_to_saved_cb)
        group.add_action(self.revert_to_saved_action)

        self.export_project_action = Gio.SimpleAction.new("export-project", None)
        self.export_project_action.connect("activate", self.__export_project_cb)
        group.add_action(self.export_project_action)

        self.save_frame_action = Gio.SimpleAction.new("save-frame", None)
        self.save_frame_action.connect("activate", self.__save_frame_cb)
        group.add_action(self.save_frame_action)

        self.project_settings_action = Gio.SimpleAction.new("project-settings", None)
        self.project_settings_action.connect("activate", self.__project_settings_cb)
        group.add_action(self.project_settings_action)

        self.viewer_fullscreen_action = Gio.SimpleAction.new("toggle-viewer-fullscreen", None)
        self.viewer_fullscreen_action.connect("activate", lambda *unused: self.toggle_viewer_fullscreen())
        group.add_action(self.viewer_fullscreen_action)
        self.app.shortcuts.add("editor.toggle-viewer-fullscreen", ["F11"],
                               self.viewer_fullscreen_action,
                               _("See the video in fullscreen"), group="win")

        group.add_action(self.intro.intro_action)
        self.app.shortcuts.add("editor.interactive-intro", [], self.intro.intro_action,
                               _("Quick intros to Pitivi"), group="win")

        self.import_asset_action = Gio.SimpleAction.new("import-asset", None)
        self.import_asset_action.connect("activate", self.__import_asset_cb)
        group.add_action(self.import_asset_action)
        self.app.shortcuts.add("editor.import-asset", ["<Primary>i"],
                               self.import_asset_action,
                               _("Add media files to your project"), group="win")

    def __import_asset_cb(self, unused_action, unused_param):
        self.medialibrary.show_import_assets_dialog()

    def show_project_status(self):
        project = self.app.project_manager.current_project
        dirty = project.has_unsaved_modifications()
        self.save_action.set_enabled(dirty)
        self.revert_to_saved_action.set_enabled(bool(project.uri) and dirty)
        self.update_title()

# UI Callbacks

    def _media_library_play_cb(self, unused_medialibrary, asset):
        """Previews the specified asset.

        If the media library item to preview is an image, show it in the user's
        favorite image viewer. Else, preview the video/sound in Pitivi.
        """
        # Technically, our preview widget can show images, but it's never going
        # to do a better job (sizing, zooming, metadata, editing, etc.)
        # than the user's favorite image viewer.
        if asset.is_image():
            Gio.AppInfo.launch_default_for_uri(asset.get_id(), None)
        else:
            preview_window = PreviewAssetWindow(asset, self.app)
            preview_window.preview()

    def _project_changed_cb(self, unused_project):
        self.save_action.set_enabled(True)
        self.update_title()

# Toolbar/Menu actions callback

    def __save_project_cb(self, unused_action, unused_param):
        self.save_project()

    def __save_project_as_cb(self, unused_action, unused_param):
        self.save_project_as()

    def save_project(self):
        if not self.app.project_manager.current_project.uri or self.app.project_manager.disable_save:
            self.save_project_as()
        else:
            self.app.project_manager.save_project()

    def __revert_to_saved_cb(self, unused_action, unused_param):
        self.app.project_manager.revert_to_saved_project()

    def __export_project_cb(self, unused_action, unused_param):
        uri = self._show_export_dialog(self.app.project_manager.current_project)
        result = None
        if uri:
            result = self.app.project_manager.export_project(
                self.app.project_manager.current_project, uri)

        if not result:
            self.log("Project couldn't be exported")
        return result

    def __project_settings_cb(self, unused_action, unused_param):
        self.show_project_settings_dialog()

    def show_project_settings_dialog(self):
        project = self.app.project_manager.current_project
        dialog = ProjectSettingsDialog(self.app.gui, project, self.app)
        dialog.window.run()
        self.update_title()

# Project management callbacks

    def _project_manager_new_project_loaded_cb(self, project_manager, project):
        """Connects the UI to the specified project.

        Args:
            project_manager (ProjectManager): The project manager.
            project (Project): The project which has been loaded.
        """
        self.log("A new project has been loaded")

        self._connect_to_project(project)
        project.pipeline.activate_position_listener()

        self.viewer.set_project(project)
        self.clipconfig.set_project(project, self.timeline_ui)
        self.add_text_button.set_sensitive(True)
        self.timeline_ui.set_project(project)

        # When creating a blank project there's no project URI yet.
        if project.uri:
            folder_path = os.path.dirname(path_from_uri(project.uri))
            self.settings.lastProjectFolder = folder_path

        self.update_title()

        if project_manager.disable_save is True:
            # Special case: we enforce "Save as", but the normal "Save" button
            # redirects to it if needed, so we still want it to be enabled:
            self.save_action.set_enabled(True)

        if project.ges_timeline.props.duration != 0:
            self.render_button.set_sensitive(True)

    def _project_manager_save_project_failed_cb(self, unused_project_manager, uri, exception=None):
        project_filename = unquote(uri.split("/")[-1])
        dialog = Gtk.MessageDialog(transient_for=self.app.gui,
                                   modal=True,
                                   message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.OK,
                                   text=_('Unable to save project "%s"') % project_filename)
        if exception:
            dialog.set_property("secondary-use-markup", True)
            dialog.set_property("secondary-text", unquote(str(exception)))
        dialog.set_transient_for(self.app.gui)
        dialog.run()
        dialog.destroy()
        self.error("failed to save project")

    def _project_manager_project_saved_cb(self, unused_project_manager, unused_project, unused_uri):
        self.update_title()
        self.save_action.set_enabled(False)

    def _project_manager_closing_project_cb(self, project_manager, project):
        """Investigates whether it's possible to close the specified project.

        Args:
            project_manager (ProjectManager): The project manager.
            project (Project): The project which has been closed.

        Returns:
            bool: True when it's OK to close it, False when the user chooses
                to cancel the closing operation.
        """
        if not project.has_unsaved_modifications():
            return True

        if project.uri and not project_manager.disable_save:
            save = _("Save")
        else:
            save = _("Save as...")

        dialog = Gtk.MessageDialog(transient_for=self.app.gui, modal=True)
        reject_btn = dialog.add_button(_("Close without saving"),
                                       Gtk.ResponseType.REJECT)

        dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL,
                           save, Gtk.ResponseType.YES)

        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        dialog.get_accessible().set_name("unsaved changes dialog")
        reject_btn.get_style_context().add_class("destructive-action")

        primary = _("Save changes to the current project before closing?")
        dialog.props.use_markup = True
        dialog.props.text = "<span weight=\"bold\">" + primary + "</span>"

        if project.uri:
            path = unquote(project.uri).split("file://")[1]
            last_saved = max(
                os.path.getmtime(path), project_manager.time_loaded)
            time_delta = time() - last_saved
            message = _("If you don't save, "
                        "the changes from the last %s will be lost.") % \
                beautify_time_delta(time_delta)
        else:
            message = _("If you don't save, your changes will be lost.")

        dialog.props.secondary_text = message

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            if project.uri is not None and project_manager.disable_save is False:
                res = self.app.project_manager.save_project()
            else:
                res = self.save_project_as()
        elif response == Gtk.ResponseType.REJECT:
            res = True
        else:
            res = False

        return res

    def _project_manager_project_closed_cb(self, project_manager, project):
        """Starts disconnecting the UI from the specified project.

        This happens when the user closes the app or asks to load another
        project, immediately after the user confirmed that unsaved changes,
        if any, can be discarded but before the filechooser to pick the next
        project to load appears.
        """
        # We must disconnect from the project pipeline before it is released:
        if project.pipeline is not None:
            project.pipeline.deactivate_position_listener()

        self.info("Project closed")
        self.add_text_button.set_sensitive(False)
        if project.loaded:
            self._disconnect_from_project(project)

        self.timeline_ui.set_project(None)
        self.clipconfig.set_project(None, None)

        self.render_button.set_sensitive(False)
        return False

    def _project_manager_reverting_to_saved_cb(self, unused_project_manager, unused_project):
        if self.app.project_manager.current_project.has_unsaved_modifications():
            dialog = Gtk.MessageDialog(transient_for=self.app.gui,
                                       modal=True,
                                       message_type=Gtk.MessageType.WARNING,
                                       buttons=Gtk.ButtonsType.NONE,
                                       text=_("Revert to saved project version?"))
            dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.NO,
                               Gtk.STOCK_REVERT_TO_SAVED, Gtk.ResponseType.YES)
            dialog.set_resizable(False)
            dialog.set_property("secondary-text",
                                _("This will reload the current project. All unsaved changes will be lost."))
            dialog.set_default_response(Gtk.ResponseType.NO)
            dialog.set_transient_for(self.app.gui)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.YES:
                return False
        return True

    def _project_manager_missing_uri_cb(self, project_manager, project, unused_error, asset):
        if project.at_least_one_asset_missing:
            # One asset is already missing so no point in spamming the user
            # with more file-missing dialogs, as we need all of them.
            return None

        if self.app.proxy_manager.is_proxy_asset(asset):
            uri = self.app.proxy_manager.get_target_uri(asset)
        else:
            uri = asset.get_id()

        dialog = MissingAssetDialog(self.app, asset, uri)
        new_uri = dialog.get_new_uri()

        if not new_uri:
            dialog.hide()
            if not self.app.proxy_manager.check_proxy_loading_succeeded(asset):
                # Reset the project manager and disconnect all the signals.
                project_manager.close_running_project()
                # Signal the project loading failure.
                # You have to do this *after* successfully creating a blank project,
                # or the startupwizard will still be connected to that signal too.
                reason = _("No replacement file was provided for \"<i>%s</i>\".\n\n"
                           "Pitivi does not currently support partial projects.") % \
                    info_name(asset)
                project_manager.emit("new-project-failed", project.uri, reason)

        dialog.destroy()
        return new_uri

    def _connect_to_project(self, project):
        project.connect("project-changed", self._project_changed_cb)
        project.ges_timeline.connect("notify::duration",
                                     self._timeline_duration_changed_cb)

    def _disconnect_from_project(self, project):
        project.disconnect_by_func(self._project_changed_cb)
        project.ges_timeline.disconnect_by_func(self._timeline_duration_changed_cb)

    def _timeline_duration_changed_cb(self, timeline, unused_duration):
        """Updates the render button.

        This covers the case when a clip is inserted into a blank timeline.
        This callback is not triggered by loading a project.
        """
        duration = timeline.get_duration()
        self.debug("Timeline duration changed to %s", duration)
        self.render_button.set_sensitive(duration > 0)

    def _show_export_dialog(self, project):
        self.log("Export requested")
        chooser = Gtk.FileChooserDialog(title=_("Export To..."),
                                        transient_for=self.app.gui,
                                        action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL,
                            _("Save"), Gtk.ResponseType.OK)
        chooser.set_default_response(Gtk.ResponseType.OK)

        chooser.set_select_multiple(False)
        chooser.props.do_overwrite_confirmation = True

        asset = GES.Formatter.get_default()
        asset_extension = asset.get_meta(GES.META_FORMATTER_EXTENSION)

        chooser.set_current_name(
            project.name + "." + asset_extension + "_tar")

        filt = Gtk.FileFilter()
        filt.set_name(_("Tar archive"))
        filt.add_pattern("*.%s_tar" % asset_extension)
        chooser.add_filter(filt)
        default = Gtk.FileFilter()
        default.set_name(_("Detect automatically"))
        default.add_pattern("*")
        chooser.add_filter(default)

        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            self.log("User chose a URI to export project to")
            # need to do this to work around bug in Gst.uri_construct
            # which escapes all /'s in path!
            uri = "file://" + chooser.get_filename()
            self.log("uri: %s", uri)
            ret = uri
        else:
            self.log("User didn't choose a URI to export project to")
            ret = None

        chooser.destroy()
        return ret

    def save_project_as(self):
        uri = self._show_save_as_dialog()
        if uri is None:
            return False
        return self.app.project_manager.save_project(uri)

    def _show_save_as_dialog(self):
        self.log("Save URI requested")
        chooser = Gtk.FileChooserDialog(title=_("Save As..."),
                                        transient_for=self.app.gui,
                                        action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL,
                            _("Save"), Gtk.ResponseType.OK)
        chooser.set_default_response(Gtk.ResponseType.OK)
        asset = GES.Formatter.get_default()
        filt = Gtk.FileFilter()
        filt.set_name(asset.get_meta(GES.META_DESCRIPTION))
        filt.add_pattern("*.%s" % asset.get_meta(GES.META_FORMATTER_EXTENSION))
        chooser.add_filter(filt)

        chooser.set_select_multiple(False)
        chooser.set_current_name(_("Untitled") + "." +
                                 asset.get_meta(GES.META_FORMATTER_EXTENSION))
        chooser.set_current_folder(self.settings.lastProjectFolder)
        chooser.props.do_overwrite_confirmation = True

        default = Gtk.FileFilter()
        default.set_name(_("Detect automatically"))
        default.add_pattern("*")
        chooser.add_filter(default)

        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            self.log("User chose a URI to save project to")
            # need to do this to work around bug in Gst.uri_construct
            # which escapes all /'s in path!
            uri = "file://" + chooser.get_filename()
            file_filter = chooser.get_filter().get_name()
            self.log("uri:%s , filter:%s", uri, file_filter)
            self.settings.lastProjectFolder = chooser.get_current_folder()
            ret = uri
        else:
            self.log("User didn't choose a URI to save project to")
            ret = None

        chooser.destroy()
        return ret

    def __save_frame_cb(self, unused_action, unused_param):
        """Exports a snapshot of the current frame as an image file."""
        res = self._show_save_screenshot_dialog()
        if res:
            path, mime = res[0], res[1]
            self.app.project_manager.current_project.pipeline.save_thumbnail(
                -1, -1, mime, path)

    def _show_save_screenshot_dialog(self):
        """Asks the user where to save the current frame.

        Returns:
            List[str]: The full path and the mimetype if successful, None otherwise.
        """
        chooser = Gtk.FileChooserDialog(title=_("Save As..."),
                                        transient_for=self.app.gui, action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL,
                            _("Save"), Gtk.ResponseType.OK)
        chooser.set_default_response(Gtk.ResponseType.OK)
        chooser.set_select_multiple(False)
        chooser.set_current_name(_("Untitled"))
        chooser.props.do_overwrite_confirmation = True
        formats = {_("PNG image"): ["image/png", ("png",)],
                   _("JPEG image"): ["image/jpeg", ("jpg", "jpeg")]}
        for image_format in formats:
            filt = Gtk.FileFilter()
            filt.set_name(image_format)
            filt.add_mime_type(formats.get(image_format)[0])
            chooser.add_filter(filt)
        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            chosen_format = formats.get(chooser.get_filter().get_name())
            chosen_ext = chosen_format[1][0]
            chosen_mime = chosen_format[0]
            uri = os.path.join(
                chooser.get_current_folder(), chooser.get_filename())
            ret = ["%s.%s" % (uri, chosen_ext), chosen_mime]
        else:
            ret = None
        chooser.destroy()
        return ret

    def update_title(self):
        project = self.app.project_manager.current_project
        unsaved_mark = ""
        if project.has_unsaved_modifications():
            unsaved_mark = "*"
        title = "%s%s — %s" % (unsaved_mark, project.name, APPNAME)
        self.headerbar.set_title(with_build_label(title))
        self.project_name_label.set_text("%s%s" % (unsaved_mark, project.name))
        # The development build, to tell which code is running.
        self.build_label.set_text(with_build_label("").lstrip(" —"))


class PreviewAssetWindow(Gtk.Window):
    """Window for previewing a video or audio asset.

    Args:
        asset (GES.UriClipAsset): The asset to be previewed.
        app (Pitivi): The app.
    """

    def __init__(self, asset, app):
        Gtk.Window.__init__(self)
        self._asset = asset
        self.app = app

        self.set_title(_("Preview"))
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_transient_for(app.gui)

        self._previewer = PreviewWidget(app.settings, minimal=True)
        self.add(self._previewer)
        self._previewer.preview_uri(self._asset.get_id())
        self._previewer.show()

        self.connect("key-press-event", self._key_press_event_cb)

    def preview(self):
        """Shows the window and starts the playback."""
        width, height = self._calculate_preview_window_size()
        self.resize(width, height)
        # Setting the position of the window only works if it's currently hidden
        # otherwise, after the resize the position will not be readjusted
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.show()

        self._previewer.play()
        # Hack so that we really really force the "utility" window to be
        # focused
        self.present()

    def _calculate_preview_window_size(self):
        info = self._asset.get_info()
        video_streams = info.get_video_streams()
        if not video_streams:
            # There is no video/image stream. This is an audio file.
            # Resize to the minimum and let the window manager deal with it.
            return 1, 1
        # For videos and images, automatically resize the window
        # Try to keep it 1:1 if it can fit within 85% of the parent window
        video = video_streams[0]
        img_width = video.get_natural_width()
        img_height = video.get_natural_height()
        mainwindow_width, mainwindow_height = self.app.gui.get_size()
        max_width = 0.85 * mainwindow_width
        max_height = 0.85 * mainwindow_height

        controls_height = self._previewer.bbox.get_preferred_size()[0].height
        if img_width < max_width and (img_height + controls_height) < max_height:
            # The video is small enough, keep it 1:1
            return img_width, img_height + controls_height
        else:
            # The video is too big, size it down
            # TODO: be smarter, figure out which (width, height) is bigger
            new_height = max_width * img_height / img_width
            return int(max_width), int(new_height + controls_height)

    def _key_press_event_cb(self, unused_widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
        return True
