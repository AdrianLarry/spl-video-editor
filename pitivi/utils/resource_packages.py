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
"""Management of reusable resource packages (stickers, audio, fonts).

Packages are folders containing a manifest.json file detailing author,
license (CC0, CC-BY, OFL), and the items bundled. This allows designers
and musicians to contribute content without writing code.
"""
import json
import os
from typing import Dict
from typing import List
from typing import Optional

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf
from gi.repository import Gst

from pitivi.configure import get_packages_dir
from pitivi.configure import get_user_packages_dir
from pitivi.utils.loggable import Loggable


class ResourceItem:
    """An individual resource bundled in a package (sticker, audio, font)."""

    def __init__(self,
                 item_id: str,
                 name: str,
                 item_type: str,
                 category: str,
                 file_path: str,
                 author: str = "",
                 license_name: str = "CC0",
                 description: str = "",
                 package_id: str = "",
                 preview_path: Optional[str] = None):
        self.id = item_id
        self.name = name
        self.type = item_type
        self.category = category
        self.file_path = file_path
        self.author = author
        self.license = license_name
        self.description = description
        self.package_id = package_id
        self.preview_path = preview_path or file_path

    @property
    def uri(self) -> str:
        """Returns the GStreamer URI of the resource file."""
        return Gst.filename_to_uri(os.path.abspath(self.file_path))

    def get_pixbuf(self, size: int = 48) -> Optional[GdkPixbuf.Pixbuf]:
        """Loads and returns a square Pixbuf preview of the resource."""
        path = self.preview_path if os.path.exists(self.preview_path) else self.file_path
        if not os.path.exists(path):
            return None
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
        except Exception:
            return None

    def __repr__(self) -> str:
        return f"<ResourceItem {self.id} ({self.type}): {self.name}>"


class ResourcePackage:
    """A collection of resources described by a manifest.json file."""

    def __init__(self,
                 package_id: str,
                 name: str,
                 version: str = "1.0",
                 author: str = "",
                 license_name: str = "CC0",
                 description: str = "",
                 path: str = ""):
        self.id = package_id
        self.name = name
        self.version = version
        self.author = author
        self.license = license_name
        self.description = description
        self.path = path
        self.items: List[ResourceItem] = []

    def get_items(self, item_type: Optional[str] = None, category: Optional[str] = None) -> List[ResourceItem]:
        """Filters package items by type and/or category."""
        return [
            item for item in self.items
            if (item_type is None or item.type == item_type) and
               (category is None or item.category == category)
        ]

    def __repr__(self) -> str:
        return f"<ResourcePackage {self.id} v{self.version} ({len(self.items)} items)>"


class PackageManager(Loggable):
    """Discovers, loads, and indexes resource packages."""

    def __init__(self):
        Loggable.__init__(self)
        self.packages: Dict[str, ResourcePackage] = {}
        self.items_by_id: Dict[str, ResourceItem] = {}

    def load_packages(self, extra_dirs: Optional[List[str]] = None) -> None:
        """Scans system and user directories for packages."""
        self.packages.clear()
        self.items_by_id.clear()

        search_dirs = [get_packages_dir(), get_user_packages_dir()]
        if extra_dirs:
            search_dirs.extend(extra_dirs)

        for directory in search_dirs:
            if not os.path.isdir(directory):
                continue
            for entry in os.listdir(directory):
                pkg_path = os.path.join(directory, entry)
                if os.path.isdir(pkg_path):
                    self._load_package(pkg_path)

        self.info("Loaded %d resource packages with %d total items",
                  len(self.packages), len(self.items_by_id))

    def _load_package(self, package_dir: str) -> Optional[ResourcePackage]:
        manifest_path = os.path.join(package_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.warning("Failed to parse manifest at %s: %s", manifest_path, e)
            return None

        pkg_id = data.get("id") or os.path.basename(package_dir)
        package = ResourcePackage(
            package_id=pkg_id,
            name=data.get("name", pkg_id),
            version=str(data.get("version", "1.0")),
            author=data.get("author", ""),
            license_name=data.get("license", "CC0"),
            description=data.get("description", ""),
            path=package_dir
        )

        for item_data in data.get("items", []):
            item_file = item_data.get("file", "")
            full_file_path = os.path.normpath(os.path.join(package_dir, item_file))
            if not os.path.exists(full_file_path):
                self.debug("Resource item file missing: %s", full_file_path)
                continue

            preview_file = item_data.get("preview", "")
            full_preview_path = (os.path.normpath(os.path.join(package_dir, preview_file))
                                 if preview_file else None)

            item = ResourceItem(
                item_id=item_data.get("id", os.path.splitext(os.path.basename(item_file))[0]),
                name=item_data.get("name", item_data.get("id", "")),
                item_type=item_data.get("type", "sticker"),
                category=item_data.get("category", "general"),
                file_path=full_file_path,
                author=item_data.get("author", package.author),
                license_name=item_data.get("license", package.license),
                description=item_data.get("description", ""),
                package_id=pkg_id,
                preview_path=full_preview_path
            )
            package.items.append(item)
            self.items_by_id[item.id] = item

        self.packages[pkg_id] = package
        return package

    def get_packages(self) -> List[ResourcePackage]:
        """Returns the list of loaded packages."""
        return list(self.packages.values())

    def get_items(self, item_type: Optional[str] = None, category: Optional[str] = None) -> List[ResourceItem]:
        """Returns all items matching the optional type and/or category."""
        return [
            item for item in self.items_by_id.values()
            if (item_type is None or item.type == item_type) and
               (category is None or item.category == category)
        ]

    def get_stickers(self, category: Optional[str] = None) -> List[ResourceItem]:
        """Returns all sticker items."""
        return self.get_items(item_type="sticker", category=category)

    def get_audio(self, category: Optional[str] = None) -> List[ResourceItem]:
        """Returns all audio items."""
        return self.get_items(item_type="audio", category=category)

    def get_fonts(self) -> List[ResourceItem]:
        """Returns all font items."""
        return self.get_items(item_type="font")

    def get_item(self, item_id: str) -> Optional[ResourceItem]:
        """Finds a specific resource item by its ID."""
        return self.items_by_id.get(item_id)


STICKER_META = "spl::sticker"


def is_sticker_clip(clip) -> bool:
    """Whether the clip is a sticker overlay."""
    return clip is not None and bool(clip.get_string(STICKER_META))


def get_sticker_name(clip) -> str:
    """Returns the name of the sticker."""
    return clip.get_string(STICKER_META) or ""

