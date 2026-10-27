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

from pitivi.utils.blurfill import get_blur_fill
from pitivi.utils.blurfill import set_blur_fill
from pitivi.utils.fades import get_keyframes
from pitivi.utils.timeline import EditingContext
from pitivi.utils.transitions import BLUR
from pitivi.utils.transitions import BOTTOM
from pitivi.utils.transitions import DISSOLVE
from pitivi.utils.transitions import FADE_TO_BLACK
from pitivi.utils.transitions import FADE_TO_WHITE
from pitivi.utils.transitions import get_blur_fades
from pitivi.utils.transitions import get_contacts
from pitivi.utils.transitions import get_image_fades
from pitivi.utils.transitions import get_max_duration
from pitivi.utils.transitions import get_video_transition
from pitivi.utils.transitions import is_blur_effect
from pitivi.utils.transitions import LEFT
from pitivi.utils.transitions import PUSH
from pitivi.utils.transitions import RIGHT
from pitivi.utils.transitions import SOFT_WIPE
from pitivi.utils.transitions import TOP
from pitivi.utils.transitions import get_white_fades
from pitivi.utils.transitions import is_white_effect
from pitivi.utils.transitions import remove_transition
from pitivi.utils.transitions import set_image_fades
from pitivi.utils.transitions import set_blur_fades
from pitivi.utils.transitions import set_transition
from pitivi.utils.transitions import wipes_work
from pitivi.utils.transitions import PUSH_WIPES
from pitivi.utils.transitions import SOFT_WIPE_BORDER
from pitivi.utils.transitions import sync_pushes
from pitivi.utils.transitions import sync_saved_types
from pitivi.utils.transitions import WIPES
from tests import common

SECOND = Gst.SECOND


