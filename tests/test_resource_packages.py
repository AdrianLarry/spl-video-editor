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
"""Tests for resource packages (stickers, audio, fonts) and timeline integration."""
import os
from unittest import mock

from gi.repository import GES
from gi.repository import Gst

from pitivi.clip_properties.summary import describe_clip
from pitivi.utils.resource_packages import get_sticker_name
from pitivi.utils.resource_packages import is_sticker_clip
from pitivi.utils.resource_packages import PackageManager
from tests import common


class ResourcePackagesTest(common.TestCase):
    """Tests for discovering and loading resource packages."""

    def setUp(self):
        super().setUp()
        self.pm = PackageManager()
        self.pm.load_packages()

    def test_bundled_package_loaded(self):
        packages = self.pm.get_packages()
        self.assertGreater(len(packages), 0)
        comercial = self.pm.packages.get("comercial")
        self.assertIsNotNone(comercial)
        self.assertEqual(comercial.license, "CC0")

    def test_stickers_discovery_and_pixbuf(self):
        stickers = self.pm.get_stickers()
        self.assertGreaterEqual(len(stickers), 6)
        expected_ids = {"sticker_oferta", "sticker_nuevo", "sticker_descuento",
                        "sticker_precio", "sticker_destacado", "sticker_envio_gratis"}
        found_ids = {s.id for s in stickers}
        self.assertTrue(expected_ids.issubset(found_ids))

        for sticker in stickers:
            self.assertTrue(os.path.exists(sticker.file_path))
            self.assertTrue(sticker.uri.startswith("file://"))
            pixbuf = sticker.get_pixbuf(size=64)
            self.assertIsNotNone(pixbuf, f"Failed rendering pixbuf for {sticker.name}")
            self.assertGreater(pixbuf.get_width(), 0)
            self.assertGreater(pixbuf.get_height(), 0)

    def test_audio_discovery_and_assets(self):
        audio_items = self.pm.get_audio()
        self.assertGreaterEqual(len(audio_items), 2)
        found_ids = {a.id for a in audio_items}
        self.assertIn("audio_loop_comercial", found_ids)
        self.assertIn("audio_chime_exito", found_ids)

        for item in audio_items:
            self.assertTrue(os.path.exists(item.file_path))
            asset = GES.UriClipAsset.request_sync(item.uri)
            self.assertIsNotNone(asset, f"Failed creating GES asset for {item.name}")
            self.assertGreater(asset.get_duration(), 0)


class TimelineStickersTest(common.TestCase):
    """Tests for adding stickers and audio from packages to the timeline."""

    @common.setup_timeline
    @common.setup_clipproperties
    def test_create_sticker_clip(self):
        pm = PackageManager()
        pm.load_packages()
        sticker = pm.get_item("sticker_oferta")
        self.assertIsNotNone(sticker)

        self.project.pipeline.get_position = mock.Mock(return_value=0)
        self.clipproperties.create_sticker_clip(sticker)

        clips = self.layer.get_clips()
        self.assertEqual(len(clips), 1)
        clip = clips[0]
        self.assertTrue(is_sticker_clip(clip))
        self.assertEqual(get_sticker_name(clip), sticker.name)

        # Check summary
        kind, name, icon = describe_clip(clip)
        self.assertEqual(kind, "Sticker")
        self.assertEqual(name, sticker.name)
        self.assertEqual(icon, "emblem-favorite-symbolic")

        # Source positioning and scale
        source = clip.find_track_element(None, GES.VideoUriSource)
        self.assertIsNotNone(source)
        w = source.get_child_property("width")[1]
        h = source.get_child_property("height")[1]
        self.assertGreater(w, 50)
        self.assertGreater(h, 50)

        # Test Undo and Redo
        self.action_log.undo()
        self.assertEqual(len(self.layer.get_clips()), 0)
        self.action_log.redo()
        self.assertEqual(len(self.layer.get_clips()), 1)
        self.assertTrue(is_sticker_clip(self.layer.get_clips()[0]))

    @common.setup_timeline
    @common.setup_clipproperties
    def test_create_audio_clip(self):
        pm = PackageManager()
        pm.load_packages()
        audio = pm.get_item("audio_loop_comercial")
        self.assertIsNotNone(audio)

        self.project.pipeline.get_position = mock.Mock(return_value=0)
        self.clipproperties.create_audio_clip(audio)

        all_clips = [c for layer in self.project.ges_timeline.get_layers() for c in layer.get_clips()]
        self.assertEqual(len(all_clips), 1)
        clip = all_clips[0]
        self.assertTrue(clip.props.supported_formats & GES.TrackType.AUDIO)
        self.assertGreater(clip.props.duration, 0)

        # Test Undo and Redo
        self.action_log.undo()
        all_clips = [c for layer in self.project.ges_timeline.get_layers() for c in layer.get_clips()]
        self.assertEqual(len(all_clips), 0)
        self.action_log.redo()
        all_clips = [c for layer in self.project.ges_timeline.get_layers() for c in layer.get_clips()]
        self.assertEqual(len(all_clips), 1)

    def test_resources_menu_button_ui(self):
        from pitivi.clip_properties.stickers_ui import ResourcesMenuButton
        from gi.repository import Gtk

        pm = PackageManager()
        pm.load_packages()

        sticker_called = []
        audio_called = []

        def on_sticker(item):
            sticker_called.append(item)

        def on_audio(item):
            audio_called.append(item)

        btn = ResourcesMenuButton(on_sticker, pm, on_audio)
        self.assertIsNotNone(btn.popover)

        # Trigger popover show callback to build tabs
        btn._ResourcesMenuButton__popover_show_cb(btn.popover)

        main_box = btn.popover.get_child()
        self.assertIsInstance(main_box, Gtk.Box)

        # Test audio page and insert callback
        audio_item = pm.get_item("audio_loop_comercial")
        btn._ResourcesMenuButton__insert_audio_clicked_cb(None, audio_item)
        self.assertEqual(len(audio_called), 1)
        self.assertEqual(audio_called[0].id, "audio_loop_comercial")

        # Test sticker clicked callback
        sticker_item = pm.get_item("sticker_oferta")
        btn._ResourcesMenuButton__sticker_clicked_cb(None, sticker_item)
        self.assertEqual(len(sticker_called), 1)
        self.assertEqual(sticker_called[0].id, "sticker_oferta")

        # Test popover hide stops preview
        btn._ResourcesMenuButton__popover_hide_cb(btn.popover)

