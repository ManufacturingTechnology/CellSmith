# Viewport interaction

Everything about the 3D viewport (`viewport_panel.py`): the mouse/interactor model, picking, depth-peeling + hidden-cell display handling, the viewcube + navigation glyphs + camera animation, orientation indicators, the per-viewport settings strip + `ViewSettingsBus`, error dialogs, and the Measure tool. Read when changing viewport rendering, selection/picking, camera, or the settings strip. Verify against `src/`; may lag.

---

> **Redesign update (authoritative: `selection-and-cgb.md`).** The **Measure tool** now has MODES (distance / angle / radius / coordinate / bbox — `viewport_panel.MeasureMode`), and the viewport gained a persistent **user-datum layer** (`set_datum_records` — point/axis/plane/basis glyphs) alongside the fixed CGB datum aid. The single-distance Measure description below predates the modes.
>
> **⭐ Measure is DIRECT-PICK, not construction** (`ConstructionGeometry.set_auto_accept`). The CGB normally KEEP-PICKS: a pick fills a slot and arms the next, and the user Accepts. For a measurement that is wrong — you are selecting existing geometry, so one click must be one entity. Picking two planes in ANGLE mode used to fill E1+E2 of a SINGLE Axis construction → `axis_plane_intersect` (their intersection LINE), delivered nothing, and left a half-built axis in the bar (reported live as "the UI looks more like it's defining an axis" while picking the YZ plane + a plane datum). `_arm_measure` now sets **`set_auto_accept(True)`** — the FIRST valid construction is delivered immediately (deferred one event loop so the pick signal completes), no Accept, no further slots — plus `set_want(WANT_DIRECTION)` for ANGLE so the bar names the request "Direction". `set_mode(None)` clears both, so a normal command can never inherit them. **Trade-off:** a Measure pick can't use a MULTI-slot construction (a 2-point axis, a midpoint), because the single-pick form is already valid.
>
> **What each mode COLLECTS** (`_MEASURE_NEEDS` / `_MEASURE_AXIS_MODES`): Distance 2 points · Coordinate 1 point · BBox 2 points · Radius 1 **AXIS** · **Angle 2 AXES**. Angle originally took **3 points** (apex form), so picking a FACE did nothing — the pick carried no `.point` and was silently re-armed (reported live as "I should be able to select two planes to measure the angle"). It now arms **AXIS**, which the CGB resolves from a flat face's **normal** (`axis_face_normal`), an edge line, an arc/cylinder axis, or two points — so two planes, two edges, edge-vs-plane and cylinder axes all measure under one rule. An apex angle is still expressible as two axes sharing the apex. Because a direction's SIGN is arbitrary (a normal may point either way; the CGB's Flip toggles it), the readout reports **θ and its supplement** — for two planes the acute one is the usual answer.

## Viewport interaction (viewport_panel.py)
- **Mouse** (`_CADInteractorStyle`): LEFT = select/pick only (no camera), CTRL+LEFT =
  add/remove from selection (multi-select), MIDDLE-drag = rotate, RIGHT-drag = pan
  (also CTRL+MIDDLE), **RIGHT-click (no drag) = context menu** (same as the tree; see
  below), wheel = zoom. Right click-vs-drag is told apart by movement between press and
  release (`_CLICK_TOL2`); `_right_up` fires `_on_right_click` only on a negligible move.
  **Picking is done IN the style** (`_pick_display`),
  NOT via pyvista's `enable_point_picking` — pyvista's pick callback needs pyvista's
  own interactor style (`GetInteractorStyle()._parent()`), which our custom style
  replaces (that mismatch silently broke left-click selection). Picking casts the view
  ray through a cached `vtkCellLocator` and selects the NEAREST **visible** component —
  hits on effectively-hidden (hidden/suppressed) components are skipped, so you click
  "through" an invisible part to the one behind (`_pick_display` + `_ensure_locator`).
  `_left_up` passes the Ctrl state as `additive`; a hit calls `on_pick(cid, additive)`,
  a miss calls `on_pick_none(additive)`.
- **Deselect-all / cancel**: **Esc** (`MainWindow._on_escape`) FIRST cancels an active
  pick mode (eyedropper); otherwise it — or a plain LEFT-click on empty
  space (miss → `on_pick_none(False)`) — clears the tree selection + 3D highlight +
  origin triad. CTRL+LEFT on empty space is a no-op.
- **Z-origin datum pick** now lives in the TRANSFORM MAIN window (its own
  viewport uses the same machinery): `set_pick_point_mode` → the next
  left-click captures the surface 3D point (`_point_at`, source coords) →
  `on_pick_point`; the window places the datum along the PENDING up axis
  (zeroing the other two) and changing Up resets it. While the mode is active
  a **hover preview** marker (yellow sphere, `set_hover_point`) tracks the
  surface point the next click would capture — driven by a MouseMove observer
  added on the INTERACTOR (not the custom style, so camera handling is
  untouched; `_on_hover_observer`, added once, guarded by `_hover_obs_added`).
  The datum is a Source→Main bake input (baked into the geometry) — no export
  CLI applies it.
- **Show Global Origin** (settings-STRIP checkable toggle, TRANSIENT — NOT in the
  config; **default OFF** — `ViewSettingsBus.show_global_origin = False`):
  `set_scene_origin(enabled, (0,0,0))` draws a larger export-axis triad + a small
  yellow marker sphere (radius `model_size*0.12*0.03`) at the WORLD origin —
  which IS the export origin, since orientation + datum are baked into every
  model's main stage (`_scene_origin_actors`, `_redraw_scene_origin`). Shown
  ONLY when the toggle is on AND **nothing is selected**
  (a selection draws the per-component origin triad instead, so the two never compete).
  Refreshed live by `MainWindow._update_scene_origin()` on toggle, on selection change
  (tree `selectionChanged`), and after
  every (re)render (since `viewport.load()`→`clear()` drops all actors).
- **Multi-select** is the single source of truth in `SelectionController`: the tree
  (ExtendedSelection, Ctrl+Click) and viewport (Ctrl+LEFT) both feed it; highlight =
  subtree expansion of the whole selection. `TreePanel.mousePressEvent` swallows a
  right-press on an already-selected row so Qt doesn't collapse a multi-selection
  before the context menu opens.
- **Context menu** (tree AND viewport → same actions): the viewport's right-click finds
  the component under the cursor (`_component_at`, shared with `_pick_display`) and
  calls `on_context_menu(cid|None, global_pos)`. `MainWindow._on_tree_menu` /
  `_on_viewport_menu` resolve the target set (`_menu_targets`: right-click outside the
  selection resets it to the clicked node; inside it, acts on the whole selection) then
  hand off to the shared `_exec_component_menu`. In the viewport a right-click on empty
  space acts on the current selection (if any). Display→global mapping accounts for the
  VTK bottom-left origin + device-pixel ratio.
- **Opacity slider** (settings strip): transient global view opacity — folds into
  the per-cell alpha in `_refresh_cells` (`set_global_opacity`). NOT persisted, NOT
  exported; hidden components are EXCLUDED from the display mesh (not alpha-zeroed —
  see depth-peeling note below).
- **Depth peeling** (`ViewportPanel.__init__` → `plotter.enable_depth_peeling`,
  guarded): hiding/suppressing sets a component's per-cell alpha to 0; once ANY
  cell is <255 VTK renders the WHOLE merged actor in the translucent pass, and
  WITHOUT depth peeling the opaque (alpha 255) cells behind others blend through
  → the model looks glassy ("suppress a body → everything turns transparent").
  Depth peeling gives order-independent transparency so alpha-255 cells stay
  solid. (User-live-tested — no GPU in the dev env.)
  - **Hiding EXCLUDES cells from the shaded actor's DISPLAY mesh — it does NOT
    alpha-zero them** (`_rebuild_display_mesh` / `_visible_cell_index`, called
    from `set_hidden`). Alpha-zeroing hidden cells flipped the WHOLE merged
    actor into the translucent pass; it then stopped writing depth in the opaque
    pass, so the SEPARATE edge overlays (feature/face edges, Show-Tess-Edges
    wireframe, edge-pick layer) showed through everything like hidden lines —
    depth peeling does NOT reliably occlude translucent LINES on every GL driver
    (offscreen it does; the user's live GL does not, so `SetForceTranslucent`
    was NOT a fix — reverted). Instead the shaded actor's input is swapped to a
    VISIBLE-cell subset (`full.extract_cells(visible_idx)` → UnstructuredGrid)
    so with opacity 1 it stays OPAQUE, writes depth in the opaque pass, and the
    edge overlays (even translucent ones — a hidden edge is still alpha-0) are
    depth-tested against it and occluded normally. `_combined.mesh` stays the
    FULL mesh (authoritative for picking / edge extraction / colour
    computation); only the display ACTOR uses the subset. `_refresh_cells`
    writes the full RGBA to `_combined.mesh` (overlays copy it) AND, when a
    subset is active, `rgba[_visible_idx]` to `_display_mesh` (fast fancy-index,
    no re-extract — so hover/highlight recolours stay instant while hidden).
    `_visible_idx`=None ⇒ display IS the full mesh (nothing hidden — the common
    path is byte-unchanged). Re-extract cost ≈ 50 ms / 300k cells, only on a
    hide/show set CHANGE. The opacity SLIDER (<1) still makes the actor
    genuinely translucent (a deliberate see-through mode); edge occlusion there
    is peeling-dependent and acceptable. (Real-GL-probe verified: hiding a
    non-overlapping body changes an occluded region by 0 px; no wgl errors.)
  - **The Show-Tess-Edges wireframe excludes hidden components** — it's a fixed
    actor with no per-cell alpha, so `_rebuild_tess_edge_actor` subsets the
    combined mesh to (body-filter ∪ all) MINUS `_hidden`, and `set_hidden`
    rebuilds it. (Feature edges already hide per-component via `_refresh_edges`
    alpha=0.)
- **Orientation indicators** (`viewport.set_orientation(M)`): the bottom-left
  corner gizmo (`vtkAxesActor` in an orientation widget, UserTransform = Mᵀ, viewport
  set to `(0,0,0.15,0.15)` — anchored at the window origin so it hugs the
  bottom-left corner) and the selected-node origin triad (arrows along M's
  rows). The MAIN
  window's viewport keeps the default IDENTITY orientation (Main is truly
  baked-oriented now); the TRANSFORM SOURCE window drives `set_orientation` live
  with the pending settings over the untouched SOURCE preview (root model only).
