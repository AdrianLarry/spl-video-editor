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
"""Tests for the pitivi.utils.transitions module."""
from gi.repository import GES
from gi.repository import Gst

from pitivi.utils.fades import get_keyframes
from pitivi.utils.timeline import EditingContext
from pitivi.utils.transitions import DISSOLVE
from pitivi.utils.transitions import FADE_TO_BLACK
from pitivi.utils.transitions import FADE_TO_WHITE
from pitivi.utils.transitions import get_contacts
from pitivi.utils.transitions import get_image_fades
from pitivi.utils.transitions import get_max_duration
from pitivi.utils.transitions import get_video_transition
from pitivi.utils.transitions import PUSH
from pitivi.utils.transitions import RIGHT
from pitivi.utils.transitions import SOFT_WIPE
from pitivi.utils.transitions import TOP
from pitivi.utils.transitions import get_white_fades
from pitivi.utils.transitions import is_white_effect
from pitivi.utils.transitions import set_transition
from tests import common

SECOND = Gst.SECOND


class TransitionsTest(common.TestCase):
    """Tests for adding and removing transitions where clips meet."""

    def _add_clip(self, start, duration=4, layer=None):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("one_fps_numeroted_blue.mkv"))
        clip = (layer or self.layer).add_asset(asset, start * SECOND, 0, duration * SECOND,
                                               GES.TrackType.UNKNOWN)
        self.assertIsNotNone(clip)
        return clip

    def _get_transitions(self):
        return [(clip.props.start / SECOND, clip.props.duration / SECOND)
                for clip in self.layer.get_clips() if isinstance(clip, GES.TransitionClip)]

    @common.setup_timeline
    def test_dissolve(self):
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)
        clip_c = self._add_clip(10)
        other_layer = self.timeline.append_layer()
        other_clip = self._add_clip(6, layer=other_layer)

        # The clips meeting have a contact, the gap does not.
        contact, = get_contacts(self.layer)
        self.assertEqual((contact.clip_a, contact.clip_b, contact.kind), (clip_a, clip_b, None))

        with self.action_log.started("transition"):
            contact = set_transition(contact, DISSOLVE, SECOND)
        # The second clip and the following ones moved to the left.
        self.assertEqual([clip.props.start / SECOND for clip in (clip_a, clip_b, clip_c, other_clip)],
                         [0, 3, 9, 6])
        self.assertEqual(self._get_transitions(), [(3, 1)])
        self.assertEqual(get_contacts(self.layer), [contact])
        self.assertEqual(contact.kind, DISSOLVE)

        # A longer one.
        with self.action_log.started("transition"):
            contact = set_transition(contact, DISSOLVE, 2 * SECOND)
        self.assertEqual([clip.props.start / SECOND for clip in (clip_b, clip_c)], [2, 8])
        self.assertEqual(self._get_transitions(), [(2, 2)])

        self.action_log.undo()
        self.assertEqual(self._get_transitions(), [(3, 1)])
        self.action_log.undo()
        self.assertEqual(self._get_transitions(), [])
        self.assertEqual([clip.props.start / SECOND for clip in (clip_b, clip_c)], [4, 10])

    @common.setup_timeline
    def test_fade_to_black(self):
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)

        contact, = get_contacts(self.layer)
        with self.action_log.started("transition"):
            contact = set_transition(contact, FADE_TO_BLACK, SECOND)
        # Nothing moves, the clips fade out and in.
        self.assertEqual(clip_b.props.start, 4 * SECOND)
        self.assertEqual(self._get_transitions(), [])
        self.assertEqual(get_image_fades(clip_a).fade_out, SECOND // 2)
        self.assertEqual(get_image_fades(clip_b).fade_in, SECOND // 2)
        self.assertEqual(get_contacts(self.layer), [contact])

        # Replaced by a dissolve.
        with self.action_log.started("transition"):
            contact = set_transition(contact, DISSOLVE, SECOND)
        self.assertEqual(get_image_fades(clip_a).fade_out, 0)
        self.assertEqual(get_image_fades(clip_b).fade_in, 0)
        self.assertEqual(clip_b.props.start, 3 * SECOND)

        self.action_log.undo()
        self.assertEqual(get_contacts(self.layer)[0].kind, FADE_TO_BLACK)

    @common.setup_timeline
    def test_trimming_keeps_the_dissolve(self):
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)
        contact, = get_contacts(self.layer)
        with self.action_log.started("transition"):
            set_transition(contact, DISSOLVE, SECOND)

        # Extending the first clip pushes the second one, keeping the
        # transition.
        with self.action_log.started("trim"):
            context = EditingContext(clip_a, self.timeline, GES.EditMode.EDIT_TRIM,
                                     GES.Edge.EDGE_END, self.app)
            context.edit_to(5 * SECOND, self.layer)
            context.finish()
        self.assertEqual(clip_b.props.start, 4 * SECOND)
        self.assertEqual(self._get_transitions(), [(4, 1)])

        # Extending the start of the second clip does not overlap more.
        with self.action_log.started("trim"):
            context = EditingContext(clip_b, self.timeline, GES.EditMode.EDIT_TRIM,
                                     GES.Edge.EDGE_START, self.app)
            context.edit_to(2 * SECOND, self.layer)
            context.finish()
        self.assertEqual(self._get_transitions(), [(4, 1)])

    @common.setup_timeline
    def test_fade_to_white(self):
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)
        clip_c = self._add_clip(8)

        contact_ab, contact_bc = get_contacts(self.layer)
        with self.action_log.started("transition"):
            set_transition(contact_ab, FADE_TO_WHITE, SECOND)
        with self.action_log.started("transition"):
            set_transition(contact_bc, FADE_TO_WHITE, 2 * SECOND)
        # Nothing moves, the clips turn white with a single effect each.
        self.assertEqual([clip.props.start / SECOND for clip in (clip_a, clip_b, clip_c)], [0, 4, 8])
        self.assertEqual(get_white_fades(clip_b)[1:], (SECOND // 2, SECOND))
        self.assertEqual(len([effect for effect in clip_b.get_top_effects()
                              if is_white_effect(effect)]), 1)
        self.assertEqual([contact.kind for contact in get_contacts(self.layer)],
                         [FADE_TO_WHITE, FADE_TO_WHITE])

        # The keyframes of the effect go from white to the original image.
        effect, = clip_a.get_top_effects()
        brightness = effect.get_control_binding("brightness").props.control_source
        # At the end the image is white: videobalance applies the brightness
        # to the luma between 16 and 235.
        self.assertEqual([(timestamp, round(value, 3)) for timestamp, value in get_keyframes(brightness)],
                         [(0, 0.5), (int(3.5 * SECOND), 0.5), (4 * SECOND, round((1 + 219 / 255) / 2, 3))])
        contrast = effect.get_control_binding("contrast").props.control_source
        self.assertEqual(get_keyframes(contrast)[-1], (4 * SECOND, 0.0))

        # Trimming keeps the fade to white at the new end.
        with self.action_log.started("trim"):
            context = EditingContext(clip_a, self.timeline, GES.EditMode.EDIT_TRIM,
                                     GES.Edge.EDGE_END, self.app)
            context.edit_to(3 * SECOND, self.layer)
            context.finish()
        self.assertEqual(get_white_fades(clip_a).fade_out, SECOND // 2)
        self.action_log.undo()

        # Removed, the effect goes away from the clips without fades to white.
        contact_ab = get_contacts(self.layer)[0]
        with self.action_log.started("transition"):
            set_transition(contact_ab, FADE_TO_BLACK, SECOND)
        self.assertEqual(clip_a.get_top_effects(), [])
        self.assertEqual(get_white_fades(clip_b)[1:], (0, SECOND))

        self.action_log.undo()
        self.assertEqual(get_contacts(self.layer)[0].kind, FADE_TO_WHITE)

    @common.setup_timeline
    def test_max_duration(self):
        self._wait_until_project_loaded()
        self._add_clip(0, duration=3)
        self._add_clip(3, duration=1)
        contact, = get_contacts(self.layer)
        # A dissolve overlaps at most half of the shortest clip, each clip
        # fades at most during half of its length.
        self.assertEqual(get_max_duration(contact, DISSOLVE), SECOND // 2)
        self.assertEqual(get_max_duration(contact, FADE_TO_WHITE), SECOND)
        self.assertEqual(get_max_duration(contact, FADE_TO_BLACK), SECOND)

    @common.setup_timeline
    def test_soft_wipe(self):
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)

        contact, = get_contacts(self.layer)
        with self.action_log.started("transition"):
            contact = set_transition(contact, SOFT_WIPE, SECOND, TOP)
        # The clips overlap as for a dissolve.
        self.assertEqual(clip_b.props.start, 3 * SECOND)
        self.assertEqual(get_contacts(self.layer), [contact])
        self.assertEqual((contact.kind, contact.direction), (SOFT_WIPE, TOP))
        element = get_video_transition(clip_b)
        self.assertEqual(element.get_transition_type(), GES.VideoStandardTransitionType.BAR_WIPE_TB)
        self.assertFalse(element.is_inverted())
        self.assertGreater(element.get_border(), 0)

        # Another direction.
        with self.action_log.started("transition"):
            contact = set_transition(contact, SOFT_WIPE, SECOND, RIGHT)
        self.assertEqual(get_contacts(self.layer)[0].direction, RIGHT)
        self.assertEqual(clip_b.props.start, 3 * SECOND)

        self.action_log.undo()
        contact, = get_contacts(self.layer)
        self.assertEqual((contact.kind, contact.direction), (SOFT_WIPE, TOP))
        self.action_log.undo()
        self.assertEqual(get_contacts(self.layer)[0].kind, None)
        self.assertEqual(clip_a.props.duration, 4 * SECOND)

    @common.setup_timeline
    def test_push(self):
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)
        source_a = clip_a.find_track_element(None, GES.VideoSource)
        source_b = clip_b.find_track_element(None, GES.VideoSource)
        width = self.project.videowidth
        base_a = source_a.get_child_property("posx")[1]
        base_b = source_b.get_child_property("posx")[1]

        def get_posx_keyframes(source):
            binding = source.get_control_binding("posx")
            if not binding:
                return None
            return [(timestamp / SECOND, round(value)) for timestamp, value
                    in get_keyframes(binding.props.control_source)]

        contact, = get_contacts(self.layer)
        with self.action_log.started("transition"):
            contact = set_transition(contact, PUSH, SECOND, RIGHT)
        self.assertEqual(clip_b.props.start, 3 * SECOND)
        self.assertEqual((contact.kind, contact.direction), (PUSH, RIGHT))
        self.assertEqual(get_contacts(self.layer), [contact])
        # The first clip goes out to the left, the second comes from the right.
        self.assertEqual(get_posx_keyframes(source_a), [(0, base_a), (3, base_a), (4, base_a - width)])
        self.assertEqual(get_posx_keyframes(source_b), [(0, base_b + width), (1, base_b), (4, base_b)])
        self.assertEqual(get_video_transition(clip_b).get_border(), 0)

        # Extending the first clip moves its push with its end.
        with self.action_log.started("trim"):
            context = EditingContext(clip_a, self.timeline, GES.EditMode.EDIT_TRIM,
                                     GES.Edge.EDGE_END, self.app)
            context.edit_to(5 * SECOND, self.layer)
            context.finish()
        self.assertEqual(clip_b.props.start, 4 * SECOND)
        self.assertEqual(get_posx_keyframes(source_a), [(0, base_a), (4, base_a), (5, base_a - width)])
        self.action_log.undo()
        self.assertEqual(get_posx_keyframes(source_a), [(0, base_a), (3, base_a), (4, base_a - width)])

        # Replaced by a soft wipe, the clips stay in place.
        contact = get_contacts(self.layer)[0]
        with self.action_log.started("transition"):
            set_transition(contact, SOFT_WIPE, SECOND, RIGHT)
        self.assertEqual(get_posx_keyframes(source_a), [(0, base_a), (4, base_a)])
        self.assertEqual(get_posx_keyframes(source_b), [(0, base_b), (4, base_b)])

        self.action_log.undo()
        self.assertEqual(get_contacts(self.layer)[0].kind, PUSH)
        self.assertEqual(get_posx_keyframes(source_b), [(0, base_b + width), (1, base_b), (4, base_b)])

        # Undoing and redoing the push itself.
        self.action_log.undo()
        self.assertEqual(get_contacts(self.layer)[0].kind, None)
        self.assertIsNone(get_posx_keyframes(source_b))
        self.action_log.redo()
        self.assertEqual(get_contacts(self.layer)[0].kind, PUSH)
        self.assertEqual(get_posx_keyframes(source_a), [(0, base_a), (3, base_a), (4, base_a - width)])
        self.assertEqual(get_posx_keyframes(source_b), [(0, base_b + width), (1, base_b), (4, base_b)])
