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
"""Tests for the pitivi.configure module."""
import os
import tempfile

from pitivi.configure import user_dir
from tests import common


class UserDirTest(common.TestCase):
    """Tests for the folders of the user."""

    def test_old_folder_renamed(self):
        with tempfile.TemporaryDirectory() as parent:
            old = os.path.join(parent, "pitivi")
            os.makedirs(old)
            with open(os.path.join(old, "pitivi.conf"), "w", encoding="utf-8") as conf:
                conf.write("[user-interface]\n")
            path = user_dir(parent)
            self.assertEqual(path, os.path.join(parent, "vitrina"))
            self.assertTrue(os.path.exists(os.path.join(path, "pitivi.conf")))
            self.assertFalse(os.path.exists(old))

    def test_new_folder_kept(self):
        with tempfile.TemporaryDirectory() as parent:
            os.makedirs(os.path.join(parent, "pitivi"))
            os.makedirs(os.path.join(parent, "vitrina"))
            self.assertEqual(user_dir(parent), os.path.join(parent, "vitrina"))
            # The old one is left alone, nothing is mixed.
            self.assertTrue(os.path.exists(os.path.join(parent, "pitivi")))

    def test_no_folder(self):
        with tempfile.TemporaryDirectory() as parent:
            self.assertEqual(user_dir(parent), os.path.join(parent, "vitrina"))
