"""Unified CGB command contract (D10) + Collect (D11).

The reusable front-end every command uses to drive the viewport's Construction
Geometry Builder — replacing the near-identical CGB-button / seed-on-reclick /
finish-dispatch / controls-gating blocks that were triplicated across
``origin_window``, ``edit_bodies_window`` and ``main_window``.

Two consumption modes (the doc's *SF layer & command contract* section):

- **Construct** — :class:`CgbCommandBinder` + :class:`CgbSlotButton` turn viewport
  picks into ONE :class:`~.cgb_core.ConstructedEntity` (a Point/Axis/Plane/Basis/
  Frame), delivered via ``finished(ConstructResult)``.
- **Collect** — :class:`CollectCommand` returns the SET of picked model entities
  (faces / bodies / edges) for a command to act on (recolor / group / suppress),
  with NO construction. The main window exposes the delivery **seam**
  (``register_collect_handler``) on top of the Selection Filter's Multi mode.

numpy/PySide6 only (headless-testable with a stub CG/SF).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMenu, QToolButton

from .cgb_core import (ConstructedEntity, POINT, AXIS, PLANE, BASIS, FRAME,
                       WANT_FULL, WANT_DIRECTION, WANT_ORIENTATION, want_label)

#: target → the ConstructedEntity.kind it must return (the finish kind-guard).
TARGET_KIND = {POINT: "point", AXIS: "axis", PLANE: "plane", BASIS: "basis",
               FRAME: "frame"}


# --------------------------------------------------------------------------- #
#  request / result types
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ConstructRequest:
    target: str                         # POINT|AXIS|PLANE|BASIS|FRAME
    key: str                            # host slot id ("vertex","basis","from_point"…)
    seed: Optional[ConstructedEntity] = None   # re-seed (edit an existing pick)


@dataclass(frozen=True)
class ConstructResult:
    key: str
    entity: Optional[ConstructedEntity]  # None == cancelled

    @property
    def provenance(self):
        return getattr(self.entity, "source_slots", None) if self.entity else None


# --------------------------------------------------------------------------- #
#  slot-pick store (source_slots round-trip for re-seed)
# --------------------------------------------------------------------------- #

class SlotStore:
    """Per-command store of each slot's ``source_slots`` (the original picks), so a
    re-clicked slot re-seeds with checks + hover restored."""

    def __init__(self) -> None:
        self._d: Dict[str, object] = {}

    def get(self, key: str):
        return self._d.get(key)

    def set(self, key: str, slots) -> None:
        self._d[key] = slots

    def clear(self, key: str) -> None:
        self._d.pop(key, None)

    def clear_all(self) -> None:
        self._d.clear()


# --------------------------------------------------------------------------- #
#  reusable CGB slot button
# --------------------------------------------------------------------------- #

class CgbSlotButton(QToolButton):
    """A checkable CGB-request button: click → ``pickRequested(key)``; right-click →
    Clear (``clearRequested(key)``); hover → ``hovered(key, on)``. Absorbs
    ``_make_slot_button`` + ``_install_clear_menu`` from the three windows."""

    pickRequested = Signal(str)
    clearRequested = Signal(str)
    hovered = Signal(str, bool)

    def __init__(self, key: str, label: str = "", icon=None, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        if label:
            self.setText(label)
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        if icon is not None:
            self.setIcon(icon)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.clicked.connect(lambda: self.pickRequested.emit(self.key))

    def _menu(self, pos) -> None:
        m = QMenu(self)
        m.addAction("Clear", lambda: self.clearRequested.emit(self.key))
        m.exec(self.mapToGlobal(pos))

    def enterEvent(self, e) -> None:  # noqa: N802
        self.hovered.emit(self.key, True)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.hovered.emit(self.key, False)
        super().leaveEvent(e)


# --------------------------------------------------------------------------- #
#  the finish-dispatch + gating binder
# --------------------------------------------------------------------------- #

class CgbCommandBinder(QObject):
    """Owns the ONE ``constructionFinished`` connection for a host command pane and
    dispatches results back to per-slot callbacks. Handles the seed-on-reclick fork,
    the kind-guard (a mode switch = cancel), ``source_slots`` round-trip, and the
    controls-gating (disable while a pick is pending)."""

    finished = Signal(object)   # ConstructResult

    def __init__(self, cg, set_controls_enabled: Optional[Callable[[bool], None]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._cg = cg
        self._set_controls = set_controls_enabled
        self._store = SlotStore()
        self._pending: Optional[tuple] = None      # (key, target)
        self._slots: Dict[str, tuple] = {}         # key -> (button, target, seed_getter, result_cb)
        self._bound = False

    # -- lifecycle --
    def bind(self) -> None:
        if not self._bound:
            self._cg.constructionFinished.connect(self._on_finished)
            self._bound = True

    def unbind(self) -> None:
        if self._bound:
            try:
                self._cg.constructionFinished.disconnect(self._on_finished)
            except Exception:  # noqa: BLE001
                pass
            self._bound = False

    @property
    def store(self) -> SlotStore:
        return self._store

    @property
    def pending(self) -> bool:
        return self._pending is not None

    @property
    def pending_key(self) -> Optional[str]:
        """The slot KEY currently being picked (None when idle) — lets a host tailor
        its preview to the pick in flight (e.g. the Origin editor hides its origin
        ball while the ORIENTATION is being edited)."""
        return self._pending[0] if self._pending is not None else None

    # -- registration --
    def register(self, button: CgbSlotButton, target: str,
                 seed_getter: Optional[Callable[[], Optional[ConstructedEntity]]] = None,
                 result_cb: Optional[Callable[[ConstructedEntity], None]] = None,
                 clear_cb: Optional[Callable[[], None]] = None,
                 want: str = WANT_FULL) -> None:
        """Bind ``button`` to a CGB request for ``target``.

        ``want`` declares WHICH PART of the entity this consumer uses —
        ``WANT_DIRECTION`` (an Axis consumed for its direction) or
        ``WANT_ORIENTATION`` (a Frame consumed for its axes). It does not change the
        construction; it lets the bar tell the user what will be used, and it is the
        single source for the button's caption (``cgb_core.want_label``)."""
        self._slots[button.key] = (button, target, seed_getter, result_cb, clear_cb,
                                   want)
        button.pickRequested.connect(self._request)
        button.clearRequested.connect(self._clear)

    # -- request / finish --
    def request(self, key: str) -> None:
        self._request(key)

    def _request(self, key: str) -> None:
        button, target, seed_getter, cb, clr, want = self._slots[key]
        seed = seed_getter() if seed_getter is not None else None
        # Tell the CGB what the consumer will USE, so the bar can say so (and a
        # position-only / direction-only request reads unambiguously).
        try:
            self._cg.set_want(want)
        except Exception:  # noqa: BLE001 - older/stub controllers ignore it
            pass
        if seed is not None:
            seed.source_slots = self._store.get(key)
            self._cg.load_entity(target, seed)
        else:
            self._cg.set_mode(target)
        self._pending = (key, target)
        if self._set_controls is not None:
            self._set_controls(False)

    def _on_finished(self, entity) -> None:
        if self._pending is None:
            return
        key, target = self._pending
        self._pending = None
        if self._set_controls is not None:
            self._set_controls(True)
        if entity is None:                              # cancel
            return
        if getattr(entity, "kind", None) != TARGET_KIND.get(target):
            return                                       # kind mismatch = cancel
        self._store.set(key, getattr(entity, "source_slots", None))
        button, tgt, sg, cb, clr, _want = self._slots[key]
        try:
            button.setChecked(True)
        except Exception:  # noqa: BLE001
            pass
        if cb is not None:
            cb(entity)
        self.finished.emit(ConstructResult(key, entity))

    def _clear(self, key: str) -> None:
        self._store.clear(key)
        button, tgt, sg, cb, clr, _want = self._slots[key]
        try:
            button.setChecked(False)
        except Exception:  # noqa: BLE001
            pass
        if clr is not None:
            clr()

    def cancel(self) -> None:
        """Esc / teardown: abort a pending pick (re-enable controls, cancel the CGB)."""
        if self._pending is not None:
            self._pending = None
            if self._set_controls is not None:
                self._set_controls(True)
        try:
            if self._cg.is_active():
                self._cg.cancel()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
