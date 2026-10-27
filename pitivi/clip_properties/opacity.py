"""Simple clip opacity, independent of image fades."""
from gettext import gettext as _

from gi.repository import GES
from gi.repository import Gtk

from pitivi.undo.base import FinalizingAction
from pitivi.utils.ui import PADDING
from pitivi.utils.ui import SPACING

OPACITY_EFFECT = "alpha name=spl_opacity method=set"


def get_opacity_effect(clip):
    return next((effect for effect in clip.get_top_effects()
                 if is_opacity_effect(effect)), None)


def is_opacity_effect(effect):
    return effect.props.bin_description == OPACITY_EFFECT


class RefreshOpacityAction(FinalizingAction):
    """Commit effect additions/removals, refresh live property changes."""

    def __init__(self, pipeline, clip):
        self.pipeline = pipeline
        self.clip = clip
        self.effect = get_opacity_effect(clip)

    def do(self):
        effect = get_opacity_effect(self.clip)
        if effect != self.effect:
            self.pipeline.commit_timeline()
        else:
            # Updating alpha is live during playback. When paused, seek to
            # redraw the current frame without rebuilding the timeline.
            self.pipeline.flush_seek()
        self.effect = effect


class OpacityProperties(Gtk.Expander):
    """A percentage control which preserves the source's fade keyframes."""

    def __init__(self, app):
        super().__init__(label=_("Opacity"), expanded=True)
        self.app = app
        self.source = None
        self._updating = False
        self._handlers = []
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PADDING)
        box.props.border_width = SPACING
        self.adjustment = Gtk.Adjustment(value=100, lower=0, upper=100,
                                         step_increment=1, page_increment=10)
        self.scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL,
                               adjustment=self.adjustment, digits=0, hexpand=True)
        self.scale.connect("format-value", lambda scale, value: "%d %%" % round(value))
        box.pack_start(self.scale, False, False, 0)
        self.add(box)
        box.show_all()
        self.adjustment.connect("value-changed", self._changed_cb)

    def set_source(self, source):
        for obj, handler in self._handlers:
            obj.disconnect(handler)
        self._handlers = []
        self.source = source
        if source:
            clip = source.get_parent()
            for signal in ("child-added", "child-removed", "deep-notify"):
                self._handlers.append((clip, clip.connect(signal, self._refresh)))
            self._refresh()
        self.set_visible(bool(source))

    def _refresh(self, *unused):
        if self._updating or not self.source:
            return
        effect = get_opacity_effect(self.source.get_parent())
        value = effect.get_child_property("alpha")[1] if effect else 1
        self._updating = True
        try:
            self.adjustment.set_value(value * 100)
        finally:
            self._updating = False

    def _changed_cb(self, adjustment):
        if self._updating or not self.source:
            return
        clip = self.source.get_parent()
        pipeline = self.app.project_manager.current_project.pipeline
        self._updating = True
        try:
            with self.app.action_log.started(
                    "set opacity", toplevel=True, mergeable=True,
                    finalizing_action=RefreshOpacityAction(pipeline, clip)):
                effect = get_opacity_effect(clip)
                if effect is None:
                    effect = GES.Effect.new(OPACITY_EFFECT)
                    if not clip.add(effect):
                        raise RuntimeError("Cannot add opacity effect")
                effect.set_child_property("alpha", adjustment.get_value() / 100)
        finally:
            self._updating = False
        self._refresh()
