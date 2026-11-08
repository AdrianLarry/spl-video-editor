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
"""The prepared preview: the timeline rendered ahead, played smoothly.

NLE builds again all the sources of the timeline at every clip edge of
any layer, and with photos with effects over a video it takes up to two
seconds: the live preview has to wait there. The timeline is rendered in
the background, in another process, in pieces of a few seconds made again
only when what they show changes, and played instead of the live preview
when it is prepared from the playhead to the end.

- chunks: what each piece shows, as a key naming its file.
- worker: the process rendering the pieces.
- manager: when to render, and which pieces are ready.
- player: plays the prepared pieces in the viewer.
"""