- **Viewcube + navigation glyphs (ALL viewports)**: a top-right interactive
  VIEWCUBE — a CUSTOM overlay-renderer cube (`_ensure_view_cube`), NOT VTK's
  `vtkCameraOrientationWidget` (which was replaced: it mis-picked faces — click
  +X showed −X — snapped to ABSOLUTE views ignoring current roll, and had no
  roll control; VTK 9.6.2 exposes no hook to fix any of that). Ours: a
  layer-1 `vtkRenderer` (`SetViewport(0.80,0.80,1,1)`, `InteractiveOff`) holds a
  VISIBLE **chamfered cube** — `_build_viewcube_polydata` builds 26 pickable
  FACETS (6 face quads + 12 edge bevels + 8 corner triangles), each a cell whose
  id maps to a view direction (`_cube_dirs`); faces are axis-tinted from the
  SHARED `_AXIS_RGB` palette (+bright/−dim), edges/corners gray, facet edges
  drawn. (The earlier annotated-cube + opacity-0 pick cube was replaced — the
  picker SKIPPED the transparent pick cube → dead clicks, and it showed only 6
  flat faces.) **`_AXIS_RGB` is the ONE axis-color source** — the bottom-left
  gizmo (`vtkAxesActor` shaft+tip) reads it too, so gizmo + cube always match
  (change colors in one place). **Hover** lightens the facet under the cursor in
  place (`_cube_set_hover`, observer-safe recolor, driven from
  `_on_hover_observer` when the cursor is over the cube region).
  A `StartEvent` observer (`_sync_cube_camera`) mirrors the MAIN camera's
  direction-of-projection + up onto the cube camera so the cube shows the live
  orientation — the cube camera is **PARALLEL projection + `ResetCamera` each
  sync** (×1.25 margin) so the whole cube always fits its small corner viewport
  (a fixed-distance perspective cam OVERFLOWED/cropped it). A left-click in the
  cube region (`_viewcube_click`, checked FIRST in `_pick_display`)
  `vtkCellPicker`s the cube → the hit CELL → its direction (faces + edges +
  corners all clickable) → `_reorient_camera` looks from that direction
  **RELATIVE to the current view** but **SNAPPED to the nearest 90°**: the up is
  the current up projected ⊥ the view dir, snapped to the nearest world axis and
  re-projected (`_snapped_up` over `_relative_up`), so clicking a face lands a
  clean orthographic view (the 90° roll closest to the current one), not an
  arbitrary tilt. Four
  settings-strip glyphs on the right (by the cube): **⟲ 90° / ⟳ 90°**
  (`_on_roll_left`/`_on_roll_right` → `camera.Roll(±90)`), **⌂ Home**
  (`_on_home_view` = default isometric + zoom-extents), **⛶ Zoom Extents**
  (`_on_zoom_extents` = refit, keep angle). All elementwise math (no BLAS `@`);
  every step try/except-guarded → any failure sets `_viewcube_failed` and the
  viewport still works. No GL in the dev env → snap/relative-up logic is
  unit-tested; the actual widget is user-live-tested. **All four camera moves
  (cube click, roll, home, zoom) ANIMATE** via `_animate_to` — snapshot start +
  end poses, interpolate ELEMENTWISE over `_anim_duration_ms` (~260ms) on a
  QTimer (`_anim_enabled` gate; a new move cancels the in-flight one). **The end
  pose is computed with `self.plotter.render` STUBBED to a no-op** (item 10) —
  `apply_end()` (view_isometric / reset_camera / roll) mutates + paints the camera,
  which the user saw as a jump-to-end-and-back before the animation; suppressing the
  paint while snapshotting the end pose means only the animation is visible. Position/
  focal/parallel-scale lerp; the view-up nlerp+renormalises, and HOLDS the end
  up when start/end are near-antiparallel (a 180° roll) so a frame is never
  degenerate. Each `tick` is try/except-guarded to stop the timer and land
  EXACTLY on the end pose on any error. (This REPLACED `vtkCameraInterpolator`,
  whose linear view-up blend hit zero magnitude at the midpoint of an
  antiparallel roll → a degenerate camera → a persistent BLANK viewport when
  the unguarded tick then threw and the timer looped on the bad pose — the
  "clicking the viewcube clears everything" bug.) TODO: expose enable +
  duration in a settings menu.
