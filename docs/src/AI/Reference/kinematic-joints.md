# Kinematic joints

Defining prismatic/revolute/fixed joints on generated models and authoring them into USD (`UsdPhysics` + drives + optional limits + articulation): the per-model `joints` config map + `JointDef`, the GUI Create-Joint flow + Edit pane + gold-hexagon glyph, the magenta viewport viz, and `usd_writer._author_joints` (world-aligned axis, "Joints" scope, articulation/rigid-body-never-on-root rules). Read when touching joint definition, viz, or USD joint authoring. Verify against `src/`; may lag.

---

> ⭐ **Joints that "disappeared" are usually a SYMPTOM, not a joint bug.** The `joints` map is
> keyed by Body1's **main-stage path**, so if the bodies stop existing — most often because a
> generated model's Edit-Bodies recipe was DROPPED when its subtree's membership changed —
> every joint dangles at once. The `JointDef`s survive in the config and return the moment the
> bodies do. Check the model's recipe first (`scratchpad/probe_b2_restructure_damage.py`), and
> read the **BLAST RADIUS** section of `restructure-and-transform-source.md`.

> **Redesign update (authoritative: `selection-and-cgb.md`).** `JointDef.axis` is now a **free world-frame unit vector**, not an `"X"/"Y"/"Z"` token (legacy strings migrate to vectors); the joint pane gained a **"Pick Axis…"** CGB picker alongside the X/Y/Z combo (which stores the aligned vector). USD authoring: an axis-**aligned** pick stays byte-identical to before; a **free** vector orients the joint's local +Z along the axis. The `"GLOBAL X/Y/Z axis"` phrasing below predates this.

## Kinematic joints (prismatic/revolute → USD; NEW — headless-verified, GUI/GL live-test PENDING)
Define **prismatic** / **revolute** / **fixed** joints (with USD drive APIs +
optional limits) on tree nodes of a **GENERATED** model (an asset OR Static —
NEVER Main/Source), and author them into the USD export. The selected node is
**Body1** (moving link). **Revolute/prismatic REQUIRE a Body0** (a real parent —
ANY component-tree node, assembly or body, EXCEPT the model ROOT); a **fixed**
joint may leave Body0 unset → it grounds Body1 to the **WORLD**. The model ROOT
node can NEVER be a joint body (making it a rigid body would nest the articulation
root). The joint is LOCATED at Body1's ORIGIN; a motion joint's **axis** is a
**GLOBAL (world) X/Y/Z** aligned with the Show-Global-Origin triad (NOT Body1's
local frame) — **Flip** negates the + direction. Each joint has a user **name** =
its authored USD prim name.
- **EXPORT METADATA ONLY — NOT a geometry bake input.** Applying/removing a joint
  writes config + refreshes the indicator/viz and does **NOT** rebuild the model
  (far lighter than origins). The location is NOT stored — it is re-derived from
  the component's baked `transform` at export (so it auto-tracks a later
  Set-Origin).
- **Config = a per-model `joints` map** on `ModelConfigStore`
  (`get/set_joint_map`, `_get/_set_raw_map(model,"joints")` — mirrors
  `origins`/`splits`; deliberately EXCLUDED from `has_geometry_edits` so it never
  triggers a rebuild). Keyed by **Body1's ACTIVE (main-stage) `/`-rooted path**
  (NOT the base tree — joints don't bake, and the exporter loads the same main
  stage, so resolution is exact with no `_resolve_base_path`). Value =
  `geometry_edits.JointDef` (`joint_type` = revolute|prismatic|**fixed**, `name`
  (joint prim name), `body0` path — **`""` = WORLD, valid only for a fixed joint**,
  `axis`, `flip`, `stiffness`=50000, `damping`=1000, `limit_enabled`,
  `lower`/`upper`) + `load/dump_joint_map`.
