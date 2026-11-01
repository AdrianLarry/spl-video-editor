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
"""Procedural particle rendering for generated SPL visual effects."""
import math
from typing import Callable
from typing import Dict

import cairo


def _hash_float(i: int, seed: int = 42) -> float:
    """Returns a deterministic pseudo-random float in [0.0, 1.0) for index i."""
    x = math.sin(i * 12.9898 + seed * 78.233) * 43758.5453
    return x - math.floor(x)


_SMOKE_SPRITE = None
_SNOW_SPRITE = None


def _get_smoke_sprite() -> cairo.ImageSurface:
    """Returns a cached, pre-rendered volumetric smoke puff sprite in straight white."""
    global _SMOKE_SPRITE
    if _SMOKE_SPRITE is not None:
        return _SMOKE_SPRITE
    import numpy as np
    size = 128
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surf)
    half = size / 2.0
    pat = cairo.RadialGradient(half, half, 1.0, half, half, half - 2.0)
    pat.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 1.0)
    pat.add_color_stop_rgba(0.30, 1.0, 1.0, 1.0, 0.95)
    pat.add_color_stop_rgba(0.60, 1.0, 1.0, 1.0, 0.60)
    pat.add_color_stop_rgba(0.85, 1.0, 1.0, 1.0, 0.20)
    pat.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.0)
    cr.set_source(pat)
    cr.arc(half, half, half - 2.0, 0, 2 * math.pi)
    cr.fill()
    surf.flush()
    # Unpremultiply to pure straight white so GStreamer compositor gets vibrant 255 RGB
    data = np.frombuffer(surf.get_data(), dtype=np.uint8).reshape((size, size, 4))
    mask = data[:, :, 3] > 0
    data[mask, 0] = 255  # Blue
    data[mask, 1] = 255  # Green
    data[mask, 2] = 255  # Red
    surf.mark_dirty()
    _SMOKE_SPRITE = surf
    return _SMOKE_SPRITE


def _get_snow_sprite() -> cairo.ImageSurface:
    """Returns a cached, pre-rendered glowing snowflake sprite in straight white."""
    global _SNOW_SPRITE
    if _SNOW_SPRITE is not None:
        return _SNOW_SPRITE
    import numpy as np
    size = 64
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surf)
    half = size / 2.0
    pat = cairo.RadialGradient(half, half, 1.0, half, half, half - 2.0)
    pat.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 1.0)
    pat.add_color_stop_rgba(0.35, 1.0, 1.0, 1.0, 0.95)
    pat.add_color_stop_rgba(0.70, 1.0, 1.0, 1.0, 0.45)
    pat.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.0)
    cr.set_source(pat)
    cr.arc(half, half, half - 2.0, 0, 2 * math.pi)
    cr.fill()
    surf.flush()
    data = np.frombuffer(surf.get_data(), dtype=np.uint8).reshape((size, size, 4))
    mask = data[:, :, 3] > 0
    data[mask, 0] = 255
    data[mask, 1] = 255
    data[mask, 2] = 255
    surf.mark_dirty()
    _SNOW_SPRITE = surf
    return _SNOW_SPRITE


