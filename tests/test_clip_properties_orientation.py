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
"""Tests for the pitivi.clip_properties.orientation module."""
from pitivi.clip_properties.orientation import METHODS
from pitivi.clip_properties.orientation import Orientation
from tests import common


class OrientationTest(common.TestCase):
    """Tests for the Orientation class."""

    def test_turns(self):
        identity = Orientation()
        orientations = [identity]
        for unused in range(4):
            orientations.append(orientations[-1].rotated(90))
        # Four different orientations, back to the start.
        self.assertEqual(len(set(orientations[:4])), 4)
        self.assertEqual(orientations[4], identity)
        self.assertEqual(identity.rotated(-90), identity.rotated(270))

        self.assertEqual(identity.mirrored_horizontally().mirrored_horizontally(), identity)
        self.assertEqual(identity.mirrored_vertically().mirrored_vertically(), identity)
        # Mirroring both ways is the same as rotating by 180 degrees.
        self.assertEqual(identity.mirrored_horizontally().mirrored_vertically(), identity.rotated(180))

        # Mirroring is relative to what is seen, not to the original image.
        rotated = identity.rotated(90)
        self.assertEqual(rotated.mirrored_horizontally(), Orientation(270, True))
        self.assertEqual(rotated.mirrored_vertically(), Orientation(90, True))

    def test_methods(self):
        """Checks each orientation has its own videoflip method."""
        orientations = {Orientation(rotation, mirrored)
                        for rotation in (0, 90, 180, 270)
                        for mirrored in (False, True)}
        self.assertEqual(set(METHODS), orientations)
        self.assertEqual(sorted(METHODS.values()), list(range(8)))
        self.assertEqual(METHODS[Orientation()], 0)
