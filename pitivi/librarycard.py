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
"""Cards showing the files of the project, as in the mockup.

All the cards have the same shape. The landscape images cover the card,
the portrait ones are shown whole in the middle, the audio files show a
waveform.
"""
import math
from gettext import gettext as _

import cairo
from gi.repository import Gdk
from gi.repository import GES
from gi.repository import Gst
from gi.repository import Gtk
from gi.repository import Pango
from gi.repository import PangoCairo

VIDEO = "video"
IMAGE = "image"
AUDIO = "audio"

# The narrowest card, the cards grow to fill the row.
MIN_CARD_WIDTH = 112
CARD_SPACING = 12
CARD_RADIUS = 8

BADGE_ICONS = {VIDEO: "video-x-generic-symbolic",
               IMAGE: "image-x-generic-symbolic",
               AUDIO: "audio-x-generic-symbolic"}

# The colors of the mockup.
CARD_BACKGROUND = (0.043, 0.047, 0.063)
BADGE_BACKGROUND = (0.039, 0.047, 0.063, 0.78)
USED_COLOR = (0.373, 0.827, 0.604)
AUDIO_TOP = (0.122, 0.420, 0.349)
AUDIO_BOTTOM = (0.075, 0.267, 0.227)
WAVE_COLOR = (0.663, 0.941, 0.855)


def get_kind(asset: GES.UriClipAsset) -> str:
    """Returns the kind of the file: VIDEO, IMAGE or AUDIO."""
    if asset.is_image():
        return IMAGE
    if asset.get_info().get_video_streams():
        return VIDEO
    return AUDIO


def format_duration(duration: int) -> str:
    """Returns a duration as minutes and seconds, as "0:14"."""
    seconds = round(duration / Gst.SECOND)
    return "%d:%02d" % divmod(seconds, 60)


def get_waveform(key: str, count: int):
    """Returns the heights of the bars of a waveform, between 0 and 1.

    It is not the sound of the file, it only shows that it is audio. The
    same key gives the same waveform, as in the mockup.
    """
    seed = 0
    for char in key:
        seed = (seed * 31 + ord(char)) % 4294967296

    def random():
        nonlocal seed
        seed = (seed * 1664525 + 1013904223) % 4294967296
        return seed / 4294967296

    heights = []
    for index in range(count):
        position = index * 160 / count
        height = (0.18 + 0.82 * abs(math.sin(position * 0.11 + random()))) * (0.35 + 0.65 * random())
        heights.append(height)
    return heights


def rounded_rectangle(cr, x, y, width, height, radius):
    radius = min(radius, width / 2, height / 2)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


def draw_picture(cr, pixbuf, width, height):
    """Draws the picture covering the card, or whole if it is portrait."""
    pixbuf_width = pixbuf.get_width()
    pixbuf_height = pixbuf.get_height()
    portrait = pixbuf_height > pixbuf_width
    ratio = (min if portrait else max)(width / pixbuf_width, height / pixbuf_height)
    cr.save()
    cr.translate(width / 2, height / 2)
    cr.scale(ratio, ratio)
    Gdk.cairo_set_source_pixbuf(cr, pixbuf, -pixbuf_width / 2, -pixbuf_height / 2)
    cr.paint()
    cr.restore()


def draw_waveform(cr, key, width, height):
    """Draws the background and the waveform of an audio file."""
    gradient = cairo.LinearGradient(0, 0, width, height)
    gradient.add_color_stop_rgb(0, *AUDIO_TOP)
    gradient.add_color_stop_rgb(1, *AUDIO_BOTTOM)
    cr.set_source(gradient)
    cr.paint()

    # The waveform in the middle, between the badges.
    left = width * 0.08
    wave_width = width - 2 * left
    middle = height / 2
    amplitude = height * 0.24
    count = max(10, int(wave_width / 2.5))
    cr.set_source_rgb(*WAVE_COLOR)
    cr.set_line_width(max(1, wave_width / count * 0.55))
    for index, bar in enumerate(get_waveform(key, count)):
        x = left + (index + 0.5) * wave_width / count
        cr.move_to(x, middle - bar * amplitude)
        cr.line_to(x, middle + bar * amplitude)
    cr.stroke()