class TransitionsTest(common.TestCase):
    """Tests for adding and removing transitions where clips meet."""

    @common.setup_timeline
    def test_blur_transition_with_fill(self):
        self._wait_until_project_loaded()
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("flat_colour1_640x480.png"))
        self.layer.add_asset(asset, 0, 0, 3 * SECOND, GES.TrackType.VIDEO)
        clip_b = self.layer.add_asset(asset, 3 * SECOND, 0, 3 * SECOND, GES.TrackType.VIDEO)
        self.layer.add_asset(asset, 6 * SECOND, 0, 3 * SECOND, GES.TrackType.VIDEO)
        for fill_first in (False, True):
            with self.subTest(fill_first=fill_first):
                with self.action_log.started("blur and fill", toplevel=True):
                    if fill_first:
                        set_blur_fill(clip_b, True)
                    set_transition(get_contacts(self.layer)[0], BLUR, SECOND)
                    if not fill_first:
                        set_blur_fill(clip_b, True)
                    sync_pushes(self.layer)
                fill = get_blur_fill(clip_b)
                blur = next(effect for effect in clip_b.get_top_effects() if is_blur_effect(effect))
                self.assertLess(clip_b.get_top_effect_index(blur), clip_b.get_top_effect_index(fill))
                self.assertIn("width=1920,height=1080", blur.props.bin_description)
                self.assertEqual(get_blur_fades(clip_b).fade_in, SECOND)
                with self.action_log.started("remove fill", toplevel=True):
                    set_blur_fill(clip_b, False)
                    sync_pushes(self.layer)
                blur = next(effect for effect in clip_b.get_top_effects() if is_blur_effect(effect))
                self.assertIn("width=640,height=480", blur.props.bin_description)

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
    def test_blur(self):
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)

        contact, = get_contacts(self.layer)
        with self.action_log.started("transition"):
            contact = set_transition(contact, BLUR, SECOND)
        # The clips overlap as for a dissolve, both blurred.
        self.assertEqual(clip_b.props.start, 3 * SECOND)
        self.assertEqual(self._get_transitions(), [(3, 1)])
        self.assertEqual(get_blur_fades(clip_a).fade_out, SECOND)
        self.assertEqual(get_blur_fades(clip_b).fade_in, SECOND)
        self.assertEqual(len([e for e in clip_a.get_top_effects() if is_blur_effect(e)]), 1)
        self.assertEqual(len([e for e in clip_b.get_top_effects() if is_blur_effect(e)]), 1)
        self.assertEqual(get_contacts(self.layer), [contact])
        self.assertEqual(contact.kind, BLUR)
        self.assertTrue(contact.overlapping)
        # The most blurred in the middle: the first clip from it, the
        # second one until it.
        blur_a = [e for e in clip_a.get_top_effects() if is_blur_effect(e)][0]
        keyframes = get_keyframes(blur_a.get_control_binding("sigma").props.control_source)
        self.assertEqual([(t / SECOND, v) for t, v in keyframes][-3:], [(3, 0), (3.5, 6), (4, 6)])

        # Replaced by a dissolve, the blurs go.
        with self.action_log.started("transition"):
            contact = set_transition(contact, DISSOLVE, SECOND)
        self.assertEqual(get_blur_fades(clip_a).fade_out, 0)
        self.assertEqual(get_blur_fades(clip_b).fade_in, 0)
        self.assertEqual(len([e for e in clip_a.get_top_effects() if is_blur_effect(e)]), 0)
        self.assertEqual(len([e for e in clip_b.get_top_effects() if is_blur_effect(e)]), 0)
        self.assertEqual(clip_b.props.start, 3 * SECOND)

        self.action_log.undo()
        self.assertEqual(get_contacts(self.layer)[0].kind, BLUR)

        # Removed, the clips meet again.
        with self.action_log.started("transition"):
            remove_transition(get_contacts(self.layer)[0])
        self.assertEqual(clip_b.props.start, 4 * SECOND)
        self.assertEqual(get_blur_fades(clip_a).fade_out, 0)
        self.assertIsNone(get_contacts(self.layer)[0].kind)

    @common.setup_timeline
    def test_blur_of_older_projects(self):
        """Checks the blurs between clips meeting are still found."""
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)
        with self.action_log.started("blur"):
            set_blur_fades(clip_a, fade_out=SECOND // 2)
            set_blur_fades(clip_b, fade_in=SECOND // 2)
        contact, = get_contacts(self.layer)
        self.assertEqual((contact.kind, contact.duration), (BLUR, SECOND))
        self.assertFalse(contact.overlapping)

        # Replaced by the blur which overlaps.
        with self.action_log.started("transition"):
            set_transition(contact, BLUR, SECOND)
        contact, = get_contacts(self.layer)
        self.assertEqual((contact.kind, contact.duration), (BLUR, SECOND))
        self.assertEqual(clip_b.props.start, 3 * SECOND)

    @common.setup_timeline
    def test_moving_away_removes_the_blur(self):
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)
        with self.action_log.started("transition"):
            set_transition(get_contacts(self.layer)[0], BLUR, SECOND)

        with self.action_log.started("move"):
            context = EditingContext(clip_b, self.timeline, GES.EditMode.EDIT_NORMAL,
                                     GES.Edge.EDGE_NONE, self.app)
            context.edit_to(6 * SECOND, self.layer)
            context.finish()
        # Apart, with a gap: no transition and no blur left.
        self.assertEqual(get_contacts(self.layer), [])
        self.assertEqual(get_blur_fades(clip_a).fade_out, 0)
        self.assertEqual(get_blur_fades(clip_b).fade_in, 0)

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

        # Shortening the first clip brings the second one back, keeping the
        # transition.
        with self.action_log.started("trim"):
            context = EditingContext(clip_a, self.timeline, GES.EditMode.EDIT_TRIM,
                                     GES.Edge.EDGE_END, self.app)
            context.edit_to(3 * SECOND, self.layer)
            context.finish()
        self.assertEqual(clip_a.props.duration, 3 * SECOND)
        self.assertEqual(self._get_transitions(), [(2, 1)])

        # Not shorter than twice the transition.
        with self.action_log.started("trim"):
            context = EditingContext(clip_a, self.timeline, GES.EditMode.EDIT_TRIM,
                                     GES.Edge.EDGE_END, self.app)
            context.edit_to(SECOND, self.layer)
            context.finish()
        self.assertEqual(clip_a.props.duration, 2 * SECOND)
        self.assertEqual(self._get_transitions(), [(1, 1)])

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

        # Extending the first clip pushes the second one, the fade to white
        # stays at the new end.
        with self.action_log.started("trim"):
            context = EditingContext(clip_a, self.timeline, GES.EditMode.EDIT_TRIM,
                                     GES.Edge.EDGE_END, self.app)
            context.edit_to(5 * SECOND, self.layer)
            context.finish()
        self.assertEqual(get_white_fades(clip_a).fade_out, SECOND // 2)
        self.assertEqual(get_contacts(self.layer)[0].kind, FADE_TO_WHITE)
        self.action_log.undo()

        # Shortening it, the clips lose contact and the transition goes away.
        with self.action_log.started("trim"):
            context = EditingContext(clip_a, self.timeline, GES.EditMode.EDIT_TRIM,
                                     GES.Edge.EDGE_END, self.app)
            context.edit_to(3 * SECOND, self.layer)
            context.finish()
        self.assertEqual(get_white_fades(clip_a).fade_out, 0)
        self.assertEqual(get_white_fades(clip_b).fade_in, 0)
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

    def _get_posx_keyframes(self, clip):
        source = clip.find_track_element(None, GES.VideoSource)
        binding = source.get_control_binding("posx")
        if not binding:
            return None
        return {round(value) for unused_timestamp, value in get_keyframes(binding.props.control_source)}

    @common.setup_timeline
    def test_deleting_a_clip_removes_its_transitions(self):
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)
        clip_c = self._add_clip(8)
        contact_ab, contact_bc = get_contacts(self.layer)
        with self.action_log.started("transition"):
            set_transition(contact_ab, FADE_TO_BLACK, SECOND)
        with self.action_log.started("transition"):
            set_transition(contact_bc, PUSH, SECOND, RIGHT)
        self.assertEqual(len(self._get_posx_keyframes(clip_c)), 2)

        self.timeline_container.timeline.selection.select([clip_b])
        self.timeline_container.delete_action.activate(None)
        self.assertNotIn(clip_b, self.layer.get_clips())
        # No half transitions are left on the other clips.
        self.assertEqual(get_image_fades(clip_a).fade_out, 0)
        # Its position does not move anymore.
        self.assertEqual(len(self._get_posx_keyframes(clip_c)), 1)
        self.assertEqual(clip_c.props.start, 7 * SECOND)

        self.action_log.undo()
        self.assertEqual([contact.kind for contact in get_contacts(self.layer)],
                         [FADE_TO_BLACK, PUSH])

    @common.setup_timeline
    def test_purging_video_removes_neighbour_transitions(self):
        """Removing a library video clears both shared ends, undoably."""
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("1sec_simpsons_trailer.mp4"))
        clip_b = self.layer.add_asset(asset, 4 * SECOND, 0, SECOND, GES.TrackType.UNKNOWN)
        clip_c = self._add_clip(5)
        with self.action_log.started("transitions", toplevel=True):
            contact_ab, contact_bc = get_contacts(self.layer)
            set_transition(contact_ab, BLUR, SECOND // 2)
            set_transition(contact_bc, FADE_TO_WHITE, SECOND // 2)
            set_image_fades(clip_a, fade_in=SECOND // 4)
        self.assertGreater(get_blur_fades(clip_a).fade_out, 0)
        with self.action_log.started("assets-removal", toplevel=True):
            self.timeline_container.purge_asset(asset.props.id)
        self.assertNotIn(clip_b, self.layer.get_clips())
        self.assertEqual(get_blur_fades(clip_a).fade_out, 0)
        self.assertEqual(get_image_fades(clip_a).fade_out, 0)
        self.assertEqual(get_image_fades(clip_a).fade_in, SECOND // 4)
        self.assertEqual(get_white_fades(clip_c).fade_in, 0)
        self.action_log.undo()
        self.assertIn(clip_b, self.layer.get_clips())
        self.assertEqual([contact.kind for contact in get_contacts(self.layer)],
                         [BLUR, FADE_TO_WHITE])
        self.action_log.redo()
        self.assertEqual(get_blur_fades(clip_a).fade_out, 0)
        self.assertEqual(get_white_fades(clip_c).fade_in, 0)

    @common.setup_timeline
    def test_moving_a_clip_away_removes_its_fades(self):
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)
        self._add_clip(9)
        contact, = get_contacts(self.layer)
        with self.action_log.started("transition"):
            set_transition(contact, FADE_TO_WHITE, SECOND)

        # Moved after another clip, the clips are not neighbors anymore.
        with self.action_log.started("move"):
            context = EditingContext(clip_b, self.timeline, GES.EditMode.EDIT_NORMAL,
                                     GES.Edge.EDGE_NONE, self.app)
            context.edit_to(14 * SECOND, self.layer)
            context.finish()
        self.assertEqual(get_white_fades(clip_a).fade_out, 0)
        self.assertEqual(get_white_fades(clip_b).fade_in, 0)
        self.assertEqual(clip_a.get_top_effects(), [])

        self.action_log.undo()
        self.assertEqual(get_contacts(self.layer)[0].kind, FADE_TO_WHITE)

    @common.setup_timeline
    def test_separating_clips_removes_their_transition(self):
        self._wait_until_project_loaded()
        clip_a = self._add_clip(0)
        clip_b = self._add_clip(4)
        contact, = get_contacts(self.layer)
        with self.action_log.started("transition"):
            set_transition(contact, FADE_TO_BLACK, SECOND)

        # Moved a little, with a gap between the clips.
        with self.action_log.started("move"):
            context = EditingContext(clip_b, self.timeline, GES.EditMode.EDIT_NORMAL,
                                     GES.Edge.EDGE_NONE, self.app)
            context.edit_to(5 * SECOND, self.layer)
            context.finish()
        self.assertEqual(get_image_fades(clip_a).fade_out, 0)
        self.assertEqual(get_image_fades(clip_b).fade_in, 0)


class ImageTransitionsTest(common.TestCase):
    """Tests for the transitions with images, GES draws the wipes wrong."""

    def _add_image(self, start):
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("flat_colour1_640x480.png"))
        return self.layer.add_asset(asset, start * SECOND, 0, 4 * SECOND, GES.TrackType.UNKNOWN)

    @common.setup_timeline
    def test_push_with_images(self):
        self._wait_until_project_loaded()
        image_a = self._add_image(0)
        image_b = self._add_image(4)
        contact, = get_contacts(self.layer)
        self.assertFalse(wipes_work(image_a, image_b))

        for direction in (LEFT, TOP, BOTTOM, RIGHT):
            with self.action_log.started("transition"):
                contact = set_transition(get_contacts(self.layer)[0], PUSH, SECOND, direction)
            # No wipe, the second image appears while coming in.
            self.assertEqual(get_video_transition(image_b).get_transition_type(),
                             GES.VideoStandardTransitionType.FADE_IN)
            contact, = get_contacts(self.layer)
            self.assertEqual((contact.kind, contact.direction), (PUSH, direction))

        # Undoing gives back the previous direction.
        self.action_log.undo()
        contact, = get_contacts(self.layer)
        self.assertEqual((contact.kind, contact.direction), (PUSH, BOTTOM))

    @common.setup_timeline
    def test_videos_smaller_than_the_frame(self):
        self._wait_until_project_loaded()
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("one_fps_numeroted_blue.mkv"))
        clip_a = self.layer.add_asset(asset, 0, 0, 4 * SECOND, GES.TrackType.UNKNOWN)
        clip_b = self.layer.add_asset(asset, 4 * SECOND, 0, 4 * SECOND, GES.TrackType.UNKNOWN)
        # GES draws the wipes small in a corner.
        self.assertFalse(wipes_work(clip_a, clip_b))
        contact, = get_contacts(self.layer)
        with self.action_log.started("transition"):
            set_transition(contact, PUSH, SECOND, LEFT)
        element = get_video_transition(clip_b)
        self.assertEqual(element.get_transition_type(), GES.VideoStandardTransitionType.FADE_IN)

        # The blurred fill makes the whole frame, the wipe works.
        with self.action_log.started("fill"):
            set_blur_fill(clip_a, True)
            sync_pushes(self.layer)
        self.assertTrue(wipes_work(clip_a, clip_b))
        self.assertEqual((element.get_transition_type(), element.is_inverted()), PUSH_WIPES[LEFT])
        contact, = get_contacts(self.layer)
        self.assertEqual((contact.kind, contact.direction), (PUSH, LEFT))

        # The fill of the second clip is already slid, it is uncovered
        # where it comes in.
        with self.action_log.started("fill"):
            set_blur_fill(clip_b, True)
            sync_pushes(self.layer)
        self.assertEqual((element.get_transition_type(), element.is_inverted()), WIPES[LEFT])
        contact, = get_contacts(self.layer)
        self.assertEqual((contact.kind, contact.direction), (PUSH, LEFT))

    @common.setup_timeline
    def test_saved_types(self):
        self._wait_until_project_loaded()
        asset = GES.UriClipAsset.request_sync(common.get_sample_uri("one_fps_numeroted_blue.mkv"))
        clip_a = self.layer.add_asset(asset, 0, 0, 4 * SECOND, GES.TrackType.UNKNOWN)
        clip_b = self.layer.add_asset(asset, 4 * SECOND, 0, 4 * SECOND, GES.TrackType.UNKNOWN)
        contact, = get_contacts(self.layer)
        with self.action_log.started("transition"):
            set_transition(contact, SOFT_WIPE, SECOND, RIGHT)
        element = get_video_transition(clip_b)
        transition_clip = element.get_parent()
        self.assertEqual(transition_clip.props.vtype, GES.VideoStandardTransitionType.CROSSFADE)

        # The project saves the type of the clip.
        sync_saved_types(self.timeline)
        self.assertEqual(transition_clip.props.vtype, WIPES[RIGHT][0])
        self.assertEqual((element.get_transition_type(), element.is_inverted()), WIPES[RIGHT])
        self.assertEqual(element.get_border(), SOFT_WIPE_BORDER)
        contact, = get_contacts(self.layer)
        self.assertEqual((contact.kind, contact.direction), (SOFT_WIPE, RIGHT))


class DurationTest(common.TestCase):
    """Tests for changing the duration of the transitions."""

    @common.setup_timeline
    def test_change_duration(self):
        self._wait_until_project_loaded()
        for sample in ("flat_colour1_640x480.png", "one_fps_numeroted_blue.mkv"):
            for kind in (PUSH, DISSOLVE):
                for layer_clip in self.layer.get_clips():
                    self.layer.remove_clip(layer_clip)
                asset = GES.UriClipAsset.request_sync(common.get_sample_uri(sample))
                clip_a = self.layer.add_asset(asset, 0, 0, 4 * SECOND, GES.TrackType.UNKNOWN)
                clip_b = self.layer.add_asset(asset, 4 * SECOND, 0, 4 * SECOND, GES.TrackType.UNKNOWN)
                for duration in (1, 2, 0.5, 1.5):
                    with self.action_log.started("transition"):
                        set_transition(get_contacts(self.layer)[0], kind, int(duration * SECOND), RIGHT)
                    contact, = get_contacts(self.layer)
                    self.assertEqual((contact.kind, contact.duration), (kind, int(duration * SECOND)),
                                     (sample, kind, duration))
                    self.assertEqual(clip_b.props.start, int((4 - duration) * SECOND), (sample, kind, duration))
                    self.assertEqual(clip_a.props.duration, 4 * SECOND)