- **GUI** (`main_window`): a **"Create Joint"** context-menu flyout
  (Prismatic/Revolute/**Fixed**) on a jointless node, **"Edit Joint…"/"Remove
  Joint"** on a jointed one — single-selection, gated to `active != MODEL_SOURCE`
  AND NOT the implied ROOT (`_node_has_joint`; the root can't be a joint body). A
  right-side **Edit pane** (splitter index 2, hidden until a command is active —
  sized only WHEN shown so the maximized window can't squeeze it; modeled on the
  Component Editor's pane): **Name** (a `QLineEdit`, pre-filled `{Body1}_joint`) ·
  **Joint Root** (a **"Body"** `QToolButton` — the standard selection convention:
  `make_icon("body")`, checkable/activated when set, right-click **Clear**;
  clicking ARMS Body0 picking and the NEXT component-tree selection — a tree click
  on ANY node incl. an ASSEMBLY, OR a viewport Body pick via the sink — is captured
  (`_on_joint_pick_body0`/`_joint_capture_body0`, rejecting Body1 itself, the ROOT
  node, + any no-path node). **Revolute/prismatic REQUIRE Body0** (unset →
  "Body… (required)", Apply disabled); a **fixed** joint may leave it unset →
  "World (default)" and HIDES the Orientation/Flip/Limits/Drive groups (no motion)
  · **Orientation** (axis combo) ·
  **Flip** · **Limits** (opt-in checkbox, default OFF, + Lower/Upper spinboxes
  in ° for revolute / **m** for prismatic; first enable SEEDS full-range defaults —
  **±179°** revolute / **±1 m** prismatic — only when still at the unset 0/0, so a
  disable→re-enable keeps custom values) · **Drive** (stiffness/damping) ·
  Apply/Cancel (both hide the pane; Apply persists, NO rebuild). `_start_joint`/
  `_on_joint_apply`/`_remove_joint`/`_end_joint_command`; torn down on model
  switch (`_commit_model`) + Esc. Tree indicator = a **gold HEXAGON**
  (`tree_panel.JOINT_ROLE` / `_JOINT_COLOR`, `set_joint_nodes`), resolved in
  `_refresh_geometry_edit_indicators`.
- **Viewport viz** (`viewport_panel`, all elementwise / `vtkConeSource` only;
  vivid **magenta** `_JOINT_VIZ_COLOR` — visible vs the gradient bg + distinct from
  select-orange/hover-blue; the tree badge stays gold): **prismatic** = a line
  shaft + cone arrowhead along the (flipped) GLOBAL axis (the main viewport is
  identity-oriented, so the world axis is the plain unit vector — matches the
  global-origin triad); **revolute** = a partial arc + cone showing + rotation,
  PLUS a dash-dot **rotation-axis centerline** through the origin (static — shows
  the pivot axis; `_apply_centerline`, not drag-updated); **fixed** = a small
  3-axis "anchor" cross at the origin (no motion, `_build_fixed_viz`).
  Prismatic limits are UI **metres** → converted to source units for the viz
  (`_export_scale`). With limits, two
  **draggable end-glyphs** (the handle layer) mark lower/upper and the
  shaft/arc spans them; dragging updates the pane spinbox and vice-versa (two-way).
  `show_joint_preview` (safe rebuild) / `update_joint_preview` (IN-PLACE, drag-safe
  — fixed topology: 2-pt line / 48-pt arc, so points update without actor churn) /
  `clear_joint_preview`; the drag routes `on_handle_drag`→`joint_limit_from_drag`
  (prismatic = closest-point-on-axis distance; revolute = ray∩plane polar angle),
  `on_handle_drag_end`→full rebuild. Shown WHILE the command is active. **ALSO a
  READ-ONLY preview when a jointed node is merely SELECTED (not being edited)**:
  `MainWindow._refresh_selected_joint_viz` (piggybacked on `_update_scene_origin`,
  so it fires on every selection change + after every render, plus right after a
  joint Apply/Remove) builds the spec from the STORED `JointDef`
  (`_joint_spec_from_def`, mirrors `_joint_spec`) for the primary selected node's
  joint and calls `show_joint_preview(spec, interactive=False)`; nothing/non-jointed
  selected → `clear_joint_preview(clear_handles=False)`. **`interactive=False`**
  draws the glyphs (arrow/arc/anchor + the shaft/arc spanning the limits) but NO
  draggable limit handles and NEVER touches the handle layer (`_joint_readonly`
  gates the `set_handle_data` calls; `clear_handles=False` on the clear) — so an
  active CGB/Measure command that owns the handle layer is undisturbed. Skipped
  while a joint command is active (`_joint_cmd is not None` → the command owns the
  viz). So opening an asset and selecting a jointed link shows its joint glyphs
  without entering Edit Joint.
- **USD authoring** (`usd_writer._author_joints`, inside `_author_components`):
  each Body1 is auto-added to `origin_frame_cids` (so `frame_of[body1]` gives its
  prim frame + meter-space origin). The joint frame is **WORLD-ALIGNED at Body1's
  origin** — rotation = the export/global axes (`export[:3,:3]/scale`, unit scale),
  translation = Body1's origin — NOT Body1's local rotation, so the motion axis
  matches the global origin. `localPos/localRot` for each body = that world-aligned
  frame relative to the body's own prim frame (`local1 = inv(frame_of[body1])·Jw`
  counter-rotates Body1; flip = a 180°-about-perp pre-rotation). **All joint prims
  live under a single "Joints" scope** (`UsdGeom.Scope` under the top prim), each
  named by its `name` (sanitised + deduped). **Three types**
  (revolute/prismatic/fixed): revolute/prismatic REQUIRE a real Body0 (both bodies
  become rigid bodies); a **fixed** joint may omit Body0 → an EMPTY body0 rel
  (WORLD). The ROOT prim is NEVER a joint body / rigid body (no nesting). Authors
  `Body0/Body1` rels; motion joints add `axis`, opt.
  `Lower/UpperLimitAttr` (revolute = degrees; prismatic = METERS, authored as-is —
  the UI is meters, `metersPerUnit=1`; the VIEWPORT viz converts m↔source units
  since it renders source geometry), and a `DriveAPI` ("angular"/"linear", type
  "force", stiffness/damping, targetPosition 0). **When a model has ≥1 joint the
  export becomes a drivable articulation** — `ArticulationRootAPI` on the top/
  default prim + `RigidBodyAPI` on every referenced body (Body0 + Body1; NEVER the
  root). **Grounding is the user's explicit fixed joint — NOTHING is auto-added**
  (no mass/collision — Isaac defaults). **A jointless export authors NO physics → byte-identical to
  before** (the regression guard). Threaded through `write_subtree_usd`/
  `write_model_usd` and populated in `usd_cli`/`compose_cli` (resolve the joint map
  to cid pairs next to the frame-set build; composed asset files carry their joints
  and compose through the payloads — `main.usda` is unchanged). OBJ/STEP ignore
  joints (no concept). Only **core `UsdPhysics`** is authored — `PhysxSchema` is
  NOT in `usd-core`, so no Isaac-specific PhysX attrs.
- **v1 limits**: joints are main-stage-path keyed, so a later restructure that
  MOVES a jointed (or Body0) node stales the key → dropped + logged on export
  (rig AFTER restructuring). Revolute limit-glyph drag is awkward edge-on (text
  inputs are the fallback). **NESTING**: the ROOT is no longer a joint body, so the
  root-nesting is solved; but RigidBodyAPI still goes on every picked body with NO
  prim-tree check, so picking a jointed ANCESTOR+DESCENDANT pair among the links is
  still nested (keep links as SIBLINGS). A world-grounded base is now the user's
  explicit **fixed** joint (world→base LINK), not an auto-added root joint.
- **Verified headless** (`scratchpad/joint_test_*.py`, 94 checks): `JointDef`/map
  round-trip (incl. `name`, the `fixed` type + empty-`body0` world) +
  `get/set_joint_map` on an asset section (17); USD authoring — joint
  prims/rels/axis/drive/limits (revolute deg, prismatic m authored-as-is)/
  articulation + the "Joints" scope + named prims + the user fixed joint
  (world→body) + a skipped invalid motion joint (no Body0) + the ROOT NOT a rigid
  body + the WORLD-aligned frame (rotated Body1) + the jointless byte-identical
  guard (35); viz frame + drag math (10); the REAL MainWindow command flow
  offscreen — menu gate, Body-button convention, assembly/leaf Body0 capture, ROOT
  rejected as a body, fixed-joint world default + hidden motion groups, required
  Body0 for motion joints, Name field, ±179°/±1 m limit defaults, m→source viz
  conversion, Apply→config, Edit reload, Clear, Remove (32). GL rendering + picking
  + the live pane are USER live-test (no GPU in this dev env).