- **Face-hover highlight (Edit Bodies "Face" tool)**: `set_face_hover_mode(on,
  tri_faces)` — instead of a point dot, the whole face under the cursor is
  highlighted. A copy-of-mesh overlay (`_ensure_face_hl_actor`, created in a
  SAFE context on mode-enter) carries a per-cell RGBA `face_hl` array; the move
  observer (`_face_at` → nearest visible cell → `tri_faces[cell]` → face index)
  recolors that face's cells IN PLACE (`_set_face_highlight`, observer-safe like
  the edge/handle highlights). Cleared on tool cancel/test and in `clear()`.
- **Selected-node origin**: X/Y/Z triad at the selected component's world frame
  origin (`show_component_origin`), driven by `SelectionController`; toolbar
  "Show Component Origin" toggle (global `origin_indicator`, default on). Rendered
  ON TOP of geometry (never occluded) via `_draw_on_top` (coincident-topology polygon
  offset); arrow length = 6% of the bbox diagonal. **The triad reflects the
  component's ACTUAL local frame ORIENTATION, not just its origin point**:
  `SelectionController._primary_frame` returns `(origin, axes)` where `axes` rows =
  the world directions of the node's local X/Y/Z (= the COLUMNS of
  `comp.transform[:3,:3]`), passed as `show_component_origin(origin, axes)`. Before
  this, `_primary_origin` returned only the point and the call omitted `axes`, so
  `_triad_poly`/`_add_triad_cones` fell back to the EXPORT orientation (identity =
  world axes for Main/assets) — the triad ALWAYS looked world-aligned even after a
  custom Set-Origin basis (the "Set Origin orientation shows global" bug, in BOTH
  Main and the asset since they share one `SelectionController`). The bake was
  correct (`apply_origins` stores `basis_matrix(xdir,axis)`); only the indicator
  was wrong. NOTE (Option 1b): in an ASSET whose ROOT declared the origin, the
  asset root is authored at IDENTITY (de-rotated into the robot's coords), so its
  triad is CORRECTLY world-aligned in the asset's own space — that IS the robot
  frame; child parts show their real orientations. Also: `transform_origin_frame`
  now rotates `xdir` (it dropped it, corrupting a custom basis whenever a
  Source→Main orientation/datum made the conversion non-identity).
- **Toolbar is ONE row** (`_build_toolbar`): COMMANDS only, in order —
  **Rebuild**, separator, **Recolor Registry…** (`RecolorDialog`), the
  eyedropper labeled **"Recolor"** with its icon. **Transform Source is NOT a
  toolbar button** — it's reached via each Model Tree row's right-click menu
  (Main / Static / asset); `_open_transform_source` stays, invoked by
  `restructure_requested`.
  - **Rebuild** REPLACES the old Show 3D / Clear 3D pair: it re-tessellates +
    re-renders the active model at the current visual quality, and is ENABLED
    ONLY when the render is stale (`_render_stale()` → `_refresh_rebuild_action`:
    loaded, not busy, not `_pending_show3d`, AND (nothing rendered OR the mesh
    cache is stale for the active variant/quality)). Model switches, geometry
    bakes, and a visual-quality Apply all AUTO-rebuild (`_pending_show3d` /
    `_request_quality_rebuild`), so Rebuild rarely lights up — it's the
    genuine-miss escape hatch. `_refresh_rebuild_action` is called from
    `_set_busy`, the cached render fast-path, and the quality-change path.
  - **Recolor Registry…** = the former "Global Recolor" (renamed action +
    dialog title "Recolor Registry - Global Per-Color Overrides"); the
    eyedropper action (label "Recolor") is unchanged.
  - Up(Z)/Z-rot/Set Z-Origin live in the Transform Source window.
- **Per-viewport settings strip + ViewSettingsBus** (`src/gui/view_settings.py`
  + `ViewportPanel._build_settings_strip`): a compact row at the TOP of EVERY
  ViewportPanel (main window + every editor window) — an **"Adjust Visual
  Quality"** button (LEFTMOST), **Show Shaded** (was "Show Bodies" — the shaded
  tessellated surfaces; `set_bodies_visible`), **Show B-Rep Edges** (was "Show
  Edges" — the topological feature-edge overlay; `set_edges_visible`), **Show Tess
  Edges** (NEW, default off — the full triangle-mesh wireframe overlay;
  `set_tess_edges_visible`, persisted `GlobalConfig.show_tess_edges` + bus field
  `show_tess_edges`), Show Component Origin / Show Global Origin / **Perspective**
  toggles, Opacity slider — ALL bound to the ONE `ViewSettingsBus` MainWindow owns
  (module-level default via `set_default_bus`; panels SELF-ATTACH in `__init__`,
  zero constructor plumbing).
  - **Perspective** (`viewport.set_perspective`) toggles perspective
    (vanishing-point) vs the DEFAULT orthographic projection (`enable_/
    disable_parallel_projection`; re-applied after every `load`). PERSISTED
    file-wide (`GlobalConfig.perspective`, default False → ortho), bus field +
    `_on_view_setting_changed`.
  - **Mesh quality moved OFF the strip into a MODAL** (`Adjust Visual Quality`
    button → `src/gui/visual_quality_dialog.py` `VisualQualityDialog`,
    Apply/Cancel, two whole-number spinboxes Linear mm / Angular deg). Apply
    pushes both onto the bus (`bus.set("deflection"/"angular_deg")`); the
    button/handler live on `ViewportPanel` (`_open_visual_quality`) so EVERY
    viewport (main + editor windows) has it. A quality change is a real user
    edit → MainWindow's `_on_view_setting_changed` now HANDLES
    `deflection`/`angular_deg` (was a no-op): persists to `GlobalConfig`
    (`_save_config`) + coalesces the two bus edits into ONE auto-rebuild of the
    MAIN viewport (`_request_quality_rebuild` → 0-timer → `_do_quality_rebuild`;
    if busy, sets `_pending_show3d`). Editor windows adopt the new quality on
    their NEXT open (they snapshot it at open) — the modal drives the main
    viewport's live re-mesh only.
  - An edit in any strip → `bus.set` → every panel re-syncs its strip and
    applies the live effects itself (opacity, origin indicator, edge VISIBILITY
    where an overlay exists); MainWindow listens too and persists the
    GlobalConfig-backed fields + runs the edge BUILD flow (`_apply_edges_toggle`)
    and the selection-aware global-origin marker. `bus.seed(gs)` on every model
    commit emits `changed("*")` — NOT a user edit (no writes/builds). Windows
    whose owner drives `set_scene_origin` themselves set
    `viewport.owns_scene_origin = True` so the strip's Global Origin toggle
    doesn't fight them. `show_global_origin` + `opacity` are transient
    (bus-shared, never persisted).
- **Error dialogs with a Copy button** (`MainWindow._error_box(title, text)`):
  a custom modal `QDialog` (critical icon + read-only SELECTABLE `QPlainTextEdit`
  + a non-closing **Copy** button that grabs `"{title}\n\n{text}"` + Close),
  used for the worker-failure criticals (Generate Assets / Restructure / Export
  / load / parse) so tracebacks paste cleanly into a report. QMessageBox closes
  on any button, so a custom dialog was needed to keep Copy non-terminal.
- **Measure tool** (NEW — settings-strip checkable **"Measure"** button on EVERY
  `ViewportPanel`, `make_icon("measure")`; offscreen-verified, GL live-test
  PENDING): pick TWO vertices via the viewport's OWN Construction Geometry Builder
  (VERTEX mode, one Accept each — `set_measure_mode` connects the CGB's
  `constructionFinished`, stores P1, re-arms for P2, then draws + **re-arms P1 for a
  fresh measurement** — continuous). Defaults to **EDGE-endpoint vertex snapping**
  (End/Mid/arc-Center; the pickable edge layer is PRE-CALCULATED — see the
  edge-pick pre-calc bullet below — so it no longer freezes; `cg.set_vertex_snap`
  can override the CGB's default, and `_slot_spec` honours it). Draws the direct
  P1→P2 line (yellow) with the
  **total distance in METERS** + a tip-to-tail **X/Y/Z staircase** (P1→+dx→+dy→+dz,
  colored X-red/Y-green/Z-blue via `_AXIS_RGB`) each labeled with its component
  length. Distance = source-mm × `measure_scale` (set by the owner from
  `_export_scale()`, default 0.001). Labels are **net-new 3D text** with a WHITE
  background box, ALWAYS ON TOP of all lines/geometry
  (`add_billboard_label` → `plotter.add_point_labels(always_visible=True,
  shape_color="white", fill_shape=True)`; dark text for the total, axis-colored for
  X/Y/Z) AND the four values are emitted (`measurementMade` signal)
  to the status bar (**Both**). All lines via `_add_measure_line`/`_make_sphere`/
  `_draw_on_top` (no BLAS). Mutually exclusive with the other tools
  (`measureModeChanged` → MainWindow ends the joint/transform commands + eyedropper;
  those ending call `set_measure_mode(False)`); Esc/uncheck clears (`clear_measure`;
  nulled in `clear()`). Viewport-owned + self-contained → works in editor-window
  viewports too.