def draw_snow(cr: cairo.Context, t: float, width: int, height: int,
              amount: float = 1.0, speed: float = 1.0,
              size: float = 1.0, opacity: float = 0.95):
    """Renders falling snow with gentle sway, parallax layers and depth of field."""
    scale = min(width, height) / 720.0
    num_particles = max(10, int(90 * amount))
    margin = 35.0 * scale
    total_h = height + 2 * margin
    base_fall_speed = 75.0 * scale * speed
    glow_sprite = _get_snow_sprite()
    glow_half = 32.0

    for i in range(num_particles):
        s1 = _hash_float(i, 1)
        s2 = _hash_float(i, 2)
        s3 = _hash_float(i, 3)
        s4 = _hash_float(i, 4)
        s5 = _hash_float(i, 5)

        layer = s1
        speed_factor = 0.45 + layer * 1.15
        r = max(1.5, (2.0 + layer * 5.5) * scale * size)
        # Exaggerated pure white opacity
        alpha = max(0.0, min(1.0, (0.75 + layer * 0.25) * opacity))

        # Vertical position with continuous wrap
        y = (s2 * total_h + t * base_fall_speed * speed_factor) % total_h - margin

        # Horizontal sway
        sway_amp = (8.0 + 16.0 * s3) * scale
        sway_freq = 0.9 + 1.4 * s4
        sway_phase = s5 * 2.0 * math.pi
        x = (s3 * width + sway_amp * math.sin(t * sway_freq + sway_phase)) % width

        # Foreground snowflakes have soft glow halo; mid/distant ones are crisp solid white
        if layer > 0.65:
            cr.save()
            cr.translate(x, y)
            s_scale = (r * 2.0) / 64.0
            cr.scale(s_scale, s_scale)
            cr.set_source_surface(glow_sprite, -glow_half, -glow_half)
            cr.paint_with_alpha(alpha)
            cr.restore()
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, alpha)
            cr.arc(x, y, r, 0, 2 * math.pi)
            cr.fill()


CONFETTI_COLORS = [
    (0.96, 0.22, 0.38),  # Crimson / Vivid Red
    (1.00, 0.78, 0.12),  # Gold / Amber
    (0.18, 0.78, 0.94),  # Electric Cyan
    (0.38, 0.85, 0.32),  # Spring Green
    (0.68, 0.32, 0.92),  # Purple / Violet
    (1.00, 0.52, 0.18),  # Bright Orange
    (0.98, 0.42, 0.75),  # Hot Pink
    (0.92, 0.95, 0.98),  # Pearl White
]


def draw_confetti(cr: cairo.Context, t: float, width: int, height: int,
                  amount: float = 1.0, speed: float = 1.0,
                  size: float = 1.0, opacity: float = 0.9):
    """Renders festive tumbling confetti fluttering and falling under gravity."""
    scale = min(width, height) / 720.0
    num_particles = max(10, int(85 * amount))
    margin = 40.0 * scale
    total_h = height + 2 * margin
    base_fall_speed = 90.0 * scale * speed
    num_colors = len(CONFETTI_COLORS)

    for i in range(num_particles):
        s1 = _hash_float(i, 11)
        s2 = _hash_float(i, 23)
        s3 = _hash_float(i, 37)
        s4 = _hash_float(i, 49)
        s5 = _hash_float(i, 51)
        s6 = _hash_float(i, 73)

        # Depth and mass variation
        layer = 0.5 + 0.5 * s1
        fall_spd = (0.7 + 0.8 * s2) * base_fall_speed
        w = max(3.5, (12.0 + 9.0 * s3) * scale * size * layer)
        h = max(2.5, (7.0 + 7.0 * s4) * scale * size * layer)

        # Position with wrap
        y = (s2 * total_h + t * fall_spd) % total_h - margin

        # Flutter / sway horizontally
        sway_amp = (15.0 + 25.0 * s3) * scale
        sway_freq = 1.5 + 2.0 * s4
        sway_phase = s5 * 2.0 * math.pi
        x = (s1 * width + sway_amp * math.sin(t * sway_freq + sway_phase)) % width

        # 3D tumbling rotation
        tumble_rate = 2.0 + 4.5 * s6
        tumble_phase = s4 * 2.0 * math.pi
        tumble = math.cos(t * tumble_rate + tumble_phase)
        spin_rate = 1.0 + 2.5 * s5
        spin_angle = t * spin_rate + s3 * 6.28

        # Color and shading for front/back flip
        color_idx = int(s1 * 100) % num_colors
        base_r, base_g, base_b = CONFETTI_COLORS[color_idx]
        face_shade = 1.0 if tumble >= 0 else 0.75
        alpha = max(0.0, min(1.0, opacity * (0.8 + 0.2 * layer)))

        cr.save()
        cr.translate(x, y)
        cr.rotate(spin_angle)
        # Apply tumbling scale (simulate 3D rotation)
        cr.scale(1.0, abs(tumble) + 0.08)

        cr.set_source_rgba(base_r * face_shade, base_g * face_shade, base_b * face_shade, alpha)
        hw, hh = w / 2.0, h / 2.0
        cr.rectangle(-hw, -hh, w, h)
        cr.fill()
        cr.restore()


