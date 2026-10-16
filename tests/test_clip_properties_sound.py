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
"""Tests for the pitivi.clip_properties.sound module."""
# pylint: disable=protected-access
from gi.repository import GES
from gi.repository import Gst

from pitivi.clip_properties.sound import Envelope
from pitivi.clip_properties.sound import envelope_keyframes
from pitivi.clip_properties.sound import read_envelope
from tests import common

SECOND = Gst.SECOND


class EnvelopeTest(common.TestCase):
    """Tests for converting envelopes to and from keyframes."""

    def test_round_trip(self):
        """Checks the keyframes of an envelope describe the same envelope."""
        for envelope in (Envelope(1.0, 0, 0),
                         Envelope(0.5, 2 * SECOND, 0),
                         Envelope(2.0, 0, 3 * SECOND),
                         Envelope(1.5, SECOND, SECOND),
                         Envelope(0.0, 0, 0)):
            keyframes = envelope_keyframes(envelope, 10 * SECOND, 20 * SECOND)
            read = read_envelope(keyframes)
            self.assertIsNotNone(read, envelope)
            self.assertAlmostEqual(read.volume, envelope.volume)
            self.assertEqual((read.fade_in, read.fade_out),
                             (envelope.fade_in, envelope.fade_out))

    def test_keyframes(self):
        """Checks the keyframes of an envelope with fades."""
        keyframes = envelope_keyframes(Envelope(1.0, 2 * SECOND, 3 * SECOND), 0, 10 * SECOND)
        self.assertEqual(keyframes, [(0, 0.0),
                                     (2 * SECOND, 0.1),
                                     (7 * SECOND, 0.1),
                                     (10 * SECOND, 0.0)])

    def test_fades_longer_than_the_clip(self):
        """Checks the fades are limited to the duration of the clip."""
        keyframes = envelope_keyframes(Envelope(1.0, 8 * SECOND, 8 * SECOND), 0, 10 * SECOND)
        self.assertEqual(keyframes, [(0, 0.0), (8 * SECOND, 0.1), (10 * SECOND, 0.0)])

    def test_curves_edited_freely(self):
        """Checks curves which are not envelopes are not taken as such."""
        for keyframes in ([],
                          [(0, 0.1)],
                          [(0, 0.1), (5 * SECOND, 0.2), (10 * SECOND, 0.1)],
                          [(0, 0.0), (5 * SECOND, 0.1), (6 * SECOND, 0.0), (10 * SECOND, 0.1)]):
            self.assertIsNone(read_envelope(keyframes), keyframes)

    def test_trimmed_clip(self):
        """Checks the envelope is found when the ends are not at the clip ends."""
        keyframes = envelope_keyframes(Envelope(1.0, SECOND, 2 * SECOND), 0, 10 * SECOND)
        # The clip was trimmed from 10 to 8 seconds, the keyframes stay.
        self.assertEqual(read_envelope(keyframes), Envelope(1.0, SECOND, 2 * SECOND))


class SoundPropertiesTest(common.TestCase):
    """Tests for the SoundProperties widget."""

    def _select_clip(self):
        clip = self.add_clips_simple(self.timeline_container.timeline, 1)[0]
        # Long enough for the fades.
        clip.set_duration(SECOND)
        self.timeline_container.timeline.selection.select([clip])
        sound = self.clipproperties.sound_expander
        self.assertTrue(sound.get_visible())
        self.assertIsInstance(sound.source, GES.AudioSource)
        return sound

    def _get_keyframes(self, sound):
        binding = sound.source.get_control_binding("volume")
        return [(keyframe.timestamp, keyframe.value)
                for keyframe in binding.props.control_source.get_all()]

    @common.setup_timeline
    @common.setup_clipproperties
    def test_volume_and_fades(self):
        """Checks changing the volume and the fades, and undoing it."""
        sound = self._select_clip()
        initial_keyframes = self._get_keyframes(sound)
        self.assertEqual(sound.get_envelope(), Envelope(1.0, 0, 0))

        sound.volume_scale.set_value(50)
        self.assertAlmostEqual(sound.get_envelope().volume, 0.5)
        sound.fade_in_spin.set_value(0.5)
        self.assertEqual(sound.get_envelope().fade_in, SECOND // 2)
        self.assertEqual(self._get_keyframes(sound)[0][1], 0.0)

        # The volume and the fades are undone separately.
        self.action_log.undo()
        self.assertEqual(sound.get_envelope().fade_in, 0)
        self.assertAlmostEqual(sound.get_envelope().volume, 0.5)
        self.assertEqual(sound.fade_in_spin.get_value(), 0)
        self.action_log.undo()
        self.assertEqual(self._get_keyframes(sound), initial_keyframes)
        self.assertEqual(sound.volume_scale.get_value(), 100)

        self.action_log.redo()
        self.assertAlmostEqual(sound.get_envelope().volume, 0.5)

    @common.setup_timeline
    @common.setup_clipproperties
    def test_curve_edited_on_the_timeline(self):
        """Checks a curve edited freely is not changed by the widget."""
        sound = self._select_clip()
        start, end = sound._get_range()
        sound._control_source.set((start + end) // 2, 0.3)
        self.assertIsNone(sound.get_envelope())
        self.assertTrue(sound.custom_box.get_visible())
        self.assertFalse(sound.volume_scale.get_sensitive())

        sound.custom_box.get_children()[1].clicked()
        self.assertEqual(sound.get_envelope(), Envelope(3.0, 0, 0))
        self.assertFalse(sound.custom_box.get_visible())

    @common.setup_timeline
    @common.setup_clipproperties
    def test_mute(self):
        """Checks muting and undoing it."""
        sound = self._select_clip()
        sound.mute_button.set_active(True)
        self.assertTrue(sound.source.get_child_property("mute")[1])

        self.action_log.undo()
        self.assertFalse(sound.source.get_child_property("mute")[1])
        self.assertFalse(sound.mute_button.get_active())