#  Frame (Phase 5 / D5 composite) — a FULL local frame = origin + orientation
# --------------------------------------------------------------------------- #

class FrameBuilder(QObject):
    """The **Frame command** — a composite of two :class:`CgbCommandBinder` slots: an
    ORIGIN (a Point construction) and an ORIENTATION (a Basis construction), assembled
    into ONE ``ConstructedEntity(kind="frame", origin, xdir, ydir, normal)``.

    The orientation is OPTIONAL: with only an origin the frame is the identity/world
    basis at that point (the "Global" origin case Set-Origin/ReOrigin use). This is
    the reusable frame primitive; a host registers its own two ``CgbSlotButton``s
    (any keys) with a shared binder and passes them here. ``changed`` fires whenever
    either slot updates so the host can re-sync its Apply gate / triad preview.

    Elementwise math only (``np.cross``) — never ``@``/BLAS (GUI process)."""

    changed = Signal()

    def __init__(self, binder: "CgbCommandBinder",
                 origin_btn: CgbSlotButton, orientation_btn: CgbSlotButton,
                 parent=None) -> None:
        super().__init__(parent)
        self._binder = binder
        self._ok = origin_btn.key
        self._sk = orientation_btn.key
        self._origin: Optional[tuple] = None        # (x,y,z)
        self._basis: Optional[dict] = None          # {"x":[..], "z":[..]}
        binder.register(origin_btn, POINT, seed_getter=self._seed_origin,
                        result_cb=self._got_origin, clear_cb=self._clear_origin)
        binder.register(orientation_btn, BASIS, seed_getter=self._seed_orientation,
                        result_cb=self._got_orientation,
                        clear_cb=self._clear_orientation)

    # -- state --
    @property
    def origin(self) -> Optional[tuple]:
        return self._origin

    @property
    def basis(self) -> Optional[dict]:
        return self._basis

    def has_origin(self) -> bool:
        return self._origin is not None

    def has_orientation(self) -> bool:
        return self._basis is not None

    def is_valid(self) -> bool:
        """A frame needs an origin; orientation defaults to world (Global)."""
        return self._origin is not None

    def set_origin(self, pt) -> None:
        self._origin = None if pt is None else tuple(float(v) for v in pt)
        self.changed.emit()

    def set_basis(self, xdir, zdir) -> None:
        self._basis = ({"x": [float(v) for v in xdir], "z": [float(v) for v in zdir]}
                       if xdir is not None and zdir is not None else None)
        self.changed.emit()

    def frame_entity(self) -> Optional[ConstructedEntity]:
        if self._origin is None:
            return None
        if self._basis is not None:
            x = np.asarray(self._basis["x"], dtype=np.float64)
            z = np.asarray(self._basis["z"], dtype=np.float64)
        else:
            x = np.array([1.0, 0.0, 0.0]); z = np.array([0.0, 0.0, 1.0])
        y = np.cross(z, x)
        ent = ConstructedEntity("frame", origin=tuple(self._origin),
                                xdir=tuple(float(v) for v in x),
                                ydir=tuple(float(v) for v in y),
                                normal=tuple(float(v) for v in z))
        return ent

    def clear(self) -> None:
        self._origin = None
        self._basis = None
        self._binder.store.clear(self._ok)
        self._binder.store.clear(self._sk)
        self.changed.emit()

    # -- binder callbacks --
    def _seed_origin(self):
        return (ConstructedEntity("point", point=tuple(self._origin))
                if self._origin is not None else None)

    def _seed_orientation(self):
        if self._basis is None:
            return None
        x = np.asarray(self._basis["x"], dtype=np.float64)
        z = np.asarray(self._basis["z"], dtype=np.float64)
        e = ConstructedEntity("basis", normal=tuple(float(v) for v in z),
                              xdir=tuple(float(v) for v in x),
                              ydir=tuple(float(v) for v in np.cross(z, x)))
        if self._origin is not None:              # hover-marker fallback point
            e.origin = tuple(self._origin)
        return e

    def _got_origin(self, ent) -> None:
        if getattr(ent, "point", None) is not None:
            self._origin = tuple(float(v) for v in ent.point)
            self.changed.emit()

    def _got_orientation(self, ent) -> None:
        if ent.xdir is not None and ent.normal is not None:
            self._basis = {"x": [float(v) for v in ent.xdir],
                           "z": [float(v) for v in ent.normal]}
            self.changed.emit()

    def _clear_origin(self) -> None:
        self._origin = None
        self.changed.emit()

    def _clear_orientation(self) -> None:
        self._basis = None
        self.changed.emit()