SPARKLE_PALETTE = [
    (1.00, 0.96, 0.82),  # Warm Champagne Gold
    (0.92, 0.96, 1.00),  # Diamond Ice White
    (1.00, 0.86, 0.38),  # Golden Shimmer
    (1.00, 0.78, 0.88),  # Rose Quartz
]


def draw_sparkles(cr: cairo.Context, t: float, width: int, height: int,
                  amount: float = 1.0, speed: float = 1.0,
                  size: float = 1.0, opacity: float = 0.9):
    """Renders twinkling star sparkles, diamond cross-bursts, and gentle glowing orbs."""
    scale = min(width, height) / 720.0
    num_particles = max(10, int(60 * amount))
    margin = 30.0 * scale
    total_h = height + 2 * margin
    drift_spd = 25.0 * scale * speed
    palette_len = len(SPARKLE_PALETTE)

    for i in range(num_particles):
        s1 = _hash_float(i, 101)
        s2 = _hash_float(i, 211)
        s3 = _hash_float(i, 307)
        s4 = _hash_float(i, 419)
        s5 = _hash_float(i, 521)
        s6 = _hash_float(i, 631)

        # Gentle upward drift
        y = (s2 * total_h - t * drift_spd * (0.6 + 0.8 * s3)) % total_h - margin
        # Subtle sideways float
        x = (s1 * width + 15.0 * scale * math.sin(t * 0.8 + s4 * 6.28)) % width

        # Twinkle pulse cycle
        pulse_freq = (1.8 + 2.5 * s4) * speed
        pulse_phase = s5 * 2.0 * math.pi
        pulse_val = math.sin(t * pulse_freq + pulse_phase)
        intensity = max(0.0, pulse_val) ** 2.2
        if intensity < 0.03:
            continue

        base_r, base_g, base_b = SPARKLE_PALETTE[int(s1 * 100) % palette_len]
        alpha = max(0.0, min(1.0, intensity * opacity))
        base_radius = (4.0 + 12.0 * s6) * scale * size

        # Center glow halo
        halo_radius = base_radius * 2.2
        pat = cairo.RadialGradient(x, y, 0.5, x, y, halo_radius)
        pat.add_color_stop_rgba(0.0, base_r, base_g, base_b, alpha)
        pat.add_color_stop_rgba(0.4, base_r, base_g, base_b, alpha * 0.5)
        pat.add_color_stop_rgba(1.0, base_r, base_g, base_b, 0.0)
        cr.set_source(pat)
        cr.arc(x, y, halo_radius, 0, 2 * math.pi)
        cr.fill()

        # 4-point diamond star cross flare
        if intensity > 0.25:
            ray_len = base_radius * (1.5 + 2.5 * intensity)
            ray_thick = max(0.8, 1.8 * scale * size)
            cr.save()
            cr.translate(x, y)
            rot = s3 * math.pi * 0.5 + t * 0.2
            cr.rotate(rot)

            cr.set_source_rgba(1.0, 1.0, 1.0, alpha * 0.95)
            # Horizontal ray
            cr.move_to(-ray_len, 0)
            cr.line_to(0, -ray_thick)
            cr.line_to(ray_len, 0)
            cr.line_to(0, ray_thick)
            cr.close_path()
            cr.fill()

            # Vertical ray
            cr.move_to(0, -ray_len)
            cr.line_to(ray_thick, 0)
            cr.line_to(0, ray_len)
            cr.line_to(-ray_thick, 0)
            cr.close_path()
            cr.fill()

            # Diagonal mini-burst for intense sparkles
            if intensity > 0.65:
                mini_len = ray_len * 0.45
                mini_thick = ray_thick * 0.6
                cr.rotate(math.pi / 4.0)
                cr.set_source_rgba(base_r, base_g, base_b, alpha * 0.7)
                cr.move_to(-mini_len, 0)
                cr.line_to(0, -mini_thick)
                cr.line_to(mini_len, 0)
                cr.line_to(0, mini_thick)
                cr.close_path()
                cr.fill()
                cr.move_to(0, -mini_len)
                cr.line_to(mini_thick, 0)
                cr.line_to(0, mini_len)
                cr.line_to(-mini_thick, 0)
                cr.close_path()
                cr.fill()

            cr.restore()


