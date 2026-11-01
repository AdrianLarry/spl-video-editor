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
"""Widget summarizing the selected clip."""
from gettext import gettext as _

from gi.repository import GES
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Pango

from pitivi.clip_properties.overlay import get_shape_name
from pitivi.clip_properties.overlay import is_overlay_clip
from pitivi.clip_properties.particles import get_particle_effect_name
from pitivi.clip_properties.particles import is_particle_clip
from pitivi.clip_properties.particles import PARTICLE_LABELS
from pitivi.utils.misc import filename_from_uri
from pitivi.utils.shapes import SHAPES
from pitivi.utils.ui import beautify_length
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING
from pitivi.utils.ui import time_to_string


def describe_clip(clip):
    """Returns the kind, the name and an icon name for the specified clip."""
    if isinstance(clip, GES.TitleClip):
        text = ""
        for child in clip.get_children(False):
            if isinstance(child, GES.TitleSource):
                text = child.get_child_property("text")[1] or ""
        name = text.strip().splitlines()[0] if text.strip() else _("Text")
        return _("Text"), name, "insert-text-symbolic"

    if isinstance(clip, GES.TransitionClip):
        return _("Transition"), clip.props.vtype.value_nick, "media-playlist-shuffle-symbolic"

    if is_particle_clip(clip):
        p_name = get_particle_effect_name(clip)
        label = PARTICLE_LABELS.get(p_name, _("Effect"))
        return _("Effect"), label, "weather-snow-symbolic"

    if is_overlay_clip(clip):
        shape = SHAPES.get(get_shape_name(clip))
        return _("Overlay"), shape.label if shape else _("Shape"), "applications-graphics-symbolic"

    if isinstance(clip, GES.TestClip):
        return _("Color"), _("Color"), "applications-graphics-symbolic"

    if isinstance(clip, GES.UriClip):
        name = filename_from_uri(clip.props.uri)
        if clip.get_asset().is_image():
            return _("Image"), name, "image-x-generic-symbolic"
        if clip.props.supported_formats & GES.TrackType.VIDEO:
            return _("Video"), name, "video-x-generic-symbolic"
        return _("Audio"), name, "audio-x-generic-symbolic"

    return "", clip.props.name, "applications-multimedia-symbolic"


class ClipSummary(Gtk.Box):
    """Shows the kind, the name and the position of a clip."""

    def __init__(self):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACING)
        self.props.margin_start = SPACING
        self.props.margin_end = SPACING
        self.props.margin_top = PADDING

        self._icon = Gtk.Image()
        self._icon.set_pixel_size(32)
        self.pack_start(self._icon, False, False, 0)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._kind_label = Gtk.Label(xalign=0)
        self._kind_label.get_style_context().add_class("dim-label")
        self._name_label = Gtk.Label(xalign=0)
        self._name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._time_label = Gtk.Label(xalign=0)
        self._time_label.get_style_context().add_class("dim-label")
        for label in (self._kind_label, self._name_label, self._time_label):
            labels.pack_start(label, False, False, 0)
        self.pack_start(labels, True, True, 0)

        self.show_all()
        self.set_no_show_all(True)
        self.clip = None
        self._handler_ids = []
        self.hide()

    def set_clip(self, clip):
        """Shows the summary of the specified clip, or hides it if None."""
        for handler_id in self._handler_ids:
            self.clip.disconnect(handler_id)
        self._handler_ids = []
        self.clip = clip
        if not clip:
            self.hide()
            return

        self._handler_ids = [clip.connect(signal, self.__clip_changed_cb)
                             for signal in ("notify::start", "notify::duration", "deep-notify")]
        self.__update()
        self.show()

    def __clip_changed_cb(self, clip, *unused_args):
        if clip is self.clip:
            self.__update()

    def __update(self):
        kind, name, icon_name = describe_clip(self.clip)
        self._icon.set_from_icon_name(icon_name, Gtk.IconSize.DND)
        self._kind_label.set_markup("<small>%s</small>" % GLib.markup_escape_text(kind.upper()))
        self._name_label.set_markup("<b>%s</b>" % GLib.markup_escape_text(name))
        start = self.clip.props.start
        duration = self.clip.props.duration
        self._time_label.set_markup("<small>%s</small>" % GLib.markup_escape_text(
            "%s – %s · %s" % (time_to_string(start), time_to_string(start + duration),
                              beautify_length(duration))))