# --------------------------------------------------------------------------- #
#  Collect (D11) — a SET of picked model entities, no construction
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CollectRequest:
    modes: object                        # Set[SelectMode]
    multi: bool = True
    face_kinds: object = None
    edge_kinds: object = None
    locked: bool = True


@dataclass(frozen=True)
class CollectResult:
    items: List[object]                  # List[SelectionItem] — the raw bag


class CollectCommand(QObject):
    """Own the Selection Filter in Multi mode and deliver the accumulated bag of
    picked ``SelectionItem``s to ``on_result`` — the Collect consumption mode a
    command (per-face recolor, link grouping, …) uses instead of the CGB."""

    def __init__(self, selection_filter, parent=None) -> None:
        super().__init__(parent)
        self._sf = selection_filter
        self._cb: Optional[Callable[[CollectResult], None]] = None
        self._active = False

    def begin(self, req: CollectRequest,
              on_result: Callable[[CollectResult], None]) -> None:
        # local import (SelectionSpec lives in the Qt SF module)
        from .selection_filter import SelectionSpec
        self._cb = on_result
        spec = SelectionSpec(modes=set(req.modes), multi=req.multi,
                             face_kinds=req.face_kinds, edge_kinds=req.edge_kinds,
                             locked=req.locked)
        self._sf.begin_owned(spec, self._on_pick)
        self._active = True

    def _on_pick(self, result) -> None:
        if self._cb is not None:
            self._cb(CollectResult(list(getattr(result, "items", []))))

    def end(self) -> None:
        if self._active:
            self._active = False
            try:
                self._sf.end_owned()
            except Exception:  # noqa: BLE001
                pass
