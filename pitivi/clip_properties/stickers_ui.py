# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2026, AdrianLarry <familystyle@outlook.es>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser Commercial General Public
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
"""UI for choosing and adding resources (stickers, audio, fonts) from resource packages."""
from gettext import gettext as _
from typing import Callable
from typing import Optional

from gi.repository import GdkPixbuf
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gst
from gi.repository import Gtk

from pitivi.configure import get_packages_dir
from pitivi.configure import get_user_packages_dir
from pitivi.utils.resource_packages import PackageManager
from pitivi.utils.resource_packages import ResourceItem
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING


class ResourcesMenuButton(Gtk.MenuButton):
    """Button offering stickers, audio, and content from resource packages."""

    def __init__(self, add_sticker_cb: Callable[[ResourceItem], None],
                 package_manager: PackageManager,
                 add_audio_cb: Optional[Callable[[ResourceItem], None]] = None):
        Gtk.MenuButton.__init__(self)
        self.add_sticker_cb = add_sticker_cb
        self.add_audio_cb = add_audio_cb
        self.package_manager = package_manager

        # Audio preview player
        self._player = None
        self._playing_item_id = None
        self._playing_btn = None

        box = Gtk.Box(spacing=PADDING)
        icon = Gtk.Image.new_from_icon_name("emblem-favorite-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        box.pack_start(icon, False, False, 0)
        box.pack_start(Gtk.Label(label=_("Resources")), False, False, 0)
        box.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU),
                       False, False, 0)
        self.add(box)
        self.set_tooltip_text(_("Add promotional stickers, background music, or sound effects from packages"))

        popover = Gtk.Popover()
        popover.connect("show", self.__popover_show_cb)
        popover.connect("hide", self.__popover_hide_cb)
        self.popover = popover
        self.set_popover(popover)
        box.show_all()

    def _get_player(self):
        if self._player is None:
            self._player = Gst.ElementFactory.make("playbin", "resource_preview_player")
            if self._player:
                bus = self._player.get_bus()
                bus.add_signal_watch()
                bus.connect("message::eos", self.__bus_eos_cb)
                bus.connect("message::error", self.__bus_error_cb)
        return self._player

    def _stop_preview(self):
        if self._player:
            self._player.set_state(Gst.State.NULL)
        if self._playing_btn:
            icon = Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
            self._playing_btn.set_image(icon)
        self._playing_item_id = None
        self._playing_btn = None

    def __bus_eos_cb(self, bus, msg):
        self._stop_preview()

    def __bus_error_cb(self, bus, msg):
        self._stop_preview()

    def __popover_hide_cb(self, popover):
        self._stop_preview()

    def __popover_show_cb(self, popover):
        self._stop_preview()
        old_child = popover.get_child()
        if old_child:
            popover.remove(old_child)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        main_box.props.margin = PADDING
        main_box.props.margin_top = PADDING // 2

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_transition_duration(150)

        # 1. Stickers Page
        stickers_widget = self._create_stickers_page()
        stack.add_titled(stickers_widget, "stickers", _("Stickers"))

        # 2. Audio Page
        audio_widget = self._create_audio_page()
        stack.add_titled(audio_widget, "audio", _("Audio"))

        # 3. Packages Page
        packages_widget = self._create_packages_page()
        stack.add_titled(packages_widget, "packages", _("Packages"))

        switcher = Gtk.StackSwitcher()
        switcher.set_stack(stack)
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.props.margin_bottom = PADDING // 2

        main_box.pack_start(switcher, False, False, 0)
        main_box.pack_start(stack, True, True, 0)

        popover.add(main_box)
        main_box.show_all()

    def _create_stickers_page(self) -> Gtk.Widget:
        stickers = self.package_manager.get_stickers()
        if not stickers:
            lbl = Gtk.Label(label=_("No stickers available in packages"))
            lbl.props.margin = PADDING * 2
            return lbl

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(min(320, 95 * ((len(stickers) + 1) // 2)))
        scroll.set_min_content_width(300)

        grid = Gtk.Grid()
        grid.set_column_spacing(PADDING)
        grid.set_row_spacing(PADDING)
        grid.set_column_homogeneous(True)

        for idx, item in enumerate(stickers):
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NORMAL)
            item_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            item_box.props.margin = 4

            pixbuf = item.get_pixbuf(size=56)
            if pixbuf:
                img = Gtk.Image.new_from_pixbuf(pixbuf)
            else:
                img = Gtk.Image.new_from_icon_name("image-x-generic-symbolic", Gtk.IconSize.DND)
            item_box.pack_start(img, True, True, 0)

            lbl = Gtk.Label(label=item.name)
            lbl.set_line_wrap(True)
            lbl.set_max_width_chars(12)
            lbl.get_style_context().add_class("caption")
            item_box.pack_start(lbl, False, False, 0)

            btn.add(item_box)
            btn.set_tooltip_text(f"{item.name} ({item.license})")
            btn.connect("clicked", self.__sticker_clicked_cb, item)

            col = idx % 2
            row = idx // 2
            grid.attach(btn, col, row, 1, 1)

        scroll.add(grid)
        return scroll

    def _create_audio_page(self) -> Gtk.Widget:
        audio_items = self.package_manager.get_audio()
        if not audio_items:
            lbl = Gtk.Label(label=_("No audio tracks available in packages"))
            lbl.props.margin = PADDING * 2
            return lbl

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(240)
        scroll.set_min_content_width(300)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)

        for item in audio_items:
            row = Gtk.ListBoxRow()
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=PADDING)
            row_box.props.margin = 6

            # Play / Stop button
            play_btn = Gtk.Button()
            play_btn.set_relief(Gtk.ReliefStyle.NONE)
            play_icon = Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
            play_btn.set_image(play_icon)
            play_btn.set_tooltip_text(_("Listen preview"))
            play_btn.connect("clicked", self.__play_audio_clicked_cb, item)
            row_box.pack_start(play_btn, False, False, 0)

            # Details
            info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            name_lbl = Gtk.Label(label=item.name, xalign=0)
            name_lbl.set_markup(f"<b>{GLib.markup_escape_text(item.name)}</b>")
            info_box.pack_start(name_lbl, False, False, 0)

            desc = item.description or item.category or _("Royalty-free audio")
            desc_lbl = Gtk.Label(label=desc, xalign=0)
            desc_lbl.get_style_context().add_class("dim-label")
            desc_lbl.set_line_wrap(True)
            desc_lbl.set_max_width_chars(26)
            info_box.pack_start(desc_lbl, False, False, 0)
            row_box.pack_start(info_box, True, True, 0)

            # Insert button
            add_btn = Gtk.Button()
            add_btn.set_relief(Gtk.ReliefStyle.NORMAL)
            add_icon = Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
            add_btn.set_image(add_icon)
            add_btn.set_tooltip_text(_("Add audio track to timeline"))
            add_btn.connect("clicked", self.__insert_audio_clicked_cb, item)
            row_box.pack_start(add_btn, False, False, 0)

            row.add(row_box)
            list_box.add(row)

        scroll.add(list_box)
        return scroll

    def _create_packages_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PADDING)
        box.props.margin = PADDING
        box.set_size_request(300, -1)

        packages = self.package_manager.get_packages()
        for pkg in packages:
            pkg_frame = Gtk.Frame()
            pkg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            pkg_box.props.margin = PADDING

            title_lbl = Gtk.Label(xalign=0)
            title_lbl.set_markup(f"<b>{GLib.markup_escape_text(pkg.name)}</b> v{pkg.version}")
            pkg_box.pack_start(title_lbl, False, False, 0)

            author_str = f"Autor: {pkg.author} | Licencia: {pkg.license}"
            author_lbl = Gtk.Label(label=author_str, xalign=0)
            author_lbl.get_style_context().add_class("dim-label")
            pkg_box.pack_start(author_lbl, False, False, 0)

            if pkg.description:
                desc_lbl = Gtk.Label(label=pkg.description, xalign=0)
                desc_lbl.set_line_wrap(True)
                desc_lbl.set_max_width_chars(32)
                pkg_box.pack_start(desc_lbl, False, False, 0)

            count_str = f"{len(pkg.get_items('sticker'))} stickers, {len(pkg.get_items('audio'))} pistas de audio"
            count_lbl = Gtk.Label(label=count_str, xalign=0)
            count_lbl.get_style_context().add_class("caption")
            pkg_box.pack_start(count_lbl, False, False, 0)

            pkg_frame.add(pkg_box)
            box.pack_start(pkg_frame, False, False, 0)

        # Folder button
        folder_btn = Gtk.Button()
        btn_box = Gtk.Box(spacing=PADDING)
        btn_box.pack_start(Gtk.Image.new_from_icon_name("folder-open-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        btn_box.pack_start(Gtk.Label(label=_("Open packages folder")), False, False, 0)
        folder_btn.add(btn_box)
        folder_btn.set_tooltip_text(_("Open ~/.local/share/pitivi/packages to add or manage packages"))
        folder_btn.connect("clicked", self.__open_packages_folder_cb)
        box.pack_start(folder_btn, False, False, PADDING)

        return box

    def __open_packages_folder_cb(self, unused_btn):
        user_pkg_dir = get_user_packages_dir()
        try:
            Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(user_pkg_dir), None)
        except Exception:
            pass

    def __play_audio_clicked_cb(self, button, item: ResourceItem):
        if self._playing_item_id == item.id:
            # Stop playback
            self._stop_preview()
        else:
            # Switch or start playback
            self._stop_preview()
            player = self._get_player()
            if player:
                player.props.uri = item.uri
                player.set_state(Gst.State.PLAYING)
                self._playing_item_id = item.id
                self._playing_btn = button
                icon = Gtk.Image.new_from_icon_name("media-playback-stop-symbolic", Gtk.IconSize.BUTTON)
                button.set_image(icon)

    def __insert_audio_clicked_cb(self, unused_btn, item: ResourceItem):
        self._stop_preview()
        self.popover.popdown()
        if self.add_audio_cb:
            self.add_audio_cb(item)

    def __sticker_clicked_cb(self, unused_button, item: ResourceItem):
        self._stop_preview()
        self.popover.popdown()
        self.add_sticker_cb(item)


# Backwards compatibility alias
StickerMenuButton = ResourcesMenuButton