def draw_badge(cr, widget, x, y, text=None, icon_name=None, color=(1, 1, 1), align_right=False,
               align_bottom=False):
    """Draws a dark badge with an icon and/or a text, as in the mockup."""
    layout = None
    text_width = text_height = 0
    if text:
        layout = widget.create_pango_layout(text)
        font = Pango.FontDescription.from_string("Sans Bold 8")
        layout.set_font_description(font)
        text_width, text_height = layout.get_pixel_size()
    icon_size = 13
    padding = 3 if not text else 5
    gap = 3 if text and icon_name else 0
    content_width = (icon_size if icon_name else 0) + gap + text_width
    content_height = max(icon_size if icon_name else 0, text_height)
    badge_width = content_width + 2 * padding
    badge_height = content_height + 4
    if align_right:
        x -= badge_width
    if align_bottom:
        y -= badge_height

    rounded_rectangle(cr, x, y, badge_width, badge_height, 5)
    cr.set_source_rgba(*BADGE_BACKGROUND)
    cr.fill()

    cursor = x + padding
    if icon_name:
        pixbuf = load_symbolic_icon(icon_name, icon_size, color)
        if pixbuf:
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, cursor, y + (badge_height - icon_size) / 2)
            cr.paint()
        cursor += icon_size + gap
    if layout:
        cr.move_to(cursor, y + (badge_height - text_height) / 2)
        cr.set_source_rgb(*color)
        PangoCairo.show_layout(cr, layout)


_icons = {}


def load_symbolic_icon(icon_name, size, color):
    key = (icon_name, size, color)
    if key not in _icons:
        theme = Gtk.IconTheme.get_default()
        info = theme.lookup_icon(icon_name, size, Gtk.IconLookupFlags.FORCE_SIZE)
        pixbuf = None
        if info:
            rgba = Gdk.RGBA(*color, 1)
            pixbuf, unused_was_symbolic = info.load_symbolic(rgba, None, None, None)
        _icons[key] = pixbuf
    return _icons[key]


class LibraryCard(Gtk.DrawingArea):
    """The card of a file, with its kind, duration and whether it is used.

    Attributes:
        item (AssetStoreItem): The file.
        is_used (function): Tells whether the file is used in the timeline.
    """

    def __init__(self, item, is_used):
        Gtk.DrawingArea.__init__(self)
        self.item = item
        self.is_used = is_used
        self.kind = get_kind(item.asset)
        self.set_card_width(MIN_CARD_WIDTH)

    def set_card_width(self, width):
        self.set_size_request(width, round(width * 9 / 16))

    def do_draw(self, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        rounded_rectangle(cr, 0, 0, width, height, CARD_RADIUS)
        cr.clip()
        cr.set_source_rgb(*CARD_BACKGROUND)
        cr.paint()

        if self.kind == AUDIO:
            draw_waveform(cr, self.item.uri, width, height)
        else:
            pixbuf = self.item.thumb_decorator.card_thumb
            if pixbuf:
                draw_picture(cr, pixbuf, width, height)

        # A thin light border, as in the mockup.
        rounded_rectangle(cr, 0.5, 0.5, width - 1, height - 1, CARD_RADIUS)
        cr.set_source_rgba(1, 1, 1, 0.07)
        cr.set_line_width(1)
        cr.stroke()

        margin = 6
        draw_badge(cr, self, margin, margin, icon_name=BADGE_ICONS[self.kind])
        if self.kind == IMAGE:
            duration_text = _("Photo")
        else:
            duration_text = format_duration(self.item.asset.get_duration())
        draw_badge(cr, self, width - margin, height - margin, text=duration_text,
                   align_right=True, align_bottom=True)
        if self.is_used(self.item.asset):
            draw_badge(cr, self, margin, height - margin, text=_("In use"),
                       icon_name="object-select-symbolic", color=USED_COLOR, align_bottom=True)
        return False
