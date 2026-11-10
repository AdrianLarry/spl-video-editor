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
"""The quality of the prepared preview, chosen or measured.

A smaller preview is prepared faster: computers with less power wait
less. In the automatic mode the time taken to prepare the pieces is
measured, and the quality goes down when they take longer than they last,
and up again when there is time to spare. The export is not affected.
"""
from gettext import gettext as _
from typing import List
from typing import Optional

AUTO = "auto"
HIGH = "alta"
MEDIUM = "media"
LOW = "baja"
LEVELS = [HIGH, MEDIUM, LOW]
# How smaller the timeline is rendered.
FACTORS = {HIGH: 1.0, MEDIUM: 0.5, LOW: 1 / 3}
# Time taken to prepare for each second of video.
SLOW = 0.9
FAST = 0.35
# The pieces measured.
MEASURED = 4


def register_settings():
    """Adds the settings and the choice in the preferences."""
    # pylint: disable=import-outside-toplevel
    from pitivi.dialogs.prefs import PreferencesDialog
    from pitivi.settings import GlobalSettings
    GlobalSettings.add_config_section("preview")
    GlobalSettings.add_config_option("previewQuality", section="preview", key="quality",
                                     default=AUTO, notify=True)
    # Starting at the medium one, which looks the same in the small viewer:
    # the first time the computer is measured, waiting less.
    GlobalSettings.add_config_option("previewAutoLevel", section="preview", key="auto-level",
                                     default=MEDIUM)
    PreferencesDialog.add_section("preview", _("Video preview"))
    PreferencesDialog.add_choice_preference(
        "previewQuality", section="preview",
        label=_("Quality of the preview"),
        description=_("A lower quality is prepared faster, playing with fewer waits "
                      "on less powerful computers. The exported video always has "
                      "the full quality."),
        choices=[(_("Automatic"), AUTO), (_("High"), HIGH),
                 (_("Medium"), MEDIUM), (_("Low"), LOW)])


class AutoQuality:
    """Chooses the level from the time taken to prepare the pieces."""

    def __init__(self, level: str = HIGH):
        self.level = level if level in LEVELS else HIGH
        self.samples: List[float] = []

    def add(self, seconds: float, duration: float) -> Optional[str]:
        """Records a piece, returns the new level when it changes."""
        if duration <= 0:
            return None
        self.samples = (self.samples + [seconds / duration])[-MEASURED:]
        if len(self.samples) < MEASURED:
            return None
        ratio = sum(self.samples) / len(self.samples)
        index = LEVELS.index(self.level)
        if ratio > SLOW and index < len(LEVELS) - 1:
            index += 1
        elif ratio < FAST and index > 0:
            index -= 1
        else:
            return None
        self.level = LEVELS[index]
        self.samples = []
        return self.level