def draw_smoke(cr: cairo.Context, t: float, width: int, height: int,
               amount: float = 1.0, speed: float = 1.0,
               size: float = 1.0, opacity: float = 0.90):
    """Renders rising atmospheric smoke / vapor puffs billowing upwards in brilliant white."""
    scale = min(width, height) / 720.0
    num_puffs = max(8, int(28 * amount))
    base_rise_speed = 65.0 * scale * speed
    cycle_duration = max(3.5, (height * 1.2) / max(10.0, base_rise_speed))
    sprite = _get_smoke_sprite()
    sprite_half = 64.0

    for i in range(num_puffs):
        s1 = _hash_float(i, 311)
        s2 = _hash_float(i, 421)
        s3 = _hash_float(i, 541)
        s4 = _hash_float(i, 653)
        s5 = _hash_float(i, 769)

        local_spd = 0.75 + 0.5 * s2
        progress = ((t * local_spd / cycle_duration) + s1) % 1.0

        y_start = height + 40.0 * scale
        y_end = -80.0 * scale
        y = y_start + (y_end - y_start) * progress

        initial_r = (35.0 + 25.0 * s3) * scale * size
        final_r = (140.0 + 100.0 * s4) * scale * size
        r = initial_r + (final_r - initial_r) * (progress ** 0.75)

        # Multi-harmonic wavy drift (billowing turbulence)
        sway = (35.0 * scale * math.sin(progress * 4.2 + s4 * 6.28) +
                18.0 * scale * math.sin(progress * 7.5 + s5 * 6.28))
        drift = (progress * 70.0 * (s3 - 0.5)) * scale
        x = (s2 * width * 0.75 + width * 0.12) + sway + drift

        # Opacity envelope: smooth fade in at source, fade out upon dispersion
        fade_in = min(1.0, progress / 0.12)
        fade_out = max(0.0, (1.0 - progress) / 0.88)
        # Exaggerated thick white smoke
        puff_alpha = fade_in * fade_out * opacity * (0.65 + 0.30 * s5)
        if puff_alpha <= 0.01:
            continue

        # Draw 2 overlapping sub-lobes per puff to form an organic billowing cloud
        sub_offsets = [
            (0.0, 0.0, 1.0),
            (0.30 * r * math.cos(s1 * 6.28 + progress * 2.0), 0.25 * r * math.sin(s1 * 6.28), 0.85),
        ]
        for ox, oy, rad_mul in sub_offsets:
            cx = x + ox
            cy = y + oy
            sub_r = r * rad_mul
            cr.save()
            cr.translate(cx, cy)
            s_scale = (sub_r * 2.0) / 128.0
            cr.scale(s_scale, s_scale)
            cr.set_source_surface(sprite, -sprite_half, -sprite_half)
            cr.paint_with_alpha(puff_alpha * 0.85)
            cr.restore()


PARTICLE_RENDERERS: Dict[str, Callable] = {
    "snow": draw_snow,
    "confetti": draw_confetti,
    "sparkles": draw_sparkles,
    "smoke": draw_smoke,
}


def render_particles(cr: cairo.Context, effect: str, t: float, width: int, height: int,
                     amount: float = 1.0, speed: float = 1.0,
                     size: float = 1.0, opacity: float = 0.85):
    """Draws the requested particle effect on the cairo context."""
    renderer = PARTICLE_RENDERERS.get(effect, draw_snow)
    renderer(cr, t, width, height, amount, speed, size, opacity)

