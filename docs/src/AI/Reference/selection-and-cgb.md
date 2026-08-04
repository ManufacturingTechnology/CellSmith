# Selection Filter & Construction Geometry Builder (SF/CGB)

The shared front-end every command uses to ask the user to pick geometry — the **Selection Filter (SF)** (Body / Face / Edge / Point picking with type + shape constraints) — and to turn those picks into a reference entity — the **Construction Geometry Builder (CGB)** (a Point / Axis / Plane / **Orientation** (basis) / **Frame** / Direction). Two consumption modes: **Collect** (return the set of picked model entities — recolor / group / suppress) and **Construct** (turn picks into one reference entity). Design spec (the feature-exposure contract): `../specs/construction_geometry_builder_definitions.md`. **Fully implemented; GL live-test pending** — the round-by-round build history lives in `../status.md`. Verify against `src/`; may lag.

## ⭐ Terminology — READ THIS FIRST
Two renames landed on this subsystem. The **user-facing** vocabulary below is now authoritative everywhere (UI labels, the spec, these docs); several **code tokens deliberately kept their old spelling** to avoid a wide rename, so the mechanics further down still say "Vertex"/"Basis" in identifiers. Map them as:

| Say / read | Code token | Notes |
|---|---|---|
| **Point** (the 0-D entity) | `SelectMode.POINT`, kind `"point"` | was `VERTEX` / `"vertex"`. "Vertex" now means ONLY a true B-Rep `TopoDS_Vertex` (the `End` snap target) |
| **Point Snap** `Edge`/`Tess`/`Free` | `PointSnapMode` | was `VertexSubMode` with `NONE`; `FREE` = an arbitrary un-snapped surface point. Deep fields `_vertex_types` / `vertex_sub` / `vertex_kind` keep the old spelling |
| **Frame** (origin + orthonormal axes) | target `BASIS`, kind `"basis"` | the CGB's 4th builder. The `basis` token predates the naming — **`kind == "basis"` IS a Frame** |
| **Orientation** | `BASIS` + `WANT_ORIENTATION` | a Frame consumed for its axes only — NOT a separate builder |
| **Direction** | `AXIS` + `WANT_DIRECTION` | an Axis consumed for its direction only — NOT a separate builder |
| **Composed Frame** | target `FRAME`, kind `"frame"` | an *arbitrary* Point construction + an *arbitrary* Frame construction (`FrameBuilder`), for when the origin must not be the construction's own anchor |

So: **4 CGB modes** in the bar (Frame · Plane · Axis · Point) serving **6 requestable entities** (+ Direction, Orientation). A button that requests one MUST be captioned with which (see *Request constraints*).

Both renames are **pure code renames — no persisted config / `.xbf` / stamp token encodes these**, so they are byte-neutral (no migration).

> **Historical note.** The `basis`/`frame` split exists because the spec originally defined *Basis* as direction-only (no position) and therefore had to build *Frame* by composing two builders. Every basis construction always computed an anchor, so the Frame builder existed all along — only its origin was documented as "for drawing only". Sections below written before that correction may still call it a Basis. **Known wart:** two kinds (`"basis"` and `"frame"`) now describe the same shape of entity, differing only in how the origin was obtained — collapsing them is a possible cleanup, deliberately not done (it would touch `TARGET_KIND`, every kind-guard, and `frame_matrix4`).

## Architecture — the feature-exposure engine
The SF/CGB is driven by a small Qt-free, **BLAS-free** engine (imported into the VTK process; all math elementwise — never `@` / `np.dot` / `np.linalg`; mesh least-squares lives only in a subprocess worker):
- **`cgb_core.py`** (Qt-free) — `ConstructedEntity` (kinds `point|axis|plane|basis|frame`), `SlotEntity`, the elementwise math (`_norm` / `_dot` / `_any_perpendicular` / `_rot_about` / `build_plane` / `build_axis` / `orthoframe`), target consts (`POINT/AXIS/PLANE/BASIS/FRAME`, `MAX_SLOTS`). `construction_geometry` re-imports them; `item_to_entity` stays in `construction_geometry` (needs `SelectMode`).
- **`cgb_features.py`** — the **feature-exposure model (Table A)**: `PROVIDES` maps each slot kind → the features it exposes, plus dispatch kind-sets `POINT_KINDS` / `LINE_KINDS` / `PLANE_KINDS` / `BASIS_KINDS`.
- **`cgb_recipes.py`** — `Recipe` / `CgbParams` + per-target `RECIPES` (precedence-ordered) + `resolve(target, ents, params)`. The `[impl]` recipes are lifted verbatim from the old hardcoded `_resolve_plane` / `_resolve_axis` / `_resolve_basis` and **reproduce them byte-for-byte** (golden regression harness); the old resolvers are RETAINED off the live path as the oracle. **Key payoff:** recipes read standard `SlotEntity` fields (`origin` / `direction` / `normal` / `point`), NOT the kind — so a new selection (a `Face[Cylinder]` axis, a `Datum[Plane]`) slots into every relevant recipe with NO new code. `[new]` recipes (Cramer `_solve3`, arity-guarded so they never shadow `[impl]`): midpoint, centroid, project-onto-line/plane, line∩plane, three-plane∩, axis-from-face-normal, axis=plane∩plane, mid-plane. `frame_matrix4(entity)` = the 4x4 of a Frame (Point origin + Orientation), matching `OriginFrame.matrix4`.
- **`cgb_command.py`** — the unified command contract: `ConstructRequest` / `ConstructResult`, `CgbSlotButton` (checkable + right-click Clear + hover), `CgbCommandBinder` (one `constructionFinished` connection, seed-on-reclick, kind-guard = mode-switch cancel, `source_slots` round-trip, controls-gating), `SlotStore`, `FrameBuilder` (composite Origin-Point + Orientation-Basis → `kind="frame"`), and Collect (`CollectRequest` / `CollectResult` / `CollectCommand`). The **Collect seam** = `main_window._on_filter_selection` routes a multi-select bag to a registered `register_collect_handler` (where per-face recolor / grouping wire in).
- **`cgb_filters.py`** — live per-row narrowing predicates (`distinct` / `not_parallel` / `parallel` / `off_line` / `off_axis` / `non_collinear`) + `slot_predicate`; threaded via `SelectionSpec.candidate_filter` + `SelectionFilter.set_owned_candidate_filter` (see the recipe-driven bar).
- **`fit_primitives.py` (+ `_worker`)** — recover an analytic primitive from a B-Rep or mesh face (see *Fit Primitives* below).

## Overview & interaction mechanics
Two horizontal menus at the BOTTOM of EVERY `ViewportPanel` (added to its
`QVBoxLayout` after the interactor — Construction Geometry above the Selection
Filter, filter bottom-most). The reusable front-end for asking the user to pick
geometry, with type/shape constraints. Modules: `src/gui/selection_filter.py`
(data model + `SelectionFilter` controller + `SelectionFilterBar`) and
`src/gui/construction_geometry.py` (`ConstructionGeometry` + `ConstructionBar` +
pure plane/axis math). Each `ViewportPanel` owns one `selection_filter` +
`construction_geometry` (built in `_build_selection_bars`); they are INERT until
`enable()`d (so constructing them never clobbers the main window's
`SelectionController` or an editor window's active tool).

**⭐ CGB-CONTROL CONVENTION (GLOBAL — apply to EVERY UI control that drives the
Construction Geometry Builder).** Any button that requests a CGB entity (a
Point / Frame / Orientation / Plane / Axis / Direction) MUST follow this pattern:
1. **Seed-on-reclick.** If the control ALREADY holds a value (pre-loaded OR
   user-defined), clicking it again SEEDS the CGB with that value as the starting
   point (`ConstructionGeometry.load_entity(mode, entity)`) so the user EDITS it;
   an empty control starts blank (`set_mode`). The CGB's own **Clear** button is
   how the user resets to scratch mid-pick. **A seeded value is PRE-POPULATED in
   the bar with a ✓, AND the ORIGINAL slot picks are RESTORED** so the E1/E2/E3
   buttons show the real geometry (checks + hover-highlight). `ConstructedEntity`
   carries `source_slots` (the `{slot: SlotEntity}` picks that built it); `accept()`
   attaches them, `load_entity` restores them into `_ents`. `_direct` still drives
   EXACT resolution (any gizmo/param edits baked into the value). A value built
   WITHOUT the CGB (a pre-loaded frame from the body's origin) has no picks → E1
   shows ✓ via the `_direct`/`filled(1)` fallback + the other slots show ✗, but no
   per-slot hover geometry. Callers persist `source_slots` per control (a
   `_cgb_slots` dict keyed by control) and re-attach on re-seed; Clear drops it.
2. **Right-click Clear.** The control has a right-click "Clear" context-menu item
   that removes its stored value and DEACTIVATES the button (unchecks it). Helper
   trio `_install_clear_menu(btn, key)` / `_clear_menu` / `_clear_cgb_button(key)`
   (duplicated in `edit_bodies_window.py` AND `origin_window.py`).
3. **Pre-load the useful side.** When a command has paired controls, pre-load the
   one that best serves as a starting point. Transform Orient pre-loads **To
   Orientation** with the body's current axes (From defaults to current at build → an
   untouched To is a no-op); Transform Move keeps **From Point** pre-loaded (a
   body point → "move this point to there").
Controls that follow it: ReOrigin Point/Orientation + Split Plane (Component
Editor), Transform From/To Orientation + From/To Point (Component Editor),
OriginWindow Point/Orientation (the main-window ReOrigin), the joint pane's Pick
Direction. A NEW CGB control MUST adopt all three.
**Slot markers + HOVER feedback:** EVERY filled slot shows a PERSISTENT small
ORANGE dot at its pick (`ConstructionGeometry._refresh_slot_markers` → the pooled
`ViewportPanel.set_slot_markers(points)`, sized `_marker_world_radius()*0.55` —
CLEARLY smaller than the 1.0× blue hover dot so hovering a slot is obvious), so the
user always sees where E1/E2/E3 are; refreshed
from `_update_preview` and cleared when the CGB ends. Hovering an E1/E2/E3 button
additionally shows the LARGER BLUE hover marker at that slot's key point (vertex
point / edge midpoint-or-center / face origin), via
`ConstructionGeometry.set_slot_hover(slot)` → `ViewportPanel.set_hover_point`
(bigger blue over smaller orange = which slot is which). The bar's slot buttons are
built by `_make_slot_button` (a `QToolButton` subclass whose `enterEvent`/
`leaveEvent` report hover). A no-picks PRE-LOADED value (e.g.
Transform To Orientation pre-loaded from the body's axes) has no slot geometry, so E1
hover FALLS BACK to the seed entity's own representative point (its
`point`/`origin`/`center`); the basis-seed callers attach `ent.origin` = the
body/frame origin so that fallback isn't blank. (A seed with no such point → no
marker, only the ✓.)

