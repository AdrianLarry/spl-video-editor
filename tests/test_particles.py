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
"""Tests for procedural particle effects and splparticles element."""
import cairo
import numpy as np
from gi.repository import GES
from gi.repository import Gst

from pitivi.utils.particles import draw_snow
from pitivi.utils.particles import render_particles
from pitivi.utils.particlesfilter import ELEMENT_NAME
from pitivi.utils.particlesfilter import register as register_particles
from tests import common


class ParticlesTest(common.TestCase):
    """Tests for procedural particle generation and GStreamer filter."""

    def setUp(self):
        super().setUp()
        register_particles()

    def test_effects_rendering_deterministic(self):
        """Checks that all particle effects are deterministic at same t and move at different t."""
        w, h = 320, 240
        stride = w * 4

        for effect_name in ("snow", "confetti", "sparkles", "smoke"):
            # Frame at t = 1.0
            data1 = bytearray(stride * h)
            surf1 = cairo.ImageSurface.create_for_data(data1, cairo.FORMAT_ARGB32, w, h, stride)
            cr1 = cairo.Context(surf1)
            render_particles(cr1, effect_name, 1.0, w, h)
            surf1.flush()

            # Another frame at t = 1.0
            data2 = bytearray(stride * h)
            surf2 = cairo.ImageSurface.create_for_data(data2, cairo.FORMAT_ARGB32, w, h, stride)
            cr2 = cairo.Context(surf2)
            render_particles(cr2, effect_name, 1.0, w, h)
            surf2.flush()

            # Frame at t = 2.0
            data3 = bytearray(stride * h)
            surf3 = cairo.ImageSurface.create_for_data(data3, cairo.FORMAT_ARGB32, w, h, stride)
            cr3 = cairo.Context(surf3)
            render_particles(cr3, effect_name, 2.0, w, h)
            surf3.flush()

            # Identical at same time
            self.assertEqual(bytes(data1), bytes(data2), f"Effect {effect_name} not deterministic")
            # Non-empty (particles were drawn)
            self.assertTrue(any(data1), f"Effect {effect_name} drew nothing")
            # Different at different times (particles moved)
            self.assertNotEqual(bytes(data1), bytes(data3), f"Effect {effect_name} did not move")

    def test_element_factory_and_properties(self):
        """Checks that splparticles element is registered and properties work."""
        elem = Gst.ElementFactory.make(ELEMENT_NAME, None)
        self.assertIsNotNone(elem)
        
        self.assertEqual(elem.get_property("effect"), "snow")
        self.assertAlmostEqual(elem.get_property("amount"), 1.0)
        self.assertAlmostEqual(elem.get_property("speed"), 1.0)
        self.assertAlmostEqual(elem.get_property("size"), 1.0)
        self.assertAlmostEqual(elem.get_property("opacity"), 0.85)

        elem.set_property("amount", 2.5)
        elem.set_property("speed", 1.5)
        elem.set_property("size", 0.8)
        elem.set_property("opacity", 0.5)

        self.assertAlmostEqual(elem.get_property("amount"), 2.5)
        self.assertAlmostEqual(elem.get_property("speed"), 1.5)
        self.assertAlmostEqual(elem.get_property("size"), 0.8)
        self.assertAlmostEqual(elem.get_property("opacity"), 0.5)

    def test_pipeline_execution(self):
        """Checks that splparticles processes buffers in a real GStreamer pipeline for all effects."""
        for effect_name in ("snow", "confetti", "sparkles", "smoke"):
            pipe_str = (
                f"videotestsrc num-buffers=5 ! "
                f"video/x-raw,format=BGRA,width=320,height=240,framerate=30/1 ! "
                f"splparticles effect={effect_name} ! fakesink"
            )
            pipeline = Gst.parse_launch(pipe_str)
            bus = pipeline.get_bus()
            pipeline.set_state(Gst.State.PLAYING)
            msg = bus.timed_pop_filtered(5 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
            pipeline.set_state(Gst.State.NULL)
            self.assertIsNotNone(msg, f"Effect {effect_name} pipeline produced no message")
            self.assertEqual(msg.type, Gst.MessageType.EOS, f"Effect {effect_name} pipeline failed")

    @common.setup_timeline
    def test_ges_effect_addition(self):
        """Checks adding splparticles as a GES.Effect onto a timeline clip."""
        self._wait_until_project_loaded()
        timeline = self.project.ges_timeline
        layer = timeline.append_layer()
        clip = GES.TestClip.new()
        clip.set_duration(3 * Gst.SECOND)
        layer.add_clip(clip)

        bin_desc = "videoconvert ! video/x-raw,format=BGRA ! splparticles effect=snow ! videoconvert"
        effect = GES.Effect.new(bin_desc)
        self.assertIsNotNone(effect)
        self.assertTrue(clip.add_top_effect(effect, 0))
        timeline.commit()

    @common.setup_timeline
    def test_particle_overlay_layer(self):
        """Checks creating a transparent particle overlay clip on a timeline layer."""
        self._wait_until_project_loaded()
        from pitivi.clip_properties.particles import (
            create_particle_clip, setup_particle_overlay, is_particle_clip,
            get_particle_effect, get_particle_effect_name, draw_particle_thumbnail
        )
        from pitivi.clip_properties.opacity import get_opacity_effect

        timeline = self.project.ges_timeline
        layer = timeline.append_layer()
        clip = create_particle_clip(5 * Gst.SECOND)
        layer.add_clip(clip)

        effect = setup_particle_overlay(clip, "snow", (1280, 720))
        self.assertIsNotNone(effect)
        self.assertTrue(is_particle_clip(clip))
        self.assertEqual(get_particle_effect_name(clip), "snow")
        self.assertIs(get_particle_effect(clip), effect)

        # Check transparent background
        source = clip.find_track_element(None, GES.VideoTestSource)
        self.assertEqual(source.get_child_property("foreground-color")[1], 0)

        # Check opacity integration
        opacity_effect = get_opacity_effect(clip)
        self.assertIs(opacity_effect, effect)
        effect.set_child_property("alpha", 0.6)
        self.assertAlmostEqual(effect.get_child_property("alpha")[1], 0.6)

        # Check thumbnail generation for all effects
        for effect_name in ("snow", "confetti", "sparkles", "smoke"):
            clip.set_string("spl-particles", effect_name)
            thumb = draw_particle_thumbnail(clip, 60)
            self.assertIsNotNone(thumb)
            self.assertEqual(thumb.get_width(), 60)
            self.assertEqual(thumb.get_height(), 60)