**⭐ GRIP-COLOR CONVENTION (GLOBAL).** EVERYWHERE a viewport has a COLORED,
draggable grip (a handle / rotation ring / offset arrow / axis tick) AND an
associated input UI element (spinbox/label), the UI element MUST carry a color
indicator (a ● bullet, via `construction_geometry.grip_label_html(text, rgb)`)
MATCHING its grip's color, so the user can tell which field drives which grip.
Applied: the CGB bar — angle **A** ● magenta (`_C_ROT_A` ring A), angle **B** ●
turquoise (`_C_ROT_B` ring B), **Offset** ● yellow (`_C_OFFSET` arrow), plane
**U/V** ● cyan (`_C_DEFAULT` edge handles), disc **Ø/C-U/C-V** ● cyan (rim/center
grip), axis **L−/L+** ● brown (`_C_AXIS_TICK` ticks); the Component Editor
**Transform** pane — Orient **about X/Y/Z** ● + Translate **X/Y/Z** ● recolored
LIVE (`_refresh_gizmo_label_colors` in `_sync_transform_enabled`) to match the
axis-colored rotation rings / offset arrows via the orientation-aware
`ViewportPanel.axis_color_for_dir` (so the ● tracks the grip even under a rotated
Source→Main orientation). A NEW grip+field pair MUST add a matching color
indicator.

**DATUM aid (construction reference; COMPLETE — headless + real-GL
probe-verified, GL live-test PENDING).** A datum FRAME — an origin
VERTEX, 3 AXIS lines (X/Y/Z), 3 PLANES (XY/YZ/ZX) — shown ONLY while the CGB is
active (`ConstructionGeometry.set_mode` → `_set_datum_active` →
`ViewportPanel.set_datum_active`), so a construction can reference it.
- **LOCAL ANCHOR** (`set_datum_origin(point)` / `_datum_origin`, default `(0,0,0)`;
  `datum_frame_origin()` reads it): the datum is anchored at a world point — the
  world/main origin in the main window + Source Editor, but the **Component Editor
  sets it to the edited component's LOCAL frame origin** (`_comp.transform[:3,3]`,
  in `_initial_load`) so the datum is a LOCAL reference, not the parent assembly's
  world origin. All datum geometry + pick helpers offset by `_datum_origin`; a
  constructed datum plane carries it as `plane_origin`. `clear()` keeps it (persists
  across reloads); `set_datum_origin` rebuilds + re-arms if active.
- A **corner QTreeWidget** (top-left of the viewport: Origin · Axes[X,Y,Z] ·
Planes[XY,YZ,ZX]) — the **checkbox governs ONLY normal viewport visibility +
pickability** (`set_datum_visible`; **default ALL unchecked/hidden** — the user
shows what they want). **HOVER +
CLICK on a tree row work REGARDLESS of the checkbox** (an unchecked element is still
hoverable/selectable from the tree): CLICKING a row picks that element into the CGB
(`itemClicked` → `_on_datum_tree_clicked` → `on_datum_key_pick` →
`SelectionFilter._vp_datum_key_pick` → `datum_pick_by_key`, gated on the active mode
ONLY — origin↔Vertex/axis↔Edge/plane↔Face, NOT on visibility; a checkbox-toggle
click is skipped via the `_datum_check_toggled` flag since `itemChanged` fires
first); HOVERING a row highlights it (`itemEntered` + `setMouseTracking` →
`_on_datum_tree_hover` → `datum_hover_key`: origin→blue dot, axis/plane→
`set_datum_hover`, which FORCE-SHOWS a hidden actor (+its cone) while hovered and
restores the checkbox visibility on leave — `_datum_apply_hover`; a
`_DatumTree.leaveEvent` clears it). The VIEWPORT pick paths
(`datum_origin_point`/`datum_edge_infos`/`datum_axis_hit`/`datum_plane_hit`) still
gate on visibility (unchecked = not drawn/pickable in 3D). The tree is a clean corner PANEL —
no frame/border, no scrollbars, no selection highlight (`_ensure_datum_tree`),
sized in `_position_datum_tree` to fit ALL 9 rows + labels (no scroll), with a
low-alpha `rgba(28,32,40,140)` background. **GOTCHA (cost a live "everything
broke" report): do NOT `setAttribute(WA_TranslucentBackground)` on this overlay —
over the native OpenGL viewport a translucent Qt child renders INVISIBLE ("the
tree disappeared"), and an invisible datum during a CGB command (where left-click
is a pick, not selection) reads as "all the mouse buttons are messed up." Use a
low-alpha stylesheet background (composites against the widget itself) instead.**
- **ORIENTED + AXIS-COLORED (matches the gizmo).** The datum is DRAWN + PICKED in
  the viewport's EXPORT orientation (`_oriented(d)` = axis i along `_orient` ROW i,
  EXACTLY like the origin triad `_triad_poly` + corner gizmo) — so under the
  Component/Source Editor's Source→Main override the datum's Y points where the
  gizmo's Y points (was fixed world axes → "Y pointed the wrong way"). Axes are
  AXIS-COLORED (X red / Y green / Z blue via `_AXIS_RGB`), planes by their NORMAL's
  axis (XY→blue, YZ→red, ZX→green), the origin a neutral dot; each axis gets a small
  same-color +tip cone. `set_orientation` REBUILDS the datum (+ re-arms the SF) when
  it's active. `datum_edge_infos`/`datum_axis_hit`/`datum_plane_hit`/the plane
  locator all use the oriented dirs, so picks return the ORIENTED direction (→ the
  construction is in the main/world frame after the source-frame bake).
- **HOVER** (over-model AND off-model): the origin shows the blue hover DOT (via the
  vertex snap / `_hover_datum` returning its point); an axis/plane recolors blue via
  `set_datum_hover(key)`. `SelectionFilter._unified_hover` resolves the datum
  (`_hover_datum` → `_resolve_datum`) when nothing model won, and the viewport's
  hover observer calls the SF hover with `None` when the cursor is off the model but
  the datum is up, so a datum floating in empty space still highlights.
- **Drawing is LAZY** (`_build_datum_actors` computes the plane NORMALS — needed for
  picking regardless of what's drawn — but creates NO actor for a HIDDEN element;
  `_ensure_datum_actor(key)` builds the actor(s) — origin sphere / oriented axis
  line + `+`tip cone / translucent plane quad, `_datum_base_color` per key for hover
  revert — ON DEMAND when the checkbox is checked (`set_datum_visible`) or the row
  is hovered (`_datum_apply_hover`), with `render=False`. **Drawing everything at CGB
  activation then hiding the unchecked made all elements FLASH on load** — with the
  all-off default, lazy creation means nothing is built/drawn until the user checks
  or hovers. `_datum_reset_clip` (`ResetCameraClippingRange`) runs when an element is
  first shown so a far-reaching datum renders in full without a rotate.
- **PICK HELPERS** the SF consults: `datum_origin_point()` (origin as a vertex
  candidate | None when hidden), `datum_edge_infos()` (visible axes as
  `edge_pick.EdgeInfo` lines + polylines), `datum_plane_hit(x,y)` /
  `datum_plane_hit_at_cursor()` (ray∩ the visible plane quads →
  `(plane_key, world_pt, normal, ray_t)`), `world_distance_to_camera(p)` (depth
  compare, elementwise).
- **SF INTEGRATION (DONE):** origin → `SelectionFilter._snapped_vertex` adds
  `_datum_origin_candidate()` as a gated vertex snap (Vertex mode); axes →
  `_append_datum_edges(poly, infos)` merges the visible axes into the pickable
  edge layer in `_arm_edge_layer` (re-indexed after the model edges; works with
  no model edges too), so Edge / Vertex→Edge pick them; planes →
  `_resolve_face(pt)` composes the model face with `datum_plane_hit_at_cursor()`,
  the NEARER-camera one winning (a datum FACE item carries
  `plane_origin=(0,0,0)`+`plane_normal`), wired into `_resolve_point` +
  `_unified_hover`. **Re-arm:** `ViewportPanel._notify_datum_changed()` →
  `SelectionFilter.on_datum_changed()` (→ `_arm`) fires on datum activate/deactivate
  AND on an AXIS visibility toggle, so a newly-shown axis joins the edge layer
  (planes/origin are queried live, no re-arm). All SF datum calls are try/except-
  guarded so a stub viewport (offscreen) is a clean no-op.
- **OFF-MODEL picking (the datum floats BEYOND the model — the common case):** a
  left-click that misses the model surface routes through
  `ViewportPanel._pick_display` → `_try_datum_click(x,y)` → `on_datum_click` →
  `SelectionFilter._vp_datum_click` → **`_resolve_datum(x,y)`**, a SCREEN-SPACE
  resolver (project the origin for Vertex / **`vp.datum_axis_hit(x,y)`** for Edge /
  `datum_plane_hit(x,y)` for Face → nearest within the 15px gate, Vertex>Edge>Face)
  that needs NO model surface. So origin/axes/planes are pickable anywhere on
  screen, not just where they overlap the model. **`datum_axis_hit` uses an EXACT
  line-to-ray closest point** (`_closest_point_on_line_to_ray`, BLAS-free), NOT
  polyline sampling — sampling was DENSE on a small Component-Editor body but SPARSE
  on the full model (the datum spans ~0.6·bbox), so axis clicks missed between
  samples ("axes selectable in a command but not when I start the CGB manually").
  The closest point is CLAMPED to the DRAWN segment `[-s·dv, +s·dv]` so hovering the
  theoretical axis line BEYOND the drawn tips does NOT trigger. Over-model picks
  still use the surface-ray paths above. Each visible axis draws a small
  axis-colored **cone arrowhead** at its +tip (direction cue; `_datum_actors`
  key `{axis}_cone`, follows its axis's visibility) → up to 10 actors when all are
  shown (created LAZILY per the Drawing bullet — 0 at CGB activation).
  **Mesh:** `_slot_spec` KEEPS Face in PLANE mode even without B-rep (the analytic
  datum plane stays pickable; a model Tess face is harmlessly ignored by
  `item_to_entity`). **Render:** `set_datum_active` calls
  `renderer.ResetCameraClippingRange()` after building the actors — the datum
  extends ~0.6·bbox beyond the model, so without it the axes/planes only PARTIALLY
  render until a rotate resets the clip range. Verified: `sf_datum_test.py` (15
  headless) + `probe_datum.py` (22) + `probe_datum_offmodel.py` (4 real-GL: routing
  + origin/axis fill) + `probe_datum_cycle.py` (11: mouse/select intact around a CGB).

**User datums (persistent, named — additive to the fixed aid above).** Beyond the fixed global-origin aid, the CGB has a PARALLEL **user-datum layer**: `ViewportPanel.set_datum_records` / `datum_records` + `_user_datums` / `_rebuild_user_datum_actors` draw persistent named datums (point→sphere, axis→centerline, plane→quad, **basis→triad**; visibility-gated, independent of the fixed aid), and `datum_pick_by_key("user:<id>")` picks them (`_user_datum_pick` returns vertex / edge / face / **basis** descriptors). The SF's `_vp_datum_key_pick` gained a "basis" branch → a FACE `SelectionItem` carrying `basis_xdir`; `item_to_entity` maps that → a `datum_basis` SlotEntity, and **`datum_basis` chaining** works via `cgb_features.BASIS_KINDS` + a `basis_from_datum` recipe (a datum frame IS the basis; flip negates X). A **`DatumsPanel`** (`src/gui/datums_panel.py`) — a main-window dock (list + Add / Rename / Delete + visibility checkboxes) — is loaded/saved via `store.get/set_datum_map(active_model)`, pushed to `viewport.set_datum_records`, refreshed on `_commit_model`; **Add** arms the CGB (Point / Axis / Plane / Orientation) → a `DatumEntity`.
**⭐ CLICKING a panel row PICKS that datum into the active command** (`DatumsPanel.pickRequested` → `main_window._on_datum_pick` → `viewport.on_datum_key_pick("user:<id>")` → the chain above) — the same affordance the fixed corner datum tree has. This was the **missing trigger**: the whole `datum_pick_by_key("user:…")` pipeline was built but NOTHING called it (only the fixed corner tree ever fired `on_datum_key_pick`), so a user datum was unpickable from the panel — reported live as "I can't click a Datum plane while using Measure". A checkbox toggle does NOT also pick (`_check_toggled` guard, mirroring the corner tree's `_datum_check_toggled`); visibility ≠ pickability (a hidden datum still picks); the SF mode-gate makes an unusable datum a harmless no-op.
**❗ Still missing:** user datums are NOT hit-testable in the 3D VIEWPORT — their actors are created `pickable=False`, and the SF's viewport resolvers (`datum_origin_point` / `datum_edge_infos` / `datum_plane_hit` / `_resolve_datum`) still only consult the FIXED six. Picking them requires the panel. **Config:** `geometry_edits.DatumEntity` (kind point/axis/plane/basis) + `load/dump_datum_map` + `ModelConfigStore.get/set_datum_map`; the per-model `datums` map is **EXCLUDED from `source_to_main_inputs` + `has_geometry_edits`** (references, like joints → byte-neutral, no rebuild trigger).
**⭐ BODY-FILTER PATTERN (GLOBAL — for scoping construction geometry + selection
to a subset of bodies).** A command can restrict the CGB/SF's VISIBLE effects to a
set of component ids, updated LIVE while the CGB/SF are active/owned, and cleared
to restore the whole model — cascading **command → CGB → SF → viewport**:
- `SelectionFilter.set_body_filter(cids)` / `clear_body_filter()` store `_body_filter`
  (a set | None). It restricts (a) the FORCED tess-edge overlay (the SF passes
  `only_cids=self._body_filter` to `ViewportPanel.set_tess_edges_visible(visible,
  only_cids=...)`, which wireframes ONLY those bodies' cells via the per-component
  cell ranges), and (b) the pickable edge layer (`_leaves()` includes only the
  filter). Applied live: `set_body_filter` re-emits the restricted overlay even
  while forced (the `_set_tess_overlay` idempotent guard won't). Cleared on
  `enable(False)` + `set_assembly` so it never leaks.
- `ConstructionGeometry.set_body_filter(cids)` / `clear_body_filter()` = thin
  pass-throughs into the owned SF (the canonical entry point for a command).
- **Component Editor wiring:** `_apply_command_visibility` (the single choke point
  every command calls before its CGB forces the overlay — Split/Origin at start,
  Transform via `_begin_xform_pick`, and `_on_visibility` mid-command) links the
  **Visibility** toggle: **Target Body → `cg.set_body_filter({f"body::{target}"})`**,
  **All Bodies → `cg.clear_body_filter()`**. `_end_command` clears it. This FIXES
  the tess-edge overlay showing on ALL bodies under Target Body. (Complements the
  existing `set_edge_exclude` for the pick layer; both narrow to the target.)
- A NEW place that needs body-scoped construction geometry / selection uses the
  SAME cascade: `cg.set_body_filter(...)` / `clear_body_filter()`.

- **Selection Filter** (`SelectionFilter(QObject)`): a **"Quantity" group** (Single /
  **Multi** — Multi is the DEFAULT; renamed from "Select", item 11) + modes **Body**
  (default) / **Face** / **Edge** /
  **Vertex** as TOGGLES (a `set` — `set_mode_active`/`is_mode_active`/`is_body_only`,
  not one exclusive `mode`), stacked in a **2×2 GRID** (Body/Face over Edge/Vertex).
  The bar title is the two-line, CENTER-aligned `"Selection\nFilter"`. The
  **Quantity** group (Single/Multi) and the **Face** group's B-Rep/Tess buttons are
  each stacked VERTICALLY. (The **Reset** button was
  REMOVED — `SelectionFilter.reset()` stays for request-restore + the main-window Esc
  ladder, but the user-facing bar button is gone; `_on_reset` deleted.) **Body is
  mutually exclusive with the Face/Edge/Vertex group** (select a Body, OR any
  combination of Face/Edge/Vertex); F/E/V toggle independently among themselves; the
  set is never empty (falls back to Body). Every bar button (both bars) carries a
  small QPainter-drawn icon from **`src/gui/sel_icons.py`** (`make_icon(name)`,
  cached; `ToolButtonTextBesideIcon`) — item 23. Each
  mode has an **always-visible titled group** (Body/Face/Edge/Vertex), ENABLED for
  the active modes and greyed otherwise — options never disappear. When several F/E/V
  are active a pick RESOLVES to the most-specific entity under the cursor by a
  no-select FALL-THROUGH priority **Vertex > Edge > Face > Body** (item 16 — if
  Vertex doesn't catch, try Edge, then Face): `_vp_edge` checks a snapped vertex
  BEFORE committing the edge; `_vp_point` (edge locator missed) resolves Vertex >
  Face > Body; `_unified_hover` previews the same chain. Both the Vertex snap gate
  and the Edge gate are display-pixel (screen-space) — 15 px each
  (`_VERTEX_GATE_PX` / `_EDGE_PICK_GATE_PX`). While snapping to a vertex ON an edge,
  that edge shows a **dim 50%-alpha courtesy highlight** (`highlight_pick_edge(idx,
  dim=True)`, `_EDGE_DIM_ALPHA=128`) so it reads differently from a full-opacity
  edge-selection hover. **In Point→Edge mode the courtesy cue ALSO shows when
  nothing snapped** — mid-span on a long edge every End/Mid/Center is past the 15px
  gate, which used to leave the hover with NO feedback at all; `_unified_hover` now
  remembers the `edge_at_cursor()` hit as `courtesy_edge` and applies it at the end
  **only if nothing more specific resolved** (no dot / face / cell / datum / body),
  so it can never mask a Face or Body hover. (body-ONLY keeps the classic on_pick +
  tree path; an F/E/V set arms edge_pick for Edge + point mode for the rest.)
  **SELECTED (orange) overlay for non-Body picks:** `_emit` →
  `_refresh_selection_visuals` pushes the picked Edge indices to
  `ViewportPanel.set_selected_edges` and the picked Points to `set_selected_points`
  (orange, `_marker_world_radius()*0.85` — just inside the 1.0× blue hover dot;
  hover line width 7 > selected 4 so hovering a selected edge still reads as hover).
  Before this, a non-Body pick had NO persistent visual at all — only the status-bar
  readout — so clicking an edge or point looked like nothing happened. It is
  **SKIPPED while a command owns/requests the bar** (the CGB draws its own orange
  slot markers there; doubling them up would fight), and cleared by
  `_clear_selection_visuals` from `_disarm_special` (mode switch / disarm) + the
  not-enabled `_arm` branch.
  Face sub-modes **B-Rep** (pick a triangle → its whole source face, filtered by
  surface kind Flat/Cylinder/**Other** — all three on by default — in a "B-Rep"
  sub-group) or **Tessellation** (one triangle); Edge filters Line/Arc/**Other**
  (all on by default — item 29) (an
  "Edge" group); Vertex sub-modes **Edge** (snap **End**point/Mid/arc-Center —
  End/Mid/Center ALL apply to arcs too, not just Center. **Hovering an ARC snaps
  its CENTER** (`_arc_center_hover` fallback in `_snapped_vertex`): the center
  sits a full RADIUS from the curve, so it can't pass the point-gate that
  End/Mid use — instead, when no End/Mid is within the gate, the fallback gates
  on proximity to the arc CURVE (nearest point on the analytic circle from
  `EdgeInfo.center`/`axis`/`radius`, screen-gated) and returns the center. So
  End/Mid win when near, else the arc's center; requires Vertex→Edge + 'center'
  on + the Arc edge-kind armed. Analytic-circle only (NO `edge_pick_mode`
  dependency — that's off in Vertex-only mode); "hover near the center POINT
  →center" still works via the point pass. the "Edge Type" edge-kind
  sub-group — Line/Arc/**Other**, all on by default (item 22) — comes BEFORE the
  "Edge Vertex" vertex-type sub-group, whose End/**Mid**/Center are all on by
  default too — item 27) and **Tessellation**
  (nearest mesh vertex). **Edge + Tess are INDEPENDENT toggles, stacked
  VERTICALLY** (like Face→B-Rep/Tess): at most one is active (the single
  `_vertex_sub` enum keeps them mutually exclusive — selecting one makes `_sync`
  uncheck the other), but **BOTH can be off**, which is `VertexSubMode.NONE` — no
  snapping, an ARBITRARY surface point (`_snapped_vertex` returns the raw point
  ungated). This DROPPED the former explicit **None** button (its behaviour is now
  "both off"); the click handler maps an active-button re-click → NONE. NONE is
  still never a CGB default — a user-only state. ("B-Rep", not "NURBS", for FACE sub-mode — most CAD faces
  are planes/cylinders, not spline surfaces. The Vertex "Edge" sub-mode is
  `VertexSubMode.EDGE`.) **Hover = blue, Selected = orange EVERYWHERE** (`_HOVER_RGB`
  / `_SELECT_RGB` in `viewport_panel`; face/cell/edge hover highlights + the hover
  dot are blue, the body-selection subtree + handle-drag are orange). **Body hover**: when
  Body is the sole active mode the hovered component is tinted
  (`ViewportPanel.set_body_hover_mode`/`set_hover_component`, incremental per-cell
  recolor in the highlight overlay). It REUSES the existing viewport primitives —
  `_component_at`/`on_pick` (Body), `prepare_face_highlight`+`set_face_highlight` over
  a per-cell GLOBAL face id it builds (`_ensure_global_tri`, offset per component so
  `set_face_highlight`'s single-scalar mask highlights one source face across the
  merged mesh) for Face-B-Rep, the NEW `ViewportPanel.set_cell_highlight(cell)` for
  Face-Tess, `edge_pick` + `set_edge_pick_data`/`set_edge_pick_mode` (filtered to
  enabled kinds via `_subset_edge_data`) for Edge, and point-mode + `set_hover_snap`
  for Vertex. Four use-cases: **subscribe** (`selectionMade(SelectionResult)`),
  **set** (`set_selection`), **request** (`request(spec, cb)` — arm constraints,
  deliver the next pick, restore), **reset** (`reset()` → Body/Multi). While ENABLED
  it owns `on_pick/on_pick_none/on_pick_point/on_pick_edge/on_hover_edge` (snapshot-
  free — whoever picks a tool next re-installs its own). Effective multi-additive =
  `viewport_ctrl AND multi` (Single ignores Ctrl → replace). The bar height is pinned
  to one row (`QSizePolicy.Fixed` + a fixed-height scroll area — else the scroll
  area's Expanding policy made the whole strip tall).
- **Body↔tree wiring (main window)**: `sf.set_body_sink(SelectionController.
  _on_viewport_pick, _on_viewport_pick_none)` + `sf.enable(True)`; Body picks drive
  the tree via the sink (the tree is the source of truth — the filter does NOT
  self-accumulate when a sink is present, avoiding a double-toggle), and
  `_sync_filter_from_tree` mirrors the tree back into the filter (`set_selection`)
  on tree changes. Non-Body modes emit `selectionMade` (surfaced in the status bar /
  bar readout — not yet consumed by commands). `_on_escape` ladder gained: cancel a
  Construction request → reset a non-Body filter mode → (then eyedropper / clear).
- **Body↔tree wiring (EDITOR windows — item 32)**: the Source Editor (Transform
  Source, both trees) and the Component Editor (Body Tree) route their viewport↔tree
  BODY selection through the SF too, via **`sf.enable_body_selection(on_pick,
  on_none)`** — a **LITE** mode that installs ONLY the body pick callbacks
  (`on_pick`/`on_pick_none`) + body hover, leaving each window's own point/edge pick
  TOOLS (datum / cut / axis picks on `on_pick_point`/`on_pick_edge`) UNTOUCHED. A
  pure-Body session never calls `_disarm_special` (so it can't cancel an active
  window tool — guarded by `_armed_special`, set only when a non-Body arm took over
  point/edge). Switching the bar to a non-Body mode does a full arm that DOES take
  over the viewport (superseding the window's tool — the documented caveat). The
  **Origin Editor has no component tree** (subtree viewport + command pane), so
  there's nothing to sync — its own pick tools keep the viewport; the SF bar stays
  inert there. **(40)** the Source Editor's `_on_viewport_pick` selects BOTH trees
  DIRECTLY (under the `_syncing` guard, then highlights itself) instead of selecting
  the edit tree and relying on the mirror — and tolerates a `cid` present in only
  one tree (a body under a collapsed assembly-recipe node is omitted from the edit
  tree but kept in the source tree), so a viewport body pick always lands. **(46)**
  the edit-tree side resolves through `_edit_item_for(cid)` — the exact node, else
  the nearest ANCESTOR present in the edit tree — so a pick on a child of a
  collapsed assembly-recipe node (which the Main tree shows only as its opaque
  owner) selects that owner instead of leaving the Main tree unselected (the
  earlier "Source selects, Main doesn't" symptom).
- **Construction Geometry Builder** (`ConstructionGeometry`): the three-line,
  CENTER-aligned title `"Construction\nGeometry\nBuilder"`; the mode buttons
  (**Frame** / Plane / Axis / Point — `BASIS` is captioned "Frame") are stacked in a
  **2×2 GRID** (Frame/Plane over Axis/Point).
  Modes are
  NON-exclusive toggle buttons; the
  **None button is GONE** — item 31; the mode buttons are **DISABLED while a mode is
  active** so the user can't switch mid-construction — released on Accept/Cancel,
  item 35). A titleless params group (Accept · Cancel · Clear · entity + angle
  fields) is HIDDEN when no command is active. In Plane mode the **Shape toggle sits
  LEFT of the U/V + disc params** so it stays put when switching Rectangle↔Circle
  (item 36).
  **(31) Accept / Cancel are the request/return channel** (`constructionFinished`
  signal — emits the `ConstructedEntity` on Accept, `None` (a cancelled token) on
  Cancel): a future caller subscribes, requests a Plane/Axis/Vertex, and gets the
  entity or the cancelled token back. **BOTH `accept()` and `cancel()` deactivate
  ALL modes** (`set_mode(None)` → releases the owned filter, unchecks the mode
  buttons); Esc = Cancel (`MainWindow._on_escape` → `cg.cancel()`).
  **(item 12) `load_entity(mode, entity)`** starts a mode SEEDED with an existing
  `ConstructedEntity` (edit it, not blank): the seed rides in `_direct`, `valid()`/
  `_live_entity()` return it (a PLANE re-applies the bar's extents/offset/shape via
  `_direct_entity`), a fresh pick (`_on_entity`) or `set_mode`/`clear` drops it.
  **Entity slots E1/E2/E3** (`SlotEntity` kind vertex/edge_line/edge_arc/face;
  `item_to_entity`; the filter geometry rides on `SelectionItem.edge_info`/
  `plane_origin`/`plane_normal`).
  **(30) The CGB PERSISTENTLY OWNS the Selection Filter the whole time it is active**
  (Plane/Axis/Vertex), via `SelectionFilter.begin_owned/set_owned_spec/
  set_owned_disabled/end_owned` (NOT the one-shot `request`, which restored the bar
  after a single pick — that "re-opened the bar wide open" between E-steps).
  `_own_current` drives it from the CGB state: locked to the ACTIVE slot's
  `_slot_spec` (which NARROWS per slot — e.g. Plane E1 = flat-Face+Edge+Vertex, E2
  after an edge = Vertex-only, E3 = Vertex-only; Axis E1 = Edge+Vertex, E2 =
  Vertex-only) while a pick is awaited; **fully DISABLED (whole bar greyed) once the
  entity is complete** (no slot awaiting); and RELEASED (restored to the
  pre-ownership config) only on **Accept / Cancel / Esc** (`set_mode(None)` →
  `end_owned` — item 31). Vertex options stay user-editable throughout
  (`vertex_options`). Progressive `slot_status` (active/on/**x**/off/hidden): a slot that
  is no longer needed shows an ✗ and disables. **Resolution** (`_resolve_axis`/
  `_resolve_plane`): Axis — an edge fully defines it (line → its direction; arc →
  center + arc axis), else vertices (2 pts / 1 pt + **2 tilts**, item 26). Plane — a flat Face fully
  defines it (E2/E3 → ✗); an **Edge ALONE is an axis → a plane containing that axis,
  rotatable about it by angle A (item 39 — previews immediately, one ring about the
  edge dir; line → its direction, arc → its normal axis at the center)**, optionally
  REFINED by a vertex into the Edge+Vertex plane (through the edge's axis-line and the
  vertex, angle off, E3 → ✗); else vertices (3 pts / 2 pts + tilt about their line /
  1 pt + 2 world-axis tilts). Angles are **world-axis tilts** (Rodrigues, local
  elementwise math — no BLAS `@`). **Accept** (gated on validity ≥ Vertex 1) emits
  `entityConstructed(ConstructedEntity)`; **Clear** restarts; **None** exits.
  **Live preview + extents**: as soon as the geometry is valid it draws a viewport
  preview — a translucent plane quad (outline = the draggable handle layer) or an
  axis line — via `ViewportPanel.set_construction_preview` / (drag-safe in-place)
  `update_construction_preview_points`. **Plane SHAPE (item 17): Rectangle
  (default) | Circle** toggle (`set_plane_shape`), like the Component Editor's Split
  cut. RECT = the 4 U/V extents; DISC = a **Diameter + in-plane Center U/V** offset
  (`_disc_diameter`/`_disc_u`/`_disc_v`), previewed as an `_RING_N`-gon polygon
  (viewport preview kind `"disc"`; `_disc_perimeter`) with **draggable rim (handle
  id 0 → `diameter = 2·|hit−center|`) and a '+' center grip (`_H_DISC_CENTER`=13 →
  relocates the disc in-plane)** — both via the shared `_plane_uv_hit` ray∩plane. A
  disc `ConstructedEntity` carries `shape="disc"`, `diameter`, and world `center`.
  Plane extents (U−/U+/V−/V+) and axis extents
  (L−/L+) are spinboxes AND draggable handles (plane = 4 edge handles → ray∩plane
  updates u/v; axis = 2 endpoint ticks → closest-approach param t); the controller
  owns the viewport handle callbacks while a mode is active, updates points in place
  during a drag (`_dragging` guard — never rebuild actors inside the move observer)
  and does one full rebuild on drag-end. **Transform gizmo grips** (`_grip_geometry`,
  handle ids `_H_OFFSET`/`_H_ROT_A`/`_H_ROT_B`; per-grip resting colors via
  `_grip_color` → the handle layer's `base_colors`): Plane gets a **yellow Offset
  arrow** along the normal (spinbox + drag → `_closest_axis_param`; 1/4 its old
  length, an arrowhead at its tip, and it MOVES WITH THE PLANE — base at the
  post-offset origin) and **rotation rings** for its live angles — one about the
  V1→V2 line (2 pts + A) or two about world X/Y (1 pt + A,B), none at 3 pts;
  ring A = **magenta** (`_C_ROT_A`), ring B = **turquoise** (`_C_ROT_B`, item 33),
  both CENTERED AT THE ROTATION AXIS (the pre-offset base origin,
  `_plane_base_origin`) so the offset never drags them (item 20). A single-vertex
  Axis has **TWO DOF** (item 26) — angle A (world X, magenta ring) + angle B (world
  Y, turquoise ring), via `_axis_rot_axes` + `build_axis(pts, a, b)`; a 2-point/edge
  axis has no angle. Its end ticks are **brown, half-length** (`_C_AXIS_TICK`,
  dedicated ids `_H_AXIS_T0`/`_H_AXIS_T1` so they don't share the plane-extent
  colors — item 37). The axis has **no offset**, is CENTERED at avg(E1, E2), and its
  preview line uses a **CAD centerline (dash-dot) stipple** (`_apply_centerline`).
  Ring drag = ray∩ring-plane polar-angle delta (`_ray_ring_angle`/`_apply_ring_drag`
  — BOTH axis rings drag now, item 33a; edge-on rings are hard to drag, same caveat
  as the Component Editor gizmo). **The drag measures the angle about `_ring_center`
  (item 38) — the pre-offset base origin for a plane (where the rings are DRAWN),
  NOT the post-offset `ent.origin`** — so an offset plane's rings no longer
  misalign. **Direction arrowheads are CONES** (item 34) —
  `viewport.set_construction_arrows`/`update_construction_arrows` render
  `vtkConeSource` cones (oriented in C++, no `pv.Cone` BLAS crash) at the axis
  +direction end (orange) and the plane offset-grip tip (yellow), from CGB
  `_arrow_specs`; in-place re-pointed during a drag. A **Flip** checkbox (Axis +
  Plane) negates the axis direction / plane normal (`set_flip`).
  **Round 22 (items 41-45):** **(41)** re-clicking a slot that already holds an
  entity CLEARS it AND every downstream slot before re-arming (`pick_slot`) so the
  old selection's highlight/preview never obscures the new pick. **(42)** the cone
  arrowheads move DURING a drag — the fix was that `set_construction_arrows` bound
  the actor to a static `pv.wrap` snapshot, so mutating the `vtkConeSource` never
  moved it; `update_construction_arrows` now rewrites the actor's bound MESH points
  (`mesh.points = pv.wrap(src.GetOutput()).points`). Cone size halved (plane
  `s*0.01`, axis `s*0.015`) + the cone's own edges drawn (`show_edges=True`).
  **(43)** the 1-vertex 2-DOF rotation rings sit on the composition's ACTUAL axes:
  for extrinsic `Roty(B)·Rotx(A)·+Z`, varying B rotates about world +Y (ring B) but
  varying A rotates about **`Roty(B)·X`** (ring A), NOT world +X — so ring A is
  carried by B (`_tilt_ring_axes`, shared by `_plane_rot_axes` + `_axis_rot_axes`);
  the grip and the motion now match (was misaligned once B≠0). **(44)** a 2-vertex
  plane draws a NON-draggable V1→V2 indicator line (`_H_ROT_LINE`, colored like ring
  A) marking the axis angle A rotates about. **(45)** **Flip is the LAST operation**:
  the offset is applied along the UNFLIPPED normal, the in-plane disc/extents frame
  is built from the UNFLIPPED normal (`_plane_frame`/`_plane_offset_dir`), and only
  the reported `ent.normal` flips — so toggling Flip never MOVES the plane (offset
  arrow + drag + `_plane_base_origin` all use the unflipped offset direction). Also
  `set_mode`/`clear` now zero the tilt angles (a fresh construction starts
  un-tilted).
  **Round 23 (items 46-47):** **(46)** Source-Editor viewport Body pick now selects
  the Main-Structure tree too via `_edit_item_for` (above). **(47)** the far-right
  selection **readout labels are GONE from BOTH the SF and CGB bars** (clutter); the
  SF bar's fixed height now RESERVES the horizontal-scrollbar band
  (`horizontalScrollBar().sizeHint().height()`, ~+11px) so a narrow window's
  h-scrollbar no longer smooshes the single row into showing a vertical scrollbar.
  **Round 24 — the `BASIS` command (a 4th CGB mode, FIRST in the bar):** a
  DIRECTION-ONLY orthonormal coordinate frame (X/Y/Z directions, NO position — the
  user named it "Basis"). Built like an Axis for the **PRIMARY axis** (E1 edge, or
  E1+E2 vertices), then an in-plane **reference direction** — an E3 vertex projected
  ⊥ the primary, and/or a rotation **angle A** — defines the **SECONDARY axis**; the
  third axis follows by the **right-hand rule** (`_resolve_basis` +
  `_orthoframe(pdir, plabel, sdir, slabel)`). **PRIMARY/SECONDARY axis rework
  (superseding the original "Ref axis X/Y" radio):** two button groups — **Primary
  Axis** X/Y/Z (default Z; `basis_primary_axis`/`set_basis_primary_axis`) = what E1/E2
  defines, and **Secondary Axis** X/Y/Z (default X; `basis_secondary_axis`/
  `set_basis_secondary_axis`) = what the E3 reference defines. Primary and secondary
  can't be the SAME axis: the primary's axis is DISABLED in the Secondary group, and
  setting a primary that collides with the secondary bumps the secondary to a free
  axis. **The whole Secondary Axis group is DISABLED until an E3 reference vertex is
  picked** (`basis_secondary_enabled()`): without E3 the in-plane direction is
  arbitrary and rotating the basis / angle A covers the same freedom, so the choice
  isn't practically useful. So E1+E2 no longer forces Z — the frame is arbitrary.
  `Flip` negates the primary direction. Visual = an X/Y/Z line **triad** at the anchor point (red/green/blue,
  viewport preview kind `"basis"` via `_basis_triad_poly`) with a **cone arrowhead
  on each axis tip** (three `_arrow_specs`, axis-colored); one rotation ring about Z
  drags angle A (`_basis_rot_axes`). `ConstructedEntity.kind == "basis"` carries
  `normal`=Z, `xdir`=X, `ydir`=Y. Slots auto-advance E1-edge → E3 (skipping E2). The
  new sel-icon glyph is `basis` (a mini red/green/blue triad).
  **ALSO round 24 — cone arrowheads on the ORIGIN indicators:** `show_component_origin`
  and the Show-Global-Origin triad (`_redraw_scene_origin`) now draw a cone at each
  X/Y/Z tip (`_add_triad_cones`, `vtkConeSource`, matching the triad colors); the
  component-origin cones are tracked in `_origin_cone_actors` and removed with the
  triad. (Size may need tuning after the user sees it.)
  **Round 25 (items 47-50):** **(47/49a)** a grip-driven rotation angle now WRAPS
  into [-180, 180) (`_wrap_deg` in `_apply_ring_drag`) so it ROLLS OVER past ±180
  instead of sticking at the spinbox clamp — for the 1-vertex Axis AND Plane 2-DOF
  rings. **(48)** an Edge-Line in Axis mode already shows NO rotation rings
  (`_axis_rot_axes` gates on `angle_a_enabled`, False for an edge) and **(49-arc)** an
  Edge-Arc plane already rotates about the arc NORMAL at the center (verified). The
  reported symptoms (rings / wrong axis) come from **vertex-snapping stealing the
  pick** (a click near the edge/arc lands a VERTEX under the Vertex>Edge priority) —
  the real fix is item 50. **(50)** while a command OWNS the SF, the user can now
  TOGGLE among the modes the command offered (to narrow the pick — e.g. turn Vertex
  OFF to force an edge/arc pick); non-offered modes stay disabled, and the last
  active offered mode can't be turned off (never empties). New SF state `_owned_modes`
  (the offered set, from `_apply_spec` when locked) + `owned_modes()`; `set_mode_active`
  has an owned branch; the bar enables `mode ∈ offered and active != {mode}`. This
  SUPERSEDES the item-30 "whole bar disabled while a slot awaits a pick" — only the
  NON-offered modes are disabled now.
  **Round 26 (items 51-52):** **(51)** every cone arrowhead's SHAFT now stops at the
  cone BASE (center of the bottom circle), not the tip — the line no longer pokes
  through. Applied everywhere: the origin triads (`_triad_poly` trims to
  `size·(1−_TRIAD_CONE_FRAC)`, `_TRIAD_CONE_FRAC=0.22`), the CGB axis preview + basis
  triad (a `tip_gap` in the preview payload; the viewport trims via
  `_axis_line_points` / `_basis_triad_points`), and the CGB plane offset arrow (the
  handle shaft ends at `olen − cone_height` in `_grip_geometry`). **(52)** a Basis
  from a SINGLE vertex (E1) now behaves like a 1-vertex Plane: Z is defined by TWO
  tilt angles (A about world X, B about world Y) with TWO rotation rings, valid +
  previewed immediately (`_basis_one_vertex`; `_resolve_basis` uses `build_axis([v],
  A, B)` for Z, X = the auto perpendicular, RH for the third). The edge / 2-vertex
  Basis cases are unchanged (Z pinned by geometry, ONE ring = angle A rotates the
  reference about Z). `_basis_z_defined` now means "Z geometry-pinned" (gates the E3
  reference slot); `valid`/`angle_a` use the looser "E1 filled".
  **Round 27 (items 53-54):** each angle field is now SHOWN only when it applies —
  the bar ties A/B visibility to `angle_a_enabled()`/`angle_b_enabled()` (was tied to
  the mode). So an Edge-Line OR Edge-Arc **Plane** (one DOF = angle A about the edge
  axis) shows ONLY A, never a stray greyed B; a face / 3-vertex / 2-point case shows
  neither; a 1-vertex Plane/Axis/Basis shows both. The `angle_*_enabled` predicates
  were already correct — only the bar's visibility rule changed.
  **Round 28 (item 55):** the plane's Flip is now VISIBLE. Per item 45 Flip only
  negated the reported normal and the offset arrow pointed along the UNFLIPPED
  normal, so a plane (symmetric quad) showed no change on Flip. Now the offset/normal
  arrow — both the `_arrow_specs` cone and the `_H_OFFSET` handle shaft — points along
  the DISPLAY (flipped) normal (`ent.normal`), so toggling Flip REVERSES it visibly;
  the offset drag measures along that display arrow (negated into the unflipped-stored
  offset when flipped). The plane POSITION is still held on a flip TOGGLE (offset is
  applied along the unflipped normal in `_resolve_plane`, `_plane_frame` unflips) —
  item 45 preserved. Verified on the 3-vertex-then-offset case (`sf_phase23_r28.py`).
  **Round 29 (item 56):** in Basis mode with an Edge-Line/Arc E1 (Z), picking an E3
  reference vertex now points the Ref axis (X or Y) straight AT that vertex — the
  reference is the E3 direction projected ⊥ Z with NO `angle_a` offset (previously
  `_rot_about(seed, z, angle_a)` still spun it by any stale angle). By analogy with
  the edge+vertex plane, an E3 vertex PINS the reference: `angle_a_enabled` returns
  False and `_basis_rot_axes` returns [] once E3 is set (the ring + the A field both
  disappear); `angle_a` only spins the reference in the edge-ALONE case.
  **Round 30 (item 57):** the plane offset arrow's CONE is now draggable too (was
  shaft-line only). The handle layer gained **hit-only segments** —
  `ViewportPanel.set_handle_data(..., hit_segments, hit_ids)` records segments that
  `_handle_at` hit-tests but the actor does NOT draw. `_grip_geometry` adds the cone
  tip point + a hit-only segment (cone base→tip, id `_H_OFFSET`) stashed on
  `_grip_hit_segs`/`_grip_hit_ids` (the return stays a 4-tuple); `_install_handle_data`
  forwards them. So clicking anywhere along the arrow — shaft OR cone — starts the
  offset drag, with no shaft drawn through the arrowhead (item 51 intact).
  **Round 31 (item 58):** the Basis triad/gizmo preview is half as big —
  `_basis_length` `model·0.2 → 0.1`, with the axis cones (`_arrow_specs` `s*0.02 →
  0.01`) and the shaft `tip_gap` halved to match so it stays proportional.
  **(18-20) The Selection-Filter Vertex OPTIONS group stays editable while a CGB
  request locks the rest of the bar** (`SelectionSpec.vertex_options` →
  `SelectionFilter.vertex_options_editable()`; the CGB `_slot_spec` sets it for
  Plane/Axis/Vertex) so the user freely adjusts End/Mid/Center + edge-kind +
  sub-mode mid-pick. All elementwise (no BLAS `@`).
- **Hover rendering** — `_unified_hover` RESOLVES the target then applies each
  highlight to its resolved value exactly ONCE; every viewport highlight setter is
  de-duped (incl. `set_hover_point` now), so an unchanged hover re-renders nothing
  (fixes the face/edge hover FLICKER that came from clearing-then-re-setting the same
  highlight every mouse-move). **Item 13**: when the cursor leaves geometry (raw
  point None) the observer clears EVERY hover highlight (edge/face/cell/body tint)
  so nothing sticks over the blank background. The pickable-edge layer is drawn
  **depth-tested with a small coincident-topology offset** (`_draw_edges_occluded`,
  not `_draw_on_top`), so far-side edges are OCCLUDED by the shaded surfaces instead
  of showing through like a wireframe (same for the Show Tess Edges overlay); with
  Show Shaded off, all edges show. **While Face→Tessellation OR Vertex→Tessellation
  is armed the filter forces the Show-Tess-Edges wireframe ON** (items 12/28 — so
  you see the triangle you'd pick a face/vertex from — `_set_tess_overlay`,
  restoring the user's toggle state on disarm).
  The hover dot + the selected/constructed-vertex dot are now sized in SCREEN
  PIXELS — a CONSTANT apparent size (~`_MARKER_PX`=6px radius) at any zoom, model
  scale, or window (`ViewportPanel._marker_world_radius` converts px→world via the
  camera's parallel scale (ortho) / focal distance+view-angle (perspective), no BLAS;
  falls back to `model·0.0025` headless). The hover actor is a UNIT sphere re-scaled
  per show; the CGB vertex indicator sizes at draw. (Was a fixed world-space
  `model·0.0012` that vanished on large models — item 4; applied globally in every
  viewport.) Both proximity gates are now DISPLAY-PIXEL (screen-space, consistent
  at every zoom): the edge-hover gate is **`_EDGE_PICK_GATE_PX` = 15 display-px**
  (`edge_at_cursor()` re-uses `_edge_at` from the stored last cursor xy) and the
  Vertex hover+snap gate is **`_VERTEX_GATE_PX` = 15 display-px**
  (`SelectionFilter._within_vertex_gate` projects the candidate vertex + the raw
  surface point via `ViewportPanel.world_to_display` and compares pixels; accepts
  when projection is unavailable, e.g. headless).
- **Capability gating (`SelectionCapabilities.from_assembly` → `has_brep`)**:
  `has_brep = any(component.shape is not None)` (STEP → True; a future tess-only
  OBJ/STL/USD importer with `shape=None` → False). `ViewportPanel.load()` pushes the
  assembly (recomputes caps + drops caches) via `selection_filter.set_assembly`.
  When `has_brep` is False the bar greys **Edge mode**, **Face→B-Rep** and
  **Vertex→Edge** and forces those sub-modes to **Tessellation**; the controller's
  `set_mode`/`set_*_submode` refuse the B-Rep-dependent options too. Body,
  Face→Tessellation, Vertex→Tessellation stay available (mesh-only). Construction
  Geometry stays enabled (its vertex picks fall back to Tessellation).
- **Pickable-edge layer PRE-CALC (NEW — no more freeze; headless-verified, GL
  live-test PENDING)**: the per-`TopoDS_Edge` `edge_pick` layer (Edge /
  Vertex-Edge snapping) used to build IN-PROCESS on first arm, which FROZE the GUI
  on the ~20k-part main model (GIL-holding OCC). It is now **built in a SUBPROCESS
  + cached** (`src/gui/edge_pick_build.py` worker → `edgepick-{stage}.npz` via
  `cache.edge_pick_cache_path`; topology-keyed so NOT tied to the mesh deflection).
  `edge_pick.save_edge_pick_npz` stores the poly + the `EdgeInfo`s as **PARALLEL
  NUMPY ARRAYS** (NOT one JSON blob — a 20k-part model's ~1.4M-edge blob crashed
  with "string too large to store inside array"; the box test never hit it).
  `load_edge_pick_npz` returns `(poly, arrays)` — the RAW arrays, no objects
  (building 1.4M `EdgeInfo`s up front would itself freeze).
  `MainWindow._arm_edgepick_prebuild` (armed at each `_commit_model`, mirrors
  `_maybe_prebuild_source`: silent, one-shot, polls until idle) loads the cache or
  spawns the worker, then pushes it via `SelectionFilter.preload_edge_data(poly,
  arrays)`. Arming calls `edge_pick.subset_arrays` — a VECTORIZED per-cell mask to
  the **visible** leaves returning a LAZY `EdgeInfoArray` (no bulk object build; see
  the Edge-mode INTERACTION performance bullet), so it's INSTANT at any size (the
  old per-subset object build + a `_EDGE_INFOS_MAX` skip-cap are GONE). Guard: with
  NO preload yet AND `> _EDGE_INPROC_MAX` (1500) leaves the SF DEFERS (empty layer,
  no in-process build) until the pre-calc lands. `_leaves` excludes HIDDEN/
  SUPPRESSED (edges cover only what's shown); `ViewportPanel.set_hidden` calls
  `SelectionFilter.invalidate_edges` so hiding drops those edges.
  - **⛔ EVERY subset must DEEP-COPY its points — never alias the source's buffer.**
    `poly.points` is a live view onto that mesh's VTK buffer and **pyvista installs a
    numpy array into a new mesh zero-copy** (probe: with `np.asarray`,
    `np.shares_memory(sub.points, src.points)` is `True`; with `copy=True`, `False`).
    Aliasing left the cached whole-model layer and every armed subset sharing ONE
    buffer, so dropping any of them freed it under the others — surfacing as a Windows
    **`0xc0000374` heap corruption** at a later, unrelated read of `poly.lines`, with
    no Python traceback. It bit twice live (a plain re-arm, then a datum pick during
    ReOrigin, which makes `_append_datum_edges` subset a subset). Both builders —
    `pv_polydata_lines` and `edge_pick.subset_arrays` — now copy. **Value assertions
    cannot see this**: values are identical either way. Guarded by a MEMORY assertion
    in `scratchpad/edge_poly_aliasing_test.py`.
  - **Late-arriving edges POP INTO an in-progress command** (Measure / CGB / SF)
    with NO exit+re-enter: `preload_edge_data` re-arms whenever the SF is
    `_enabled` — NOT gated on `_armed_special` (after a rebuild/model-switch
    reload the flag can be momentarily stale vs the owned state, so the push's
    re-arm silently no-op'd and the user had to toggle Measure off/on). A plain
    `_arm()` is idempotent — it rebuilds the edge layer for the ACTIVE mode (or
    harmlessly re-arms Body) from the freshly-installed `_edge_preloaded`.
    `invalidate_edges` likewise re-arms on `_armed_special OR is_owned()`.
    (The transform bake deletes `edgepick-{stage}.npz` via `delete_variant_derived`,
    so the post-rebuild prebuild re-runs + this re-arm pops the new edges into the
    re-entered Measure command.) Verified `scratchpad/edge_rearm_test.py` (7 — an
    owned CGB/Measure with a DEFERRED empty layer gets populated when
    `preload_edge_data` lands, incl. a stale-`_armed_special` regression).
  Verified: `edge_pick_cache_test.py` (14 — save/load round-trip incl. the
  parallel-array serialization + `subset_arrays` cid/kind subsets) +
  `edge_pick_worker_e2e.py` (4 — box .xbf → worker subprocess → fresh cache) + the
  worker built the full **testA1 root (19,952 parts → 1,430,941 edges, 67 MB)**
  without crashing.
- **Edge-mode INTERACTION performance — O(#edges) → O(1) (NEW; GL live-test
  PENDING)**: arming + every hover used to touch ALL visible edges, so on a big
  model Edge/Vertex snapping was slow to "appear" and laggy to use. Fixed by
  making the edge layer **array-backed + lazy + locator-narrowed**:
  - **`edge_pick.EdgeInfoArray`** — a LAZY sequence over the parallel arrays;
    `subset_arrays` (visible-leaf + kind) is a pure VECTORIZED slice that builds
    NO `EdgeInfo` objects, so arming is INSTANT regardless of edge count (the
    ~200k-object bulk build at arm was the "takes a while to appear"). `EdgeInfo`s
    are built only on index.
  - **Hover snaps to the ONE edge under the cursor** — `_snap_vertex_edge_point`
    / `_arc_center_hover` call the viewport `edge_at_cursor()` (locator, O(1)) and
    index that single edge, instead of scanning every armed edge (End/Mid/Center
    lie on the curve, so being near a vertex ⇒ the locator returns its edge —
    behaviourally equivalent). Fixes hover/highlight lag.
  - **Camera-drag gate** — the MouseMove observer SKIPS model-space hover work
    while the style's `GetState() != 0` (a `StartRotate`/`StartPan` drag). Fixes
    rotate/pan.
  - **Render cap (WIREFRAME ONLY — the highlight is never capped).**
    `set_edge_pick_data` draws the whole-model wireframe only when
    `len(infos) <= _EDGE_DRAW_MAX` (40k); above that it keeps just the hit-test
    LOCATOR (the ~N-lines ×depth-peel render was the zoom/frame stall).
    **⭐ The HIGHLIGHT must stay outside that branch.** It used to be a
    whole-model per-cell-RGBA mesh created *inside* `if draw:`, so on a real model
    (**1,108,091 edges** on testB2) the highlight actor never existed,
    `_set_edge_highlight` returned immediately, and **nothing could ever highlight**
    — hovering an edge showed nothing and clicking one had no visual (reported live
    as "edge hover/select stopped working"). It is now a SMALL dedicated one-edge
    actor: `_make_seg_mesh(_EDGE_HL_SEGS)` (256 independent 2-point segments, all
    points coincident → invisible) pre-created in `set_edge_pick_data`, and
    `_set_edge_highlight` only rewrites `mesh.points` via
    `_edge_segment_points(index, cap)` (pulls that edge's cells out of
    `_edge_pick_mesh`, pads by repeating the last point → degenerate/invisible
    segments) + sets opacity/visibility — all observer-safe (no actor add/remove),
    the same in-place trick as `update_construction_arrows`. Cost is O(1) in model
    size, so highlighting works at any edge count.
  - The datum-axis edge merge (`_append_datum_edges`, an O(#edges) Python rebuild)
    is skipped above `_DATUM_EDGE_MERGE_MAX` (5000) — datum axes aren't edge-
    pickable on a huge layer (rare aid), model edges unaffected.
  So on a huge model Edge snapping is responsive: instant arm (lazy), O(1) hover
  (locator), no hover during camera drags, and no wireframe render above 40k.

## Fit Primitives (analytic recovery — B-Rep + mesh)
Recover an analytic axis / plane / center / sphere so a mesh face or a `Face[Other]` / cylinder becomes usable geometry (cylinder joint axes, sphere centers, cone axes, mesh parity):
- **`fit_primitives.py`** (OCC, in-process, no BLAS): `analytic_face_feature` → cylinder axis / sphere center / cone axis + `feature_to_slot_kind`. `SelectionItem.face_feature` is populated in `_face_item`; `item_to_entity` builds `face_cylinder` / `face_sphere` / `face_cone` + `edge_other`.
- **`fit_primitives_worker.py`** (subprocess, registered `"fit_primitives_worker"` in `src.main._WORKERS`): mesh least-squares plane / cylinder / sphere (`np.linalg` — kept OUT of the VTK process; takes an optional world `m4` so the GUI passes LOCAL verts + the world 4x4 and no BLAS runs in-process).
- **Live FitService** (in the CGB): `_entity_for(item)` (item_to_entity, then a mesh-face fit fallback), `_fit_mesh_face` (gather the patch via `fit_primitives.mesh_face_patch` → `_run_fit_worker` blocking QProcess → SlotEntity), `_fit_cache` per (cid, face) cleared each `set_mode`. `_slot_spec` KEEPS Face for a MESH model (the FitService recovers the primitive on pick).

## Frame command
`cgb_command.FrameBuilder` composes two `CgbCommandBinder` slots — an ORIGIN Point + an ORIENTATION (a Frame construction with `WANT_ORIENTATION`) — into one `ConstructedEntity(kind="frame", origin/xdir/ydir/normal)`; the orientation is optional (identity / world = the "Global" case). `frame_matrix4` (above) turns it into the 4x4. There is no separate bar button for the COMPOSED form — the bar's **Frame** button is the single-construction builder; composition is a command-pane arrangement.

## Numeric entry (opt-in)
`ConstructionGeometry.set_numeric_point/axis/plane` seed the SAME `_direct` channel a pick/load uses (so `_live_entity` resolves them and Accept emits them; a fresh pick supersedes). `ConstructionBar` has a **"Numeric"** checkbox (default OFF) + adaptive spinboxes (POINT x/y/z; AXIS/PLANE origin + dir/normal), revealed per mode.

## Measure modes
`viewport_panel.MeasureMode` (DISTANCE / COORDINATE / ANGLE / RADIUS / BBOX) + `_MEASURE_NEEDS`; `set_measure_mode` accepts `bool | MeasureMode | None`; a settings-strip mode combo drives `_on_measure_point` (a per-mode dispatcher that accumulates the pick count then draws — `_draw_measure_coordinate/angle/bbox/radius`; RADIUS reads an arc/cylinder radius from the AXIS entity). `measurementMade` carries a `kind`; `main_window._on_measurement` is kind-aware. Picks are gathered through the CGB (see the Measure tool in `viewport-interaction.md`).

## Joint free-axis picker
A joint's axis is a **free world-frame unit vector** (`geometry_edits.JointDef.axis`; legacy `"X"/"Y"/"Z"` strings migrate to vectors). The `main_window` joint pane has a **"Pick Axis…"** `CgbSlotButton` → requests an AXIS from the CGB → stores the normalized world direction; an axis-ALIGNED pick collapses to the X/Y/Z combo token (byte-identical to an aligned joint), a free pick greys the combo. USD authoring detail → `kinematic-joints.md` (NOTE: that doc predates this change and still describes the old `"X"/"Y"/"Z"` axis — tracked in `status.md`).

## Commands that consume the SF/CGB
- **ReOrigin** (main-window `origin_window`; the menu item was "Set Origin…" — renamed to match the Component Editor's command) — a `CgbCommandBinder` + two `CgbSlotButton`s: **Point** → origin, **Orientation** (the button was labelled "Basis") → axes. There is **no Global/Custom selector**: the orientation source is **INFERRED** — no Orientation ⇒ Global (explicit world basis, the Butler rule), an Orientation ⇒ Custom (`OriginWindow._orient_source` is a derived property). Only the origin Point is required to Apply; right-click → Clear on the Orientation button returns to Global. While the Orientation is being picked (`binder.pending_key == "basis"`) the EXISTING origin indicator — triad + Z guide + ball — drops to **25% opacity** (`_ORIENT_GHOST_ALPHA`; set it to `0.0` to hide outright), because two solid triads at the same spot were impossible to tell apart: faded = what is there now, solid = the orientation being defined. Produces an `OriginFrame`. See `geometry-edits.md`.

## Which SF modes each target arms (spec-conformance)
`ConstructionGeometry._slot_spec` gets its offered SF modes from **`cgb_features.sf_modes_for_target`** — one table (`TARGET_KINDS` + `MODE_OF_KIND`) generated from the spec's per-target *"Selection types available"* rows. This exists because the hand-written offer had **drifted from the spec**, silently making whole construction rows unpickable:
- **Frame withheld Face** → all five `primary: Face[...]` rows were unreachable (reported live as "in CGB Frame mode the SF Face option is disabled"). Face is now offered, and `_c_basis` gained a **PLANE-kind primary** branch (primary = the face NORMAL, anchored at the face origin) plus **LINE/PLANE secondary** support in slot 3 (an edge direction / a second face normal, projected ⊥ primary) — the POINT-reference branch is byte-identical, so the `[impl]` rows are untouched.
- **No target offered Body** → `point: Body[Any]` (centroid) was unreachable. Point (and Frame) now arm Body; `SelectionFilter._finish_body` **bypasses the tree body-sink while a command owns/requests the bar** (else the tree ate the pick and the command got the stale result) and attaches the component's world centroid to the item, which `item_to_entity` maps to a `body` SlotEntity. Body is last in the pick priority, so the user narrows to Body via the owned-mode toggles (item 50) to use it.
- `Datum[*]` kinds ride the SF mode of their model counterpart (point→Point, axis→Edge, plane/basis→Face).
- The **composed** Frame target arms the UNION of Point + Frame.
`scratchpad/cgb_spec_modes_test.py` PARSES the spec's tables and asserts the code matches, so this can't drift again silently.

## Request constraints — Axis↔Direction, Frame↔Orientation
A positioned builder can be consumed in a REDUCED form, and the two cases are exactly parallel — **Axis** (origin+direction) consumed for its direction is a **Direction**; **Frame** (origin+orientation) consumed for its axes is an **Orientation**. Neither has its own builder: the CGB runs the same construction and the consumer ignores the rest. So the CGB bar has 4 modes (**Frame** / Plane / Axis / Point — the BASIS token is captioned "Frame") while commands request 6 named entities.
- `cgb_core` carries `WANT_FULL` / `WANT_DIRECTION` / `WANT_ORIENTATION` + `WANT_LABEL` / `want_label(target, want)` — the ONE place a request's user-facing name is decided.
- `CgbCommandBinder.register(..., want=...)` stores it per slot and calls `ConstructionGeometry.set_want()` on request; `set_mode(None)` clears it back to `WANT_FULL`.
- `ConstructionGeometry.want()` / `request_label()`; `ConstructionBar._sync` titles the params group with the request name, so a direction-only / orientation-only pick reads unambiguously even though several requests share one mode.
- **A button that requests a specific entity MUST be captioned with what it requests** (Axis / Direction / Frame / Orientation) and activate the underlying mode with that constraint. Applied: ReOrigin's **Orientation** button (`BASIS` + `WANT_ORIENTATION` — the pane supplies its own origin Point); the joint pane's **"Pick Direction…"** (`AXIS` + `WANT_DIRECTION` — a joint stores only the direction, its position comes from Body1's frame; it was mis-captioned "Pick Axis…").

## Frame origin + the Plane·Point·Point row
**FIRST-PICKED-POINT origin (universal for Frame).** A Frame anchors at the **first point picked**, in every row that includes one — one point or two, with or without a face. Only a row with NO point falls back to the primary's own anchor (edge → its midpoint/centre, face → the face origin). This makes the origin **order-independent**, so the same picks in any order anchor identically. **Axis and Plane are unchanged** (axis of 2 points = midpoint, 3-point plane = centroid) — for a line/plane the anchor is incidental, for a Frame it is a pose.
- The plain 2-point Frame therefore moved **midpoint → P1**, an intentional divergence from the retained `_resolve_basis` oracle. `cgb_regression_test.case(..., expect_diff=("origin",), why=...)` records it: the origin field is allowed to differ (with the reason printed), **every other field is still guarded**, and the oracle is left untouched so it stays usable as evidence of the old behaviour. A field that was declared to differ but MATCHES also fails — so a silent revert is caught too.
- **Slot 1 names the primary axis**, so pick order still matters for *which axis is exact*: `Plane·Point·Point` makes the face normal exact; `Point·Point·Plane` makes the P1→P2 line exact. Both are fully defined; both now anchor at the same point.
- **Two independent flips.** The params-row `Flip` negates the PRIMARY (`CgbParams.flip`); a second **`Flip`** checkbox between the Primary X/Y/Z buttons and the *Secondary Axis* label negates the SECONDARY (`CgbParams.basis_secondary_flip` ← `ConstructionGeometry.set_basis_secondary_flip` / `basis_secondary_flip()`, reset by `set_mode`/`clear`). Applied AFTER the Reference/angle resolves, so it is a clean 180° of the resolved secondary; the third axis follows the right-hand rule (so it reverses too) and the frame stays right-handed. The bar **HIDES it unless `basis_secondary_enabled()`** — with a free secondary, angle A ±180° already is this flip, so the checkbox would be redundant.
- New `[new]` row **`primary: Face[Flat]` + `point` + `point`**: primary (Z) = the face **normal** (exact), secondary (X) = the **P1→P2** direction projected ⊥ primary, **origin = P1**. The workhorse case — a mounting face gives the exact primary axis, two features give the in-plane reference, the first point gives the position.
- A **PLANE primary now advances E1→E2→E3** (`_next_active_slot`) and E2 is offered rather than ✗ (`slot_status`), because it uses both: one point = the plain `reference` row (which keeps the face origin), two points = the direction row above. An **EDGE/axis primary still skips E2** (its reference lives in E3) — unchanged.
- **Component-Editor ReOrigin + Transform Move-Point** (`edit_bodies_window`) — CGB-driven Point / Orientation picks (its buttons were relabelled to match: "Basis"→"Orientation", "Vertex"→"Point", "From / To Basis"→"From / To Orientation"). See `geometry-edits.md`. (The full binder-dedup of that file's three CGB consumers is a documented follow-up — intertwined shared helpers, no offscreen harness.)
- **Joint axis picker** (`main_window`) — above.
- **Known limits (this testing round)**: on a COLD cache the first
  edge-pick pre-calc runs in the background (status "Preparing edge snapping…") —
  Edge snapping activates when it lands (empty until then, never a freeze). In an
  editor window, BODY selection now
  coexists with the window's tools (LITE mode — item 32), but switching the SF to a
  NON-Body mode still supersedes that window's active pick tool (they can't both own
  the viewport). Vertex "Center" = arc center (no-op on
  straight edges); Edge "Arc" = circular edges (arc vs full circle not distinguished).
  Verified offscreen (`selection_filter`/`construction_geometry` controller state
  machines, Single/Multi, request/restore, reset, capability gating, plane/axis
  math, bar sync); real-GL picking is USER live-test.

