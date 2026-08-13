# Geometry edits — Edit Bodies (Component Editor) · Custom Origins · Component Transform

The per-model geometry edits that bake into a model's `.xbf`: the op-sequence Edit Bodies / Component Editor (split / merge / decompose / transform / delete with stable lineage-ids), Custom Origins / Set Origin (`OriginFrame`, folder origins, USD live joint Xforms), and the whole-subtree Component Transform — plus the shared bake order (splits→origins→transforms→structure→orientation) and engine. Read when touching `geometry_edits*`, the Component Editor window, origins, or transforms. Verify against `src/`; may lag.

---

> **Redesign update (authoritative: `selection-and-cgb.md` — read its ⭐ Terminology table first).** The Component-Editor **ReOrigin** and **Transform Move-Point** picks now run through the shared `cgb_command.CgbCommandBinder` (via `CgbSlotButton`), which fixed the `"vertex"`→`"point"` rename bug in both handlers; the main-window command (`origin_window`) is migrated onto the same binder and **renamed "Set Origin…" → "ReOrigin…"** (matching the Component Editor). **Terminology below is stale where it says "Basis"/"Vertex":** the CGB's 4th builder is now the **Frame** (internal token `basis`), consumed for its axes alone as an **Orientation**; every button was relabelled accordingly — "Basis"→**Orientation**, "Vertex"→**Point**, "From / To Basis"→**From / To Orientation** (Component Editor + main-window Transform). The main-window ReOrigin pane also **REMOVED its "Origin Orientation Source" Global/Custom group** (the source is inferred: no Orientation ⇒ Global, an Orientation ⇒ Custom — only the Point is required to Apply) and fades the existing origin indicator to 25% while the Orientation is picked. Occurrences of "Set Origin" below refer to the same command. The pre-redesign hand-rolled `_request_cgb`/`_on_cgb_finished` descriptions below are superseded for those pick flows (the full binder-dedup of `edit_bodies_window` is a documented follow-up).

## Geometry edits — Edit Bodies (né Split Bodies) + Custom Origins (Features C+D; backend + GUI logic COMPLETE, headless/offscreen-verified; user live-test PENDING)
**NAMING:** the user-facing feature is **"Edit Bodies"** (rename); the
model-layer names (`SplitRecipe`, `run_split`, …) and the config key
`"splits"` are the DURABLE format and intentionally KEEP the historical name
(renaming would break saved configs).
Two config-driven, per-model geometry edits that BAKE into the model's `.xbf`
variant (schemas `src/model/geometry_edits.py`, pure; engine
`src/io_step/geometry_edits_build.py`, Qt-free). Raw config maps `"splits"` /
`"origins"` follow the `structure` precedent exactly (top level = base model,
`assets[Name]` sections; keyed by `/`-rooted tree PATH; strict load; round-trip
untouched by `_minimize_raw`; store accessors `get/set_split_map`,
`get/set_origin_map`, `has_geometry_edits`).

- **BAKE ORDER = SPLITS → ORIGINS → STRUCTURE → root frame LAST, everywhere**
  (main bake in `restructure_build` AND per-asset/Static post-passes in
  `assets_build`, via the shared `apply_geometry_edits`): bodies exist BEFORE
  the structure map runs, so THE SAME model's restructure can group its own
  bodies into link folders (E2E-verified). Consequences: **all three maps are
  keyed against the model's PRE-STRUCTURE base tree** (root source
  stage+bodies for Main; pruned subtree+bodies for assets) — split/origin maps
  need NO re-keying when the structure map changes (the pre-structure tree is
  invariant); the Transform Source window shows the UNSPLIT tree (its
  structure maps reference only non-body paths — a split LEAF keeps its path
  after in-place conversion, so moving it carries its bodies; bake-verified
  on mockHopper), while `_resolve_base_path` still gets split stubs injected
  (`_build_edit_base(with_bodies=True)` — positional translation of
  active-model cids needs the with-bodies planned tree); GUI current-path →
  base-path translation
  (`_resolve_base_path`) is positional through `plan_tree` when a map is
  applied (planned tree == active walk 1:1). `_launch_main_bake`'s plan
  carries the FULL Source→Main inputs (`store.source_to_main_inputs`); recipe
  GEOMETRY is source-frame — see `pipeline-and-caching.md` (frame conversion).
- **Split recipe** (`SplitRecipe{cuts, body_count, bodies{index→name},
  cut_face_color, merges, assembly_color_mode, body_origins}`; `body_origins` =
  `{final-body-index→OriginFrame}` for per-body Set-Origin (baked via the origins
  map — see the Edit Bodies GUI); `assembly_color_mode` =
  `"faces"|"base"|None` — the ASSEMBLY merge-then-edit color mode, TEMPORARY
  chooser, default-omitted so leaf recipes are unaffected; `Cut` = kind +
  world-frame plane `origin/normal/xdir` +
  BOUNDED UV extents + **`shape` ("rect"|"disc") + `diameter`** + provenance):
  planes stored in the MODEL's SOURCE-STAGE world frame with an explicit
  `xdir` so extents are reproducible; the tool-face OUTLINE is either the UV
  rectangle or a CIRCLE of `diameter` around the origin (`_tool_faces_local`
  builds the disc from a `gp_Circ` wire → `MakeFace(wire, True)`; identical
  splitter semantics — full crossing severs, partial imprints, `Modified()`
  color history intact — probe-verified). `shape`/`diameter` default-omit in
  the dump so existing rect configs are untouched; `diameter` is
  rotation-invariant, so `transform_cut` needed no change. Bounded cuts are
  REQUIRED either way (a full plane severs unrelated limbs of concave bodies —
  P2). `body_count` is recorded when the
  user Tests; the bake FAILS LOUD on drift (source geometry changed).
  **A ZERO-CUT recipe is VALID**: it
  DECOMPOSES a multi-solid leaf (a compound holding several solids — e.g.
  testB1's M-710iD70 leaf = 15 solids × 6 occurrences) into its existing
  solids; `run_split` then skips the boolean splitter and serves
  `_IdentitySplit` (same body ordering; `Modified()` empty → every face keeps
  its own color). **`merges`** = JOIN groups applied AFTER all cuts
  (`apply_merges`, bake + window Test): each group of PRE-MERGE body indices
  becomes ONE body — a COMPOUND of the members (pure grouping, NO boolean, so
  non-touching solids join and faces keep identity/colors); the final list
  re-sorts by `_body_key` and `body_count`/renames key off FINAL indices
  (window UI: "Join:" row — Merge Selected / Unmerge Selected; a
  no-selection Unmerge dissolves ALL merges, the escape from
  everything-merged-into-one; merged-bake verified on mockHopper).
  **Body NAMES are keyed internally by the body's PRE-MERGE member tuple**
  (`_name_key`/`_body_label`/`_adopt_loaded_names`), NOT the final index — a
  merge only re-sorts the final indices, so a final-index-keyed name would jump
  to the wrong body (the "names switch bodies" bug). Custom names carry through
  merge/unmerge; the recipe's `bodies` map is still FINAL-index keyed (built from
  the member-tuple store at Apply — what the bake wants). Loaded final-index
  names convert on the first Test.
  **Body identity = sort by (volume, centroid) rounded**
  (`body_sort_key`) — OCC's result-compound order is NOT guaranteed stable;
  never trust it. Splitter recipe (`run_split`): `BRepAlgoAPI_Splitter` +
  bounded `BRepBuilderAPI_MakeFace(gp_Pln(gp_Ax3(o,n,x)), u±, v±)` tools,
  `SetNonDestructive(True)`, `SetRunParallel(False)`, fuzzy 1e-5.
- **⭐ `is_effective()` — what makes a recipe APPLICABLE (current, op-sequence
  format).** `len(final_ids()) >= 2 or bool(ops)`. Two INDEPENDENT ways to
  qualify: **≥2 final bodies** (a zero-op decompose of a multi-solid leaf, or any
  split), **or ANY op at all**. The second clause is what lets an op sequence land
  on ONE final body and still be a real edit — **merge-ALL-into-one** (fuse a
  leaf's / an assembly's N solids into a single body), **delete-down-to-one**, and
  a **transform of the lone body**. Gating on the body count alone silently
  disabled the Component Editor's window-level Apply for those and dropped the
  recipe on `dump_split_map` (edit vanishes + reverts). Only a genuine no-op — one
  body, zero ops — is ineffective. The window's Apply button calls this SAME
  predicate (`_update_apply_enabled` → `self._recipe().is_effective()`), so the GUI
  gate and the bake gate (`resolve_split_targets`) can never disagree.
  Probe-verified: `run_body_ops` on a 3-box compound with a merge-all op returns
  one final body (`o0:0`) holding 3 solids, and the recipe round-trips through
  `dump_split_map`/`load_split_map`.
- **Split bake = IN-PLACE product conversion (probe P4b — better than
  replace-instance)**: body products are `AddShape`d + `AddComponent`ed onto
  the split leaf's OWN product label, turning it into an assembly WITHOUT
  touching its instance — sibling order preserved (replace-instance APPENDS =
  reorder), and a multi-instanced product splits consistently in every
  occurrence (recipes resolve per-PRODUCT — `resolve_split_targets` rejects
  conflicting recipes on two occurrences). Colors: result faces inherit their
  source face's color via `splitter.Modified()` history; NEW cut faces get
  `cut_face_color` or the AREA-DOMINANT color of the original body; each
  `BodyInfo` carries its own product ENTRY so `assign_body_colors` matches by
  IDENTITY (bodies survive being moved by the structure map).
  `split_stub_assembly` predicts the post-split walk purely (body stubs carry
  SYNTHETIC entries `stubbody:{parent_entry}:{i}` — planners require entries;
  keyed off the parent's entries so occurrence counts mirror the real doc).
- **Origin frame** (`OriginFrame{origin, axis|None, xdir|None}`, world frame; axis
  → local **+Z**. With **`xdir`** (local +X, from a CGB Basis — item 48)
  `matrix4()` uses `orientation.basis_matrix(xdir, axis)` for the exact X/Y/Z;
  WITHOUT it, `axis_frame_matrix` gives the minimal-rotation Z-only completion,
  Rodrigues, elementwise): bake (`apply_origins`) = instance location `L·T`
  with `T = W⁻¹·F`; an ASSEMBLY re-origins by pure child-location surgery
  (`loc' = T⁻¹·loc`, zero color risk — P5a); a LEAF gets its product geometry
  replaced (`BRepBuilderAPI_Transform` + `SetShape` — **face enumeration order
  survives a rigid transform (P3), so the face-index color sidecar stays
  valid**; the leaf's cached MESH does NOT — `apply_geometry_edits` strips it
  for re-tessellation). World geometry never moves (verified to 1e-6 after
  every bake). **Multi-instanced targets now BAKE** (a body/link joint frame on
  a prototype used more than once): `apply_origins` re-origins the shared product
  ONCE (leaf geometry `T⁻¹·G` / assembly child-location surgery) and compensates
  EVERY DISTINCT instance label by the same product-local `t_loc`, so all
  occurrences keep their world geometry; the joint frame becomes a PROPERTY OF
  THE PROTOTYPE (every occurrence's frame moves to its own `W_k·t_local`, all of
  which are recorded in `expected` so `verify_origins` checks them rather than
  flagging drift). It flows into each asset via pruning. (`skip_shared` is a
  no-op now; a second/conflicting origin on the same product is skipped +
  reported.) After baking, the
  component's local frame IS the joint frame → origin=Local exports work in
  all three formats with zero new export code. Assets carry NO pose bake at
  all anymore (prototype rework — the old frame-EQUALITY `root_declared`
  matching is GONE), so an asset rooted at a declared frame is authored IN
  its joint frame naturally (root at identity), and the composed placement is
  still just the occurrence's Main-walk transform (the origins bake already
  rewrote it). Main-level frames inherited by pruned assets become the
  asset's own frame for free.
- **USD live joint Xforms** (`usd_writer` `origin_frame_cids` + `usd_cli`):
  a frame'd component's prim carries ONE **RIGID meter-space transform op**
  (`_frame_meter_rigid`: rotation = orientation·R_f unit-scale, translation =
  frame origin through the full export transform; nested frames compose
  relatively; Gf is ROW-vector convention — transpose on write, basis vectors
  are the ROWS on read); its subtree's points are authored RELATIVE
  (`inv_rigid(frame)` applied after the usual full bake) so the composed stage
  is IDENTICAL to the fully-baked form (verified 2e-7 m over 1909 meshes)
  while the joint frame stays live for rigging. Everything else stays
  baked-into-points (reference-safety unchanged). usd_cli (and compose_cli)
  derive the frame SET from the model's origin map UNION
  `geometry_edits.body_origin_paths(split_map)` — the per-body origins in
  `SplitRecipe.body_origins` are injected into the origin map only at bake (not
  persisted), so exporters MUST reconstruct their paths (`body_path(split,
  name)`, the same normalized join the bake uses) or body/link joint frames get
  no live Xform. The frame VALUES come from `comp.transform` (authoritative
  post-bake). **For a GENERATED model (asset/Static) the frame set ALSO unions
  `model/live_frames.inherited_frame_paths(store, model, stamp)`** — frames
  authored at ROOT bake into Root.Main and flow into the asset by PRUNING, so
  the asset's OWN origin/split maps are empty and the naive `origin_map |
  body_origin_paths` yields nothing (the "asset export drops the body origins,
  bodies fall to the assembly origin" bug). `inherited_frame_paths` reconstructs
  the ROOT frame paths (`origin_map(SOURCE) | body_origin_paths(split_map(
  SOURCE))`) and TRANSLATES them into the model's own tree: for an asset, strip
  the canonical-occurrence prefix (from the assets-stamp `occurrence_paths`) →
  occurrence-relative path; for Static, keep root paths NOT under any removed
  asset occurrence. So an asset/Static export authors the SAME live Xforms as a
  Root.Main export of the same occurrence. Both `usd_cli` and `compose_cli`
  union it (pxr-E2E verified — `test_asset_export_frames`: the asset USD's body
  prim carries `xformOp:transform`).
- ⭐ **`model/live_frames.live_frames_and_joints(store, model, step_path, asm)` is
  the ONE derivation of "which components own a live frame, and what are the
  resolved joints".** It was `export/frame_paths` until CS-162 moved it to the
  model layer: the GUI needs the identical set to validate Simplify-Bodies marks
  (`export.md` § *Simplify Bodies*), and `src/gui/` must not import `src/export/`.
  It is pure — no OCC/VTK/pxr, only `io_step.cache` for the bake stamps. `usd_cli`
  and `obj_cli` call it; `compose_cli` still assembles the set inline because it
  additionally DISCARDS the single root (the occurrence placement carries that
  frame). **Do not add a second derivation** — a mark that is fatal for USD must
  be fatal for OBJ, and the click-time dialog must agree with both.
- **GUI**: **Edit Bodies lives in the Transform Source window's context menus**
  (both trees + viewport, single leaf) — recipes land PENDING in the window's
  working copy of the split map, are validated on the window's ONE Apply, and
  bake with the structure map (+ root settings) in a single rebuild.
  `_on_edit_bodies_applied` now `_rebuild_edit_tree(current_map())` so an
  assembly recipe collapses (hides) its children — and its whole prototype
  group's — in the edit tree IMMEDIATELY (and a cleared recipe restores them),
  no re-open needed. The main
  window's context menu no longer carries body-edit items. "Set Origin…" /
  "Clear Origin" STAY in the MAIN window's context menu (single selection;
  origins are per-asset joint frames picked on the baked geometry); a
  Main-level origin edit warns that a successful Apply clears generated
  assets, then `_apply_geometry_edit` (map entry + rollback closure —
  `_restructure_rollback` is a CALLABLE) → `_launch_model_rebuild`.
- **Set Origin on a RESTRUCTURE FOLDER (joint frame for a link; NEW —
  real-OCC + pxr-E2E verified on testC1, GUI live-test PENDING).** A folder is a
  synthetic structure-map node with NO base-tree identity, so it can't key the
  origin map (the old error "a restructure folder can't carry an origin"). Its
  frame instead lives on **`NewAssembly.origin`** (an optional `OriginFrame` in
  the STRUCTURE map, keyed by the folder's `nK` — stable across Applies, dropped
  when the folder is deleted). The DEFAULT/placeholder is the **parent frame**
  (a folder is created at identity relative to its parent, so it ALWAYS has a
  well-defined frame — Set Origin never errors); a custom frame overrides it.
  - **Resolve/store (main window):** `_resolve_base_path` now yields
    `"folder:<nK>"` for a folder (was None); `_open_origin`/`_on_origin_applied`/
    `_clear_geometry_edit` branch on that prefix — read/write the frame on the
    structure map's folder entry (`_apply_folder_origin`), source↔main converted
    exactly like a base-node origin, then `_launch_model_rebuild`. "Clear Origin"
    is offered when ANY origin exists (`_model_has_any_origin` = origin map OR
    any folder origin).
  - **Bake (`restructure_build._apply_folder_origins`, inside `apply_structure`
    → BOTH root + asset builds):** re-origins each custom-frame folder with the
    world-preserving assembly surgery (`_reorigin_assembly_once`, the
    single-occurrence form of `apply_origins`' assembly branch). NESTED folder
    origins work — processed in planned PREORDER using each folder's PLANNED
    (default) world as `W`, which an ancestor re-origin PRESERVES (verified
    order-independent). The planned-tree folder transforms are updated to the
    custom frame so `compare_planned`'s transform check passes. Frame is
    SOURCE-frame (orientation bakes LAST).
  - **Export:** EVERY folder is a live USD joint Xform (custom frame if set,
    else the parent-frame default). The bake records all folder `/`-rooted final
    paths in the bake stamp (`folder_frame_paths`, INFORMATIONAL — ignored by
    `main_rebuild_required`; plus `folder_origin_frame_paths`, the CUSTOM-origin
    subset that drives the tree's teal glyph); `usd_cli`/`compose_cli` union the
    former into `origin_frame_cids` (value from the baked `comp.transform`). A Main-level
    folder pruned into an asset/Static is picked up via
    `live_frames.inherited_folder_frame_paths` (root stamp folder paths →
    occurrence-relative, mirrors `inherited_frame_paths`). STEP/OBJ inherit the
    baked folder PLACEMENT (assembly local frame = joint) automatically — no
    live-Xform concept there.
  - **MESH parity (DONE — mesh-bake + pxr-E2E verified on testD1.obj):**
    `apply_structure_mesh` applies folder origins — TRIVIAL in the mesh model
    (transforms are ABSOLUTE world, so re-origin = `transform = F`; children
    untouched, nested composes for free), and `build_mesh_main_variant` records
    `folder_frame_paths` in the stamp exactly like the OCC bake. Both mesh asset
    paths (`_bake_generated_main`/`_fast_rebuild`) route through
    `build_mesh_main_variant`, so mesh assets inherit it too. The GUI and the
    `usd_cli`/`compose_cli` frame-set code are backend-agnostic (they read the
    stamp + `load_mesh_model`), so nothing else changed. (STEP export/compose
    stays refused for mesh; that's unrelated to frames.)
- **Edit-at-Root-flows-down (body edits; supersedes the earlier "asset owns
  its edits" block).** Root body edits on a to-be-asset part BAKE INTO MAIN and
  the asset INHERITS them by pruning — `source_to_main_inputs` NO LONGER filters
  asset-covered split/origin keys (`drop_asset_covered_keys`/`path_under_any`
  are now unused; the Transform Source `_asset_covering`/`asset_paths` block is
  GONE). The old "split target not found" crash (a Root split AND a separate
  asset-section split on the SAME path) is instead SELF-HEALED at generation:
  `apply_geometry_edits(..., tolerant=True)` (asset/static builds only — the
  Main bake stays strict) DROPS a recipe whose path no longer resolves in the
  pruned tree, logged, rather than raising. **Tolerant mode ALSO drops a recipe
  whose BODY COUNT drifted** — a Main-suppressed part that fed a split is
  physically excluded from the generated model's source stage, so the authored
  count no longer fits (`apply_splits(tolerant=True)`; the post-split
  `split_stub_assembly` prediction is recomputed from only the APPLIED recipes
  so the walk-count check doesn't false-fail). The subtree keeps its surviving
  children un-decomposed; re-author Edit Bodies to re-decompose. **SET ORIGIN
  NOW FLOWS DOWN TOO (Option 1b)** — the old `_open_origin` marked-asset redirect
  is GONE, so a custom origin on a marked-asset part bakes into Main + inherits by
  pruning like body edits (multi-instance is still refused; single-instance +
  the "clears assets → regenerate" warning stay). **When the origin is on an asset
  ROOT, generation DE-ROTATES the asset into that origin frame** — it sets
  `R_root=identity` (`assets_build._build_asset` bakes NO rotation onto the pruned
  root; `mesh_assets_build._build_asset_mesh` rebases by `W_canonical⁻¹`) and
  compose places the occurrence at `W_occ` (`compose_cli` `r_inv=identity`). So the
  asset's WORLD/EXPORT frame BECOMES the robot's coordinate system: opening the
  asset shows the robot **UPRIGHT** in its own frame, with the global-origin
  indicator, the corner gizmo, and the world axes all aligned to the robot; the
  composed world still reproduces Main EXACTLY (robot placed back at its tilted
  scene pose). ⭐ **DESIGN DECISION (user-confirmed 2026-07 — do NOT re-"fix"):**
  in this de-rotate design, SELECTING the asset root shows a WORLD-ALIGNED
  component-origin triad. That is **correct, not a bug** — the robot's frame IS the
  asset's world frame here, and the robot sits upright to match. A previous round
  "fixed" the world-aligned root triad by baking the FULL frame `F` onto the asset
  root (robot tilted like Main, root triad shows the basis) — but that trades away
  exactly this: the global-origin/gizmo/world-axes then show the SCENE frame, not
  the robot's, which the user rejected. The two are the SAME frame described two
  ways and CANNOT both reflect the robot; the user chose **robot-upright /
  world=robot-frame**. So: asset root component-origin world-aligned = expected.
  The trigger is the pure
  `scene_config.asset_root_declares_origin(origin_map, occurrence_paths,
  folder_origin_paths)`, derived IDENTICALLY by generation + compose so their
  `R_root` can never disagree. ⭐ **A declared root origin lives in EITHER the
  origin map (a base-tree component) OR — when the asset root is a RESTRUCTURE
  FOLDER (a node created in Transform Source, e.g. testB2 "Elect Connectors") —
  the STRUCTURE map's `NewAssembly.origin`, whose custom-origin final paths are in
  the root bake stamp's `folder_origin_frame_paths`.** Both `assets_build.main`
  and `compose_cli` (+ `mesh_assets_build`) read `folder_origin_frame_paths` from
  the ROOT bake stamp and pass it as `folder_origin_paths` — WITHOUT this a
  folder-rooted asset's custom origin is silently ignored (origin map empty) and
  the asset never de-rotates (the "asset origin still global" bug: root component
  triad correct but global-origin/gizmo unchanged). A declared origin is ALWAYS
  single-instance (Set Origin refuses multi-instanced products); a child origin
  (under the root, not a root occurrence) doesn't trigger this and stays a live
  Xform inside; a non-origin asset keeps `R_root`=Main-rotation (unchanged
  "appears-as-in-Main"). Verified `scratchpad/asset_root_origin_fix_test.py`
  (5: helper, de-rotate → natural local frame, composed==Main) + real-testB2
  probes (`testb2_folder_derotate_probe.py`: folder-root de-rotate — asset root
  → identity, leaf de-rotated, composed==Main 4.6e-13) + the mesh asset
  E2E + compose regressions green. NOTE: a declared-origin asset must be fully
  regenerated (Clear + Generate) after any change to this bake — the fast/Update
  path reuses the asset's existing source stage.
- **⭐ Merge-then-edit takes its geometry from the WALK, never from
  `GetShape(product)`.** An XCAF assembly product's cached compound goes STALE the
  moment a re-origin rewrites the child instance locations, because
  **`UpdateAssemblies()` cannot see a location change on an ASSEMBLY child** (only on
  a leaf child — measured rule + the `refresh_assembly_compound` counter-measure now
  called by `apply_origins`/`_reorigin_assembly_once`: `occ-vtk-gotchas.md`).
  `apply_splits`' assembly branch used to read it, which is
  why an **Edit Bodies on testB2's `/Body` asset baked every body displaced by the
  whole `/Body` folder origin frame F (~4.6 m, plus its rotation) while the
  Component Editor looked correct** — the window builds its compound from the walk
  (`build_assembly_edit_compound`), the bake did not, so the preview and the bake
  disagreed. The frames were never wrong: the root stayed at identity and each
  link's frame sat at exactly its picked origin; it was the BODY GEOMETRY that had
  moved out from under them, which reads as "the origin location and orientation of
  the asset is all screwed up". FIX: the assembly branch now calls the SAME
  `build_assembly_edit_compound` over `_preorder_subtree(walked, …)` with
  `assembly_world = comp.transform`, so window and bake agree **by construction** —
  geometry AND the global face-index color map (which is why the old
  face-count-drift degrade-to-base-only guard is gone; the count now matches by
  definition). `inv(comp.transform) · leaf.transform` is the PRODUCT-LOCAL frame and
  is occurrence-INDEPENDENT, so a multi-instanced product still lands right (the
  original reason for preferring `GetShape` — "never rebuild from an occurrence's
  world transforms" — is satisfied). The LEAF branch keeps `GetShape(prod)`: a
  master's shape is stored directly and `apply_origins` rewrites it via `SetShape`.
  Verified on the real asset (`scratchpad/probe_body_fast_rebuild.py`: rebaked world
  bbox == the source stage's to **0 mm**, was F-displaced before) + a deterministic
  regression (`scratchpad/assembly_split_stale_compound_test.py`, 5 checks, which
  also asserts the stale-cache PRECONDITION so it can't pass vacuously).
  **The 30-face color change the fix caused was a CORRECTION, proven independently.**
  The global color MAP is bit-identical old-vs-new (4152/4152 faces,
  `probe_body_colormap_compare.py`) — the divergence was downstream: the old `known`
  face-identity map was built over `_faces_of(GetShape(product))`, i.e. the STALE
  compound, whose face enumeration order need not match the walk preorder the colors
  were accumulated in. The COUNTS matched (which is why the old drift guard never
  fired — it only compared counts), so 30 faces silently read another face's color.
  Checked against the color SIDECAR as an independent ground truth
  (`probe_body_color_truth.py`, centroid → owning leaf → its own per-face color):
  **NEW correct 28, OLD correct 0, 2 ambiguous** (a centroid collision in the lookup,
  not a disagreement). Since the compound that is coloured is now the same object that
  is split, the alignment is exact by construction and this class of silent
  mis-colouring is gone.
- **`_split_face_colors` keys its colors by the SHAPE-MAP INDEX, not by append
  position.** `TopTools_IndexedMapOfShape.Add` returns the 1-based index and NO-GROWS
  on a duplicate shape (two occurrences of one product at the same location, or a face
  shared by two solids of a compound leaf), while the old parallel `known_colors` list
  appended unconditionally — one duplicate shifted every later color onto the wrong
  face. Now `known_colors.setdefault(known.Add(f), color)` + `known_colors.get(idx)`;
  first-writer-wins on a genuine duplicate. Provably a no-op when there are none (the
  testB2 Body compound has 0), so it changed nothing on the real file — it removes a
  latent fragility. Guarded by `scratchpad/assembly_reorigin_compound_test.py`.
- **Merge-then-edit on ASSEMBLIES (`Edit Bodies` on a node WITH children).** The
  splitter now accepts an assembly target (`resolve_split_targets` dropped its
  non-leaf reject; `split_stub_assembly` already predicted a recipe node's
  children as bodies). `apply_splits` branches on `st.IsAssembly(prod)`: for an
  assembly, the walk-built compound yields the descendant solids in the
  assembly-local frame (see above) → `run_split` cuts/decomposes it → the bake REPLACES
  the subtree (`_replace_assembly_children`: capture free entries → RemoveComponent
  the existing children → AddShape/AddComponent the bodies onto the assembly
  product with identity loc → `_prune_free_shapes` the now-orphaned former
  children; shared products survive). Body identity = `body_sort_key`
  (deterministic across bakes, headless-verified: 29-solid assembly, 2
  occurrences, world geometry preserved 4.6e-13). **Colors are now UNIFIED
  window↔bake** (was a nearest-centroid base-only `_assembly_body_infos`, since
  removed): the SHARED `_assembly_face_colors(face_shapes, per_face)` accumulates
  each descendant LEAF's per-face colors (from the SIDECAR-bearing source, NOT
  the .xbf walk which has none) into a global face-index map keyed to
  `_faces_of` of the SAME leaf order the split's compound enumerates (since the
  walk-built-compound fix that alignment is exact by construction, so the old
  face-count-drift degrade-to-base-only guard is gone).
  **⚠️ ORDER: the leaves MUST be enumerated in PREORDER (`_preorder_subtree`,
  which filters the already-preorder `walked.components`), NOT
  `assembly.descendants()` — `descendants()` is a LIFO-stack walk, a DIFFERENT
  order (confirmed diverging at ALL 57/57 leaves on testB2's Drone Body). The
  global face index must line up with the faces of the compound the split
  CONSUMES, enumerated in COMPOUND BUILD order = preorder; using descendants()
  put EVERY per-face color on the WRONG face → the whole model's colors
  scrambled (testB2 "colors all screwed up" after a root-level assembly edit;
  the window looked fine because it built its OWN compound in descendants order,
  self-consistent, while the bake read the product's preorder compound). Both
  `apply_splits` (bake) AND `_assembly_edit_stub` (window) now use
  `_preorder_subtree`. Verified `scratchpad/assembly_color_order_test.py` (24/24
  faces correct in preorder, 0/24 in the old descendants order).**
  `build_assembly_edit_compound` builds the compound + calls the same color core
  for BOTH the window and the bake, so the preview and the bake agree exactly. The
  bake ALSO routes body colors (leaf AND assembly) through the sidecar via a
  new `color_src` arg to `apply_splits` (`apply_geometry_edits` builds it from
  the color-bearing `src_list`) — this is what makes leaf per-face colors
  reproduce in the Main bake too. **Two color MODES** (user chooser at open —
  TEMPORARY, see OPEN TODO): `per_face` carries each leaf's decals; `base`
  paints one flat color per body. The mode is persisted in
  `SplitRecipe.assembly_color_mode` (`"faces"`|`"base"`|None→faces) so the bake
  reproduces what the window showed. `_ask_assembly_color_mode` (Transform
  Source) pops the chooser; `_open_edit_bodies` passes `per_face` to
  `_assembly_edit_stub` and the mode to `EditBodiesWindow` (written into the
  recipe on Apply). GUI: `_add_edit_bodies_actions` offers it
  on assemblies; `_open_edit_bodies` warns (Apply replaces contents) then hands
  the editor a synthetic leaf = `_assembly_edit_stub` (the descendant-solid
  compound in the assembly frame, `.Moved()` per relative location). The edited
  assembly stays an OPAQUE, MOVABLE node in the edit tree — its children (and
  every same-`prototype` occurrence's children) are hidden
  (`_collapsed_child_base_cids`), bodies live only in baked Main. Body→link
  grouping inside the editor is a deferred v2.
- **⭐ A tolerant recipe DROP is never silent any more (two guards).** Asset/Static
  generation runs `apply_geometry_edits(tolerant=True)` so ONE stale edit can't block
  a whole build — but the drop was a bare `print` inside the build subprocess, whose
  stdout the GUI reads **only on failure**. Throwing away a rigged asset's entire body
  decomposition (and orphaning every joint + body origin attached to those bodies)
  therefore looked like a clean generation. NOTE the single-model FAST rebuild path is
  **strict** and already raised loudly ("decompose produced 141 solids but the recipe
  was authored with 15"); only full **Generate Assets** swallowed it.
  1. **Report it (a).** `geometry_edits_build._record_drop` appends structured records
     to an optional `drops=` list threaded through `apply_geometry_edits` →
     `apply_splits` → `_build_asset`/`_build_static`; `assets_build._emit_warnings`
     prints one `CELLSMITH-WARN <json>` line per drop (`WARN_PREFIX`), annotated with
     the knock-on damage — the body paths that were NOT created and, intersecting the
     model's joint map, exactly which JOINTS now dangle.
     `main_window._report_build_warnings` scans stdout on a SUCCESSFUL build and shows
     a `QMessageBox.warning` naming the model, `authored → actual` counts, the missing
     bodies and the dangling joints (whose definitions stay in the config and return
     when the recipe is re-authored).
  2. **Prevent it (b).** `main_window._confirm_recipe_membership_change` runs at
     Transform Source **Apply on Main, BEFORE anything is written**: it plans the OLD
     and the NEW structure map and diffs the set of base components under each asset
     root that has a split recipe (exact, needs no geometry), then warns with the
     per-model added/removed counts and offers **Cancel** (the default). Advisory — the
     move may well be intended. Wrapped in a broad `except` so an advisory check can
     never block an Apply. ⚠️ `plan_tree` REQUIRES label entries, so any test fixture
     must supply `label_entry`/`product_entry`.
  Guarded by `scratchpad/recipe_drop_visibility_test.py` (15) +
  `probe_b2_warn_tolerant.py` (3, the real MoldTending recipe: 15 → 141 solids, all 7
  joints reported). The underlying fragility — body identity is a solid INDEX plus an
  `initial_count` fingerprint — is **CS-133** (ADR-0007), still open.
- **⭐ The Transform's Orient PIVOT is FROZEN into the op — authoring order is
  arbitrary.** `BodyTransform.pivot_point` (new, optional, default-omitted) carries
  the RESOLVED world pivot, written at commit from `_gizmo_pivot_world()` — the same
  point the gizmo draws. It used to be re-resolved on every replay from the body's
  origin, which made an existing op depend on MUTABLE state: **applying a re-origin
  to an already-transformed body re-pivoted its transform and MOVED the body** (363 mm
  on the fixture), even though a re-origin is defined to re-frame without moving
  anything — the very invariant `_commit_origin`'s comment asserts. Consumers prefer
  `pivot_point` whenever set (`body_transform_world4`, `mesh_slice.body_transform_world`
  / `body_transform_local`); a LEGACY recipe without it still resolves live, so
  existing configs are byte-identical and reproduce exactly what they did before.
  `_preload_transform` restores the frozen point and `_gizmo_pivot_world` returns it,
  so **Edit** re-uses the authored pivot rather than re-resolving (an Edit can never
  make the body jump either) — the same "pivot decided once, then frozen" rule the
  main-window Transform gets from `ComponentTransform.pivot`.
  ⭐ **Freezing on commit is not enough on its own — LEGACY ops must be migrated at
  OPEN** (`_freeze_legacy_pivots`, called from `__init__` before the Reset snapshot).
  Every transform authored before the field exists carries `pivot_point=None`, so it
  keeps re-resolving and a later re-origin still moves it — which is why the first
  round of this fix did nothing for the live case (testB2's **Lid** asset, whose six
  transforms all predate the field: adding a ReOrigin to `Link2` displaced it
  **274.3 mm**, reproduced in `scratchpad/probe_lid_link2_reorigin.py` and 0 mm after
  migration). The migration applies exactly the rule the current code would, needs NO
  geometry (the centroid fallback is gone), and so is geometry-neutral at the moment
  it runs; Apply then persists the frozen pivots. Verified
  `scratchpad/body_xform_origin_order_test.py` (5, incl. a discriminating LEGACY case
  that still moves) + `probe_lid_link2_reorigin.py` (2, real asset) + the real-GL
  `probe_xform_pivot_pick.py` (19).
- **Body-Tree lineage: the op chain nests UNDER the ReOrigin node.** The bake order is
  ops → **origins**, so a re-origin is the LAST thing applied to a body and the ops
  that built it are its inputs. The tree used to hang `ReOrigin N` and the op lineage
  as SIBLINGS of the body row, which reads as two independent things (live report:
  *"shouldn't the Transform be a child of the newly applied ReOrigin?"* — yes). Now
  `add_lineage` is hosted by the ReOrigin node when there is one, and the old
  self-referential "derived" row survives only for a body with an origin but NO ops
  (an initial solid), so the node still reads. `Body → ReOrigin 1 → Transform 1 → i18`.
- **⭐ Component-Editor Transform PIVOT: the ORIGIN, never the centroid.** The
  fallback used when no `pivot_point` is frozen (legacy recipes) and what a NEW op
  freezes: the body's own joint origin when it has one, **else the COMPONENT'S LOCAL
  FRAME ORIGIN** — the
  origin the editor draws and anchors its construction datum at. It used to fall back
  to the body's **volumetric centroid**, which reads as *"the orientation is being
  rotated about some random point"*: the centroid is an arbitrary interior point, it
  moves whenever the body's merge membership changes, and rotating about it drags the
  body's frame sideways instead of just re-aiming it. Changed in **all four** places
  that must agree — `geometry_edits_build.body_transform_world4` (bake + preview),
  `mesh_slice.body_transform_world` / `body_transform_local` (mesh twins), and
  `edit_bodies_window._gizmo_pivot_world` (where the gizmo is DRAWN, which is the
  user's only visual statement of the pivot). `pivot == "centroid"` still selects the
  centroid explicitly — nothing writes it, a hand-edited config may.
  ⚠️ **Not backward-neutral:** an already-authored transform op on a body with NO
  custom origin bakes to a DIFFERENT result now. That is the point (the old result was
  the bug), but existing ops want an eyeball.
  **Companion fix — the origin lookup has to try BOTH lids.** `_origins` (GUI) and
  `SplitRecipe.origins` (recipe) are keyed by **FINAL** lids, while a transform op
  names its **INPUT** body and `_start_edit_op` passes that input as the command
  target. So an input-keyed lookup never found the origin of a body that has one, and
  the pivot silently dropped to the fallback — in the GUI *and* at bake, in mesh mode
  too. `edit_bodies_window._xform_origin_point`,
  `geometry_edits_build._resolve_body_trsf` (now takes a lid LIST) and
  `mesh_slice.run_body_ops_mesh` all try `(op.targets[0], f"{op_id}:0")` in order.
- **⭐ Component-Editor Transform PICKS happen on the ORIENTED body, over the WHOLE
  model.** `body_transform_world4` is `translate · orient`, so the Move (From→To)
  points are consumed **after** the rotation — they must therefore be picked on the
  body as the orient leaves it, or you aim at where the body used to be.
  `_begin_xform_pick` now loads its pickable geometry through
  `_render_xform_pick_bodies`, which poses the target by
  **`_xform_orient_only_world`** (orient only — including the translation would make
  `to − from` apply twice) and, when EDITING, draws the op's CONSUMED INPUT body
  *instead of* its RESULT (the result carries the stored transform, so it would be a
  stale ghost to mis-pick on). An **unpicked** From-point (the pre-loaded body origin,
  captured in the un-oriented pose) is mapped forward through the same matrix in
  `_build_body_transform`; a point the user actually picked is already in the oriented
  frame and is used verbatim (`_move_from_picked` distinguishes them, and
  `map_default_from=False` breaks the recursion when the orient matrix itself is being
  computed). **Every body stays pickable during a Transform pick** — no `set_hidden`,
  no CGB body filter, no edge exclude — because a From→To move is nearly always "put
  this point onto that point of ANOTHER body"; the Visibility toggle now governs only
  the preview view, and the Transform command DEFAULTS to **All Bodies** (Split and
  ReOrigin still default to Target Body). Real-GL verified
  (`scratchpad/probe_xform_pivot_pick.py`, 11 checks).
- **⭐ Component-Editor Transform: EDITING an existing op targets a CONSUMED body,
  so its display mesh must be built on demand.** `_meshes` (from `_run_ops`) is
  populated only for `recipe.ordered_final_ids()` — the bodies actually drawn. But
  `_start_edit_op` passes `op.targets[0]`, the op's INPUT body, which a later op
  consumed, so it is **not** final and `_meshes.get(lid)` is None. Two features died
  silently on that: `_build_xform_preview_actors` returned early → `_xform_actor` None
  → `_update_xform_preview` short-circuits → **no moving preview when editing an
  existing transform**; and `_refresh_gizmo` fell back to `verts = zeros((1,3))` →
  `_gizmo_size = max(0*0.6, 1.0)` = **1.0 mm**, a sub-pixel arrow at model scale →
  **the translate arrows could not be grabbed** (the hit test is a 12-px gate on the
  drawn shaft, so a 1 mm shaft is unreachable). FIX: `_display_mesh(lid)` returns
  `_meshes[lid]` when final, else tessellates the state from `_all_states` (which
  holds EVERY lid — OCC `tessellate_shape`, or `body_to_colors` + a VTK face array in
  mesh mode) and caches it in `_aux_meshes`, which `_replay` clears alongside the
  geometry it describes. Both consumers route through it. Real-GL verified
  (`scratchpad/probe_xform_edit_preview.py`, 20 checks): the edited case now builds
  the preview actor and reports the SAME gizmo size as a fresh transform (103.9 on the
  fixture, was 1.0), the X arrow is hit-testable at its projected mid-point, and a
  LEFT press there claims the gesture.
- **⭐ The Transform offset fields must NOT quantise — they are a ROUND-TRIP.**
  `QDoubleSpinBox` rounds to `decimals()` on both `setValue` and typing, and the pane
  writes a stored `BodyTransform` in (`_preload_transform`) and reads it back out
  (`_commit_transform`) — so `setDecimals(2)` on the mm offsets and `(1)` on the
  degree offsets **degraded an existing transform every time it was re-opened** (a
  CGB-derived `-2.7182818284` came back `-2.72` and the body moved). Both groups now
  use **`num_field.PreciseDoubleSpinBox`** (new): `decimals=12` internally (below any
  geometric tolerance) with `textFromValue` trimming trailing zeros so the field still
  reads `90°`, plus a `C` locale so Qt's own text→value parse uses the same `.`
  separator the class formats with. ❓ The Construction-Geometry bar's own spinboxes
  (`construction_geometry.py`, `setDecimals(1)`/`(3)`) have the same quantisation and
  were left alone — not reported, and their values are re-derived from picks rather
  than round-tripped.
- **Edit Bodies orientation gizmo (cue only).** The Edit Bodies viewport shows
  the ROOT's PENDING orientation as the corner gizmo (`_apply_orientation_gizmo`,
  re-applied after each `viewport.load`) so the user sees which source axis
  becomes "up". Geometry is NOT rotated — cuts are authored + stored SOURCE-frame
  (orientation bakes last; splitting commutes with rigid rotation, so the baked
  result is identical either way).
  `EditBodiesWindow` (`src/gui/edit_bodies_window.py`, renamed from
  split_window.py): a **3-pane splitter** — LEFT (bodies tree · Join/Merge ·
  cuts list) | MIDDLE (viewport, fresh tessellation, world placement kept so
  picks are model-world; feature-edge overlay built IN-PROCESS via
  `build_edges_from_loaded()` after every load) | RIGHT **"Edit"** pane of
  stacked `QGroupBox` frames (`_build_edit_pane`): **Identify Bodies** (the
  **Tint Bodies** toggle — distinct per-body tints; VISUAL ONLY, never affects
  the bake, per its tooltip) · **Define Plane** (the FIVE
  cut tools side by side — **3-Point / 2-Point / Point / Edge / Face**;
  **2-Point** picks two points and the plane contains their LINE, rotated about
  it by Tilt A — `_recompute_2point` + `_rotate_about_axis` Rodrigues, xdir = the
  line) · **Point Snap** (enabled for the 3-Point/2-Point/Point tools: **Edge**
  (default — snap the picked point to the nearest EDGE endpoint via
  `_edge_infos`), **Tesselation** (snap to the nearest combined-mesh vertex),
  **None** (raw face point); `_snap_mode`/`_on_snap_mode`/`_snap_point`, applied
  in `_on_pick_point`. The HOVER marker now previews the SNAPPED point and
  HIGHLIGHTS the snap target — via `viewport.set_hover_snap(self._hover_snap)`:
  edge snap highlights the edge (`highlight_pick_edge`), tess snap highlights the
  tessellation face (`prepare_face_highlight` + `set_face_highlight`)) · **Plane
  Shape** (Rectangle | Circle) · **Transform Plane** (`[Label|Input|Slider]`
  rows — Axis combo, **Tilt A / Tilt B on separate rows**, Offset; each numeric
  input has a coarse slider synced to it; widgets ENABLE per tool —
  Axis+Tilt only for Point (Tilt A ALSO = the 2-Point rotation), **Offset for
  EVERY tool** (shifts the plane along
  its normal — `_set_pending`/`_reapply_offset` apply it uniformly; NOTE: the
  line-Edge facing reads the Axis value, but Axis is DISABLED during Edge so it
  uses the current value), `_update_transform_enabled`) · **Resize Plane** (rect
  UV extents grid, OR — for a disc — **Diameter** + **Center U / Center V**
  (the disc center's in-plane offset from the cut origin, along xdir + the
  in-plane perpendicular; keeps the disc ON its plane, mirrors the center-drag
  grip which now syncs these fields — `_disc_u`/`_disc_v`/`_apply_pending_origin`);
  shape-toggled) · **Cut Surface Color** (a
  color SWATCH + **Set…** (opens the unified `color_picker.ColorPickerDialog`,
  which carries the "Pick Color" screen eyedropper + alpha channel — the old
  standalone "Pick" button is GONE) / **Clear** → dominant) · an
  **Add Cut** button that **AUTO-TESTS + inserts**
  (`_on_add_cut` appends → runs `_on_test`; on a build failure it pops the error
  and ROLLS the cut back). **AUTO-TEST on open**; **DRAGGABLE outline handles**
  (rect edges / disc rim; disc center '+' grip id 4 relocates the origin); the
  **3-Point Plane centers at the CENTROID of the 3 picks**. The bottom row keeps
  status · **Tint Bodies** · Test · **Clear Bodies** · Apply · Cancel (Apply
  GATED on `_bodies_valid()` = a current Test, ≥2 bodies, AND UNIQUE names). The
  body list is the **"Body Tree"** (header renamed); its indicator dot (gray =
  hidden, teal = has an origin) is painted at the ROW's RIGHT edge by
  `_BodyDotDelegate` (role `_BODY_DOT_ROLE`), like the main component tree — not
  a left icon. **Test** stays (Add-Cut and Merge auto-Test, but REMOVING a cut
  bumps the serial without a test → Test is the manual re-validate). Bodies
  render in the model's OWN colors (leaf: `_body_colors`; assembly-merge:
  nearest-leaf base color). Tree↔viewport selection syncs; **renaming to an
  EXISTING body name is refused** (reverted + status — names must be unique);
  **merging selects ONLY the newly-merged body** (`_select_only_body`, matched
  by pre-merge member tuple); **F2** renames the selected body even from the
  viewport. Right-click (tree or viewport) offers **Rename…** and
  **Hide/Show** — hidden bodies get a right-side gray dot and aren't
  rendered (`_hidden_bodies`, transient view aid; never in the recipe).
  Right-click ALSO offers **Set Origin… / Clear Origin** per body
  (single-body): Set Origin opens the existing `OriginWindow` on a synthetic
  Component from that body's solid, INHERITING the current viewport view
  (`camera_state` → new `OriginWindow(camera_state=)` arg); its Apply lands an
  `OriginFrame` in `SplitRecipe.body_origins` (keyed by FINAL body index str;
  **teal dot** in the tree). At bake, `apply_geometry_edits` injects each body
  origin into the model's origin map keyed by the body's post-split PATH
  (`{split_path}/{body_name}`, validity-checked), so the EXISTING origins bake
  (`apply_origins` leaf/assembly frame surgery) handles it — no new engine
  (real-OCC verified: world preserved 2.3e-13, Body-1 frame relocated). When
  **"Show Component Origin"** is on, selecting ONE body draws its origin triad
  (`_refresh_body_origin_indicator` → `show_component_origin`; the custom frame
  if set, else the part's frame origin).
  In the bodies view, tree↔viewport selection SYNCS (tree row highlights the
  body; a viewport pick selects the row, Ctrl adds) and BOTH offer
  right-click **Rename…** (opens the tree's inline editor — same path as
  F2/double-click). **F2 renames the selected body** even when the VIEWPORT
  has focus (a `WindowShortcut` `QShortcut(F2)` → `_on_rename_shortcut` →
  `editItem` on the selected/current row), so a body picked in 3D renames
  without clicking into the tree first.
  In BOTH edit windows a pick tool is canceled by **Esc** or by re-clicking
  its (checked) button (`_cancel_tool`/`_on_escape`). **Activating a cut tool
  PRESERVES the camera**: `_on_tool` calls `_restore_target_view`, which
  captures `viewport.camera_state()`, reloads the target with
  `reset_view=False`, then restores the pose — otherwise the auto-Test's
  bodies→target swap would `view_isometric()` and snap the view away from
  whatever the user rotated to (live-test fix).
  `OriginWindow` (`src/gui/origin_window.py`): a splitter — subtree viewport
  (existing meshes reused) LEFT + a right **"Origin" command pane**. **REWORKED to
  drive the viewport's Construction Geometry Builder (CGB) (item 48):** the pane's
  buttons REQUEST an entity from the CGB — clicking one calls `cg.set_mode(...)` and
  DISABLES the pane's CONTROLS (`_set_controls_enabled(False)` → the datum box,
  orientation-source box, Basis/transform box, and Clear button — NOT `self._pane`
  itself) until `constructionFinished` fires (Accept → the entity; Cancel/`None` →
  nothing). Only the child controls grey out (not `self._pane` itself); on re-enable
  the transform box stays gated on the Custom source. **The "pane disappears" bug was
  the maximize×splitter interaction, NOT the disable:** the splitter sizes were set
  in `_build_ui` while it was 0-wide, and opening MAXIMIZED (item 49) then handed all
  width to the stretch-3 viewport, squeezing the stretch-0 pane to ~0 (a manual
  restore→maximize recomputed it — the diagnostic clue). Fixed like Transform Source
  — `_initial_load` re-applies `self._split.setSizes(...)` off the REALIZED window
  width (pane a fixed ~360px, viewport the rest) + `setChildrenCollapsible(False)` +
  a pane min width. **The same fix was applied to `EditBodiesWindow` (Component
  Editor)** — its 3-pane splitter re-applies 250:700:320 proportions scaled to the
  window width in `_initial_load` (both hit the bug once every editor opens
  maximized). **REAL-GL probe-verified** (`scratchpad/probe_origin_pane.py`, a real
  windowed run): opening the maximized Origin Editor the pane holds 360px + visible
  as the window grows 1050→2560 AND across the Vertex-button click / CGB activation —
  it never collapses. (With the min-width + non-collapsible in place the pane cannot
  reach 0 width, so a live report of it still vanishing points to a STALE running
  instance, not the current source.) The user picks + Accepts on the viewport's
  own CGB/Selection-Filter bars. Groups: **Origin Datum** = ONE **Vertex** button
  (`make_icon("vertex")`; requests a CGB VERTEX → the origin POSITION; button goes
  active once a vertex is stored; re-click re-requests) — the old Edge/Point buttons
  + Point-Snap groups are GONE · **Origin Orientation Source** (**Global** default =
  align to the DISPLAYED WORLD axes / **Custom** = a picked Basis) · **Origin
  Orientation Transform**
  (enabled only for Custom) = ONE **Basis** button (`make_icon("basis")`; requests a
  CGB BASIS → the full X/Y/Z orientation) · a **Clear Origin** button that clears
  BOTH the Vertex and the Basis (and returns the source to Global). `_on_cgb_finished`
  matches the returned entity KIND to the pending request (a mismatched kind = a
  cancel), stores `_origin` (vertex.point) or `_basis` ({x, z} from
  basis.xdir/normal), and re-enables the pane. **Full-basis frame:** `OriginFrame`
  gained an `xdir` field — Apply writes `axis`=basis Z **and** `xdir`=basis X, and
  `matrix4()` uses `orientation.basis_matrix(xdir, axis)` (columns = the exact
  X/Y/Z) instead of the Z-only `axis_frame_matrix` (a saved axis-only frame still
  loads, X auto-completed). The bake (`apply_origins` → `matrix4`) and the USD
  live-Xform (reads post-bake `comp.transform`) inherit the full orientation with no
  further change. Triad preview `_redraw_frame` draws the full basis; Esc cancels a
  pending CGB request. **Apply is gated** on `_is_valid()` = a Vertex set, NO pending
  CGB request, AND (Global OR a Custom Basis defined). Apply/Cancel in the bottom
  row. Opens INHERITING the opener's ORIENTATION but ZOOM-EXTENTS
  (`camera_state=` pose → `reset_camera` refits + centres — NOT the opener's offset).
  Both windows are held on `TransformSourceWindow._edit_bodies_win` /
  `MainWindow._origin_win`, closed in `_commit_model`/parent closeEvent.
  **(item 49) Every top-level window opens MAXIMIZED** — `MainWindow` +
  `TransformSourceWindow` + `EditBodiesWindow` (Component Editor) + `OriginWindow`
  each set `setWindowState(windowState() | Qt.WindowState.WindowMaximized)` in
  `__init__` (right after `resize(...)`, which is now just the restored-state size).
  Not borderless fullscreen — the title bar stays so modal editors remain movable.
  **All three editor windows are `WindowModal`** (set in `__init__` before
  `show()`): a child blocks EDITS in its parent chain but not the whole app —
  Transform Source blocks the main window, Edit Bodies blocks Transform Source
  (and thus the main window too), Origin blocks the main window. Relies on
  each window being constructed with its real `parent` (all are). This
  supersedes the old "non-modal shell" pattern.
  **Draggable HANDLE layer** (`viewport_panel`): LEFT press/drag was unused
  (left is click-only; camera lives on middle/right), so the style gained
  `_on_left_press`/`_on_left_release` hooks — a press on a handle CLAIMS the
  gesture (the release then never fires a click-select). API mirrors the
  edge-pick trio: `set_handle_data(points, segments, handle_ids)` (lines
  PolyData built with `lines=` IN the ctor — `PolyData(points)` alone adds a
  VERTEX cell per point and the per-cell RGBA length breaks),
  `update_handle_points` (IN-PLACE move — the only mutation allowed during a
  drag; add/remove actors inside the MouseMove observer is the re-entrancy
  crash), `clear_handle_data`. Hit test = 2D point-to-segment distance in
  DISPLAY space (`_display_of` + `_pt_seg_d2`, 12-px gate). Hover recolors
  the handle's cells yellow, dragging orange (in-place `h_rgba`); the move
  observer feeds `on_handle_drag(hid, ray_p0, ray_p1)` — the OWNER intersects
  the view ray with its own plane. Edit Bodies wires it: rect handles 0–3 map
  to `u_min/u_max/v_min/v_max` (min clamped below max), the disc RIM (id 0)
  sets `diameter = 2·|hit − origin|`, and the disc CENTER '+' grip (id
  `_CENTER_HANDLE`=4, two extra line-segments from `_center_cross`) sets
  `_pending["origin"] = hit` (moving the whole outline in-plane). The handle
  overlay carries outline + center points; during a drag the preview poly
  follows `_cut_outline_points` while the handles follow `_handle_geometry`
  (they differ once the center cross exists). Spinboxes update signals-blocked
  and points move in place; the release does one full redraw + republish.
  The viewport also exposes `camera_state()`/`set_camera_state()` (opaque
  pose capture/restore) for exact view preservation across a re-`load()`.
  Real-GL probe: display-space hit test finds both the rim AND the center
  grip, drags resize/relocate live, tool activation preserves the view, zero
  wgl errors.
  **Pickable edge layer** (`src/gui/edge_pick.py` + viewport): per-TopoDS-edge
  polylines from `BRep_Tool.PolygonOnTriangulation` (adaptor-sampling
  fallback), classified via `BRepAdaptor_Curve` (+
  `ShapeAnalysis_CanonicalRecognition.IsCircle` rescue for BSpline circles),
  one lines PolyData with per-cell `edge_index`; viewport `set_edge_pick_data`
  / `set_edge_pick_mode` — hover highlights via a per-cell-RGBA highlight
  actor updated IN PLACE (observer-safe, same trick as the solids), hit-test =
  surface-ray point → `FindClosestPoint` → 12-px display gate; click falls
  back to `on_pick_point` when no edge is near. Tree indicators: orange
  DIAMOND = split recipe, teal TRIANGLE = origin frame
  (`_refresh_geometry_edit_indicators`; structure-moved nodes don't resolve —
  cosmetic only). A restructure FOLDER's teal triangle comes from its bake
  stamp's **`folder_origin_frame_paths`** (the CUSTOM-origin subset — folders
  with only the parent-frame default get no glyph), resolved to active-tree cids
  by `_folder_origin_nodes` — because a folder's frame lives in the STRUCTURE
  map, not the origin map, so the origin-map `resolve()` alone would miss it.
- **Known v1 limits**: indicators + USD frame set resolve base paths against
  the ACTIVE tree, so nodes MOVED by a structure map show no glyph / export
  fully baked (geometry identical either way); asset USD exports read only the
  ASSET's origin map (Main-level frames inside an asset are baked but not
  live); OBJ untouched by frames.
- **Secondary-viewport windows: `wglMakeCurrent` error-2004 spam (SOLVED —
  root cause probe-verified with a REAL-GL scripted repro,
  `probe_gl_window.py` pattern: drive real windows from a script on this
  machine; the "no GL" limitation applies only to `QT_QPA_PLATFORM=offscreen`)**:
  the burst of `vtkWin32OpenGLRenderWindow ... error 2004` lines the user hit
  when "splitting bodies" was **TEARDOWN noise, not a broken view** — the
  window rendered fine (`GetNeverRendered()==False`); destroying a
  QtInteractor WITHOUT closing its plotter leaves VTK cleanup running against
  a dead GL context (~135 MakeCurrent failures + a final `Clean()`).
  **Fix: `ViewportPanel.shutdown()` (= `plotter.close()`) called from every
  secondary window's `closeEvent`** — verified zero GL errors with both a box
  and the real testB1 `asset-41099_Fanuc_M-710iD70` leaf (that asset is a
  single leaf named like the root — actually a COMPOUND of 15 solids × 6
  occurrences, i.e. exactly the decompose-into-links use case). ALSO kept
  (correct hygiene, applied while
  chasing this): the GL viewport is constructed LAZILY — `_build_ui` places a
  plain `_viewport_host` QWidget with `self.viewport = None`; first
  `showEvent` (guarded `_initial_load_done`) → `QTimer.singleShot(0,
  _initial_load)` constructs `ViewportPanel(self._viewport_host)` (FINAL
  parent → no reparent), wires callbacks, then loads. Handlers reachable
  pre-load guard `self.viewport is None`. Keep any NEW window with its own
  viewport on BOTH patterns (lazy construct + shutdown on close).
- **Offscreen-testing gotcha (REVISED)**: a real `ViewportPanel` cannot
  construct under `QT_QPA_PLATFORM=offscreen` (vtkWin32OpenGLRenderWindow
  fails hard) — window LOGIC is offscreen-tested by monkeypatching
  `ViewportPanel` with a stub. BUT real-GL WINDOWED repros CAN be scripted
  from the dev harness (this is the user's own desktop session): QApplication
  with the default windows platform + QTimer-driven open/interact/close,
  run as a subprocess with stderr grepped for VTK errors (see the
  probe_gl_window.py pattern that cracked the error-2004 bug). Windows flash
  on the user's screen briefly — warn them. Interactive picking/visual
  QUALITY still needs the user's eyes.

## Component Transform (main window; move a subtree's placement — NEW; engine + GUI logic COMPLETE, headless/offscreen-verified, GL live-test PENDING)
A main-window command mirroring the Component Editor's **Transform**, but on a
whole COMPONENT / subtree: it rigidly **MOVES the node's world placement** and
BAKES into the model. **Non-destructive** — editing or deleting the transform
reverts the geometry on the next rebuild (bakes always start from the pristine
source stage + apply only the stored edits). Works on any active model
(Main + generated), on **assemblies** (whole subtree rides along) and leaves;
multi-instanced nodes are refused (like Set Origin). Contrast **Set Origin**,
which re-frames WITHOUT moving world geometry.

### ⭐ DEFERRED BAKE — main-window origin/transform edits BATCH
A main-window **ReOrigin**/**Transform** used to re-bake the whole Source→Main stage on
every Apply (minutes on testB2). They are now **deferred**: the config is written, the
change is **previewed**, and the bake happens ONCE — on **Rebuild**, or implicitly when
generating/opening an asset (those already prompt).
- **Scope: `_DEFERRED_KEYS = ("origins", "transforms")`**, plus the two folder writers
  (`_apply_folder_origin`/`_apply_folder_transform`). **Everything else still bakes
  immediately** — the Source Editor's restructure Apply (it supplies Main's input) and
  the Component Editor's body edits (topology surgery, nothing to preview; splits
  aren't reachable from the main window at all).
- **Pending ledger** `_pending_edits` — ordered, each entry carrying an `undo` that
  restores the prior config value. Powers the Rebuild count, *Undo last edit*, and the
  failure report.
- **Staleness** `_edits_pending()` prefers the DURABLE authority
  (`cache.main_rebuild_required` = bake stamp vs `source_to_main_inputs`) so a pending
  state survives a restart, with the in-session ledger as fallback.
- **Preview** `_pending_pose_map()` → `{cid: display 4x4}` where
  `delta = T_stored · T_stamped⁻¹` (accumulated over self+ancestors via `_accum_from`,
  then pushed into the display frame) — i.e. only the UNBAKED remainder.
  `ViewportPanel.apply_pending_pose` rigidly moves those components' rendered points
  from a pristine snapshot (so repeat updates never drift and the restore is exact);
  `clear_pending_pose` on a model commit. A pending **ORIGIN** contributes no delta —
  it re-frames without moving world geometry.
- **⭐ EVERY world-baked layer moves together** (round 17 — the live report was *"edges
  didn't move, still in the original position"*). Geometry is rendered as four separate
  world-baked polys, and a preview that moves only one of them reads as *"the transform
  didn't take"*. `apply_pending_pose` now drives all four through one kernel,
  `_posed_points(base, point_index, {component index: 4x4})` — always recomputed from a
  **pristine snapshot**, elementwise (no BLAS):
  | Layer | How it is posed |
  |---|---|
  | combined shaded mesh | `_combined.point_component` masks the points |
  | feature-edge overlay (`_edges`) | per-**cell** map scattered onto both endpoints by `_edge_point_component()` (cached; refuses anything that is not pure 2-point line cells rather than mis-mapping) |
  | tess wireframe | *extracted* from the combined mesh → `_rebuild_tess_edge_actor()`, and only when it is visible |
  | pickable-edge layer | ⛔ **NOT posed** — see below |
  **⛔ NEVER write `_edge_pick_mesh.points`.** Round 17 posed the pick layer too, and it
  **corrupted the heap** — Windows `0xc0000374`, crashing inside `poly.lines` on the next
  `_subset_edge_data`, with no Python traceback. That layer is **not privately owned**:
  `selection_filter._apply_info_mask` builds every armed subset with
  `pv_polydata_lines(poly.points, …)`, which wraps the point array **zero-copy**, so
  several PolyData share one buffer. Assigning `.points` replaces it under every other
  holder — a use-after-free that surfaces far from the write. Rebuilding the locator does
  not help; the aliasing is the problem. The pick layer therefore stays in the BAKED pose
  while an edit is pending: its wireframe lags and its hit test resolves against where the
  body used to be, until a rebuild. A lagging overlay is cosmetic; heap corruption is not.
  Every overlay failure is swallowed — a lagging wireframe is cosmetic, but an exception
  on the preview path would break the edit itself.
- **⭐ The pending-ORIGIN branch is ABSOLUTE — never compose the pose delta on it.**
  `_origin_capture_frame(..., to_display=True)` already maps the stored frame through
  the **full** stored transform (`Φ·T_stored`), so adding the pending delta
  (`Φ·T_stored·T_baked⁻¹·Φ⁻¹`) applies that transform **twice**. Live symptom: a 90° Z
  transform turned the part 90° and its origin 180°. Position looked correct — both
  terms carry the same translation — so only the doubled rotation showed, which is
  exactly how it slipped past a suite that asserted positions. The **no-custom-origin**
  branch is the other kind: baked frame × delta. The two are computed differently and
  must not be mixed. A node whose origin predates its transform is unaffected (the
  frames coincide), which is why one folder looked fine while two did not.
- **A landed bake must DROP the override, not just the map.** The closure installed by
  `_refresh_pending_state` captures the frames dict **by value**; clearing
  `_pending_frames` leaves it drawing the pre-bake frame for the rest of the session.
  `set_frame_override(None)` is called explicitly when the bake lands.
- **Reading a frame out:** `_report_selected_frame` puts the selected node's frame in
  the status bar — position plus the **X and Z axis directions** (directions, not Euler
  angles: an origin bug shows up as an axis pointing the wrong way, and Euler triples
  hide that behind convention questions). It reports the PENDING frame when there is
  one, so the readout and the glyph can never disagree.
- **The ORIGIN INDICATOR follows a pending edit** (`_pending_frame_map` →
  `SelectionController.set_frame_override` / `refresh_origin_indicator`). "Show
  Component Origin" is drawn from the **baked** `comp.transform` via
  `selection._primary_frame`, so a pending ReOrigin left the triad at the old spot
  until Rebuild. The override supplies, per node: a pending **origin's** stored frame
  mapped forward (`_origin_capture_frame(..., to_display=True)`), then any pending
  **transform** delta on top — so origin+transform compose, and a pure transform still
  carries the frame.
- **⭐ The bake is ABSOLUTE, never incremental — deltas cannot compound.** Every bake
  restarts from the **pristine source stage** and applies only the stored maps
  (`splits → origins → transforms → structure → orientation`); a stored
  `ComponentTransform.matrix` is the resolved 4x4 against the PRISTINE world, and one
  entry per path means re-editing REPLACES rather than accumulates. The pending-preview
  delta (`T_stored · T_stamped⁻¹`) is a DISPLAY-only construct — it never feeds the
  bake. **Authoring caveat:** because the stored matrix is absolute, always re-open an
  existing transform via **Edit Transform…** (which preloads the recipe *and* the
  original `pivot`); a fresh *Transform…* on an already-transformed node would replace
  its matrix while being authored against the moved pose.
- **⚠️ PERF — the refresh must stay O(affected), not O(components × config parse).**
  As first written, `_refresh_pending_state` **hung the UI**: `_pending_frame_map`
  called `_origin_capture_frame` per component, and that re-parsed the transform +
  structure maps *every* call — thousands of config parses per refresh on a real
  model. Three rules keep it fast, all guarded by a test:
  1. the maps are parsed ONCE in `_refresh_pending_state` and threaded into both
     builders (`stored=` / `baked=`; `_accum_transform_source` and
     `_origin_capture_frame` take a `by_path=` for the same reason);
  2. `_pending_pose_map` skips any component whose path is not at/under an **affected
     prefix**, and `_pending_frame_map` visits only nodes that actually have a pending
     origin or pose — never the whole tree;
  3. `_edits_pending()` is **memoized** (`_pending_cache`, cleared by
     `_invalidate_pending_cache` on edit / bake / model commit) because it reads the
     bake stamp off disk and `_refresh_rebuild_action` runs on every UI sync.
  The guard asserts ≤4 parses and sub-second completion over 3000 components.
- **Rebuild** `_on_rebuild_clicked` bakes when anything is pending, else falls through
  to the historical visual re-render; the action is labelled `Rebuild (N pending)`.
- **Bake FAILURE never auto-reverts a batch** (`_report_pending_bake_failure`): the
  config is kept, the dialog names what the bake blamed plus the pending list, and
  offers **Undo last edit**. A successful bake clears the ledger.

### ⭐ EDIT-CAPTURE FRAMES — why authoring order used to matter
**Invariant: a picked coordinate must be stored in the frame the BAKE STAGE THAT
CONSUMES IT sees.** The bake order is fixed (`splits → origins → transforms →
structure → orientation`) and never replays the authoring order, so a coordinate
captured in the *displayed* pose has to be mapped back past everything applied after
its own stage.

The capture boundary used to undo **only** the root Source→Main frame
(`_main_bake_frame`), never a per-node transform. Consequence (reported live):
- **ReOrigin → Transform worked.** A re-origin *re-frames without moving world
  geometry*, so the transforms stage sees exactly what the user saw, and the pivot is
  the origin the origins stage just placed.
- **Transform → ReOrigin did not.** The origin was picked on the *moved* part but the
  origins stage runs **before** transforms — it sees the part in its pre-transform
  pose, so the origin landed where the part used to be ("off in some other place").

**`main_window._origin_capture_frame(base_path, to_display)`** now composes BOTH
factors — the Source→Main frame **and** `_accum_transform_source(path)` — and is used
in **both directions**: storing (`_on_origin_applied`) and re-opening an existing
origin for edit. Order is therefore irrelevant.
- `_accum_transform_source` walks **path PREFIXES** (`/A/B/C` → `/A/B` → `/A`) and
  composes **outermost-first**, `T_a1 · … · T_self`. Not a guess: `apply_transforms`
  computes each node's location against its PRE-relocation parent world, so a child
  ends at `T_parent · T_child · W`.
- `_stored_transforms_by_path` unions the path-keyed transform map with
  **restructure-folder transforms**, which are keyed by folder id — so
  `_apply_folder_transform` records the folder's current path in
  `ComponentTransform.provenance["path"]` expressly to make them findable here.
- **Provably inert without a transform:** the extra factor is identity for every model
  that has none, i.e. everything that works today. It only changes the case that was
  wrong.
- **Only ORIGINS need this.** Transforms are captured in the display pose and applied
  last (and re-origin doesn't move geometry) → no compensation. Structure/orientation
  consume no picks. **Split planes are safe** even though `Cut` is stored in
  source/world coords, because the Component Editor is opened from the **Source
  Editor** on source-stage geometry — a Main-stage transform is not visible there.
- **KNOWN GAP:** a folder with NO transform whose ANCESTOR folder has one can't be
  path-resolved synchronously (`folder_key` lives on the PLANNED tree), so that
  ancestor is missed. Verified: `scratchpad/origin_order_test.py`.

### ⚠️ OPENING the Transform pane must never load the base structure
`_resolve_base_path` is **expensive**: with a structure map present it shows a busy
*"Loading base structure…"* dialog and background-loads the PRISTINE BASE (+ split
stubs) to translate an active-tree node to its base path. That is fine on **Apply /
Clear** — a bake follows anyway — and unacceptable for anything cosmetic.

Round 11 got this wrong: `_refine_transform_pivot_async` called it from **every**
`_start_transform`, so merely OPENING the pane on a model with a structure map hung
for minutes (reported live on testB2 `/Body`). Two rules now:
1. **A folder's custom origin is found SYNCHRONOUSLY.** `_apply_folder_origin` stamps
   `provenance["path"]` (exactly as `_apply_folder_transform` already did), and
   `_folder_origin_paths()` reads them back — so `_transform_pivot` needs no async
   resolve at all. The async refine is **deleted**. *(LEGACY: a folder origin written
   before the stamp has no path and is missed until it is re-applied.)*
2. **`_resolve_base_path(..., allow_load=False)`** for any opportunistic caller — it
   returns `None` instead of launching the loader. Used by the Edit-Transform
   preload. Only Apply / Clear / opening the ReOrigin window may pass `allow_load=True`.

Guarded by `transform_gui_offscreen.py`: opening the pane must resolve **nothing**,
and Edit may resolve only opportunistically.
### The PIVOT a Transform rotates about
`_transform_pivot(cid, comp, frame=…)` → `(pivot, source_label)`, decided when the pane
opens and frozen for the command (stored as `ComponentTransform.pivot` provenance,
reused by Edit). Precedence:
1. **The node's CUSTOM ORIGIN**, when it has one — the node's frame origin
   (`frame[:3,3]`), which after `apply_origins` *is* that origin, so no config lookup is
   needed to place it. Decided by an EXACT origin-map path match, or — for a restructure
   FOLDER, whose origin lives in the structure map under a folder id — by the path
   `_apply_folder_origin` **stamps into `provenance["path"]`**, read synchronously by
   `_folder_origin_paths()`.
2. **The subtree's world AABB *centre*** (mean of the 8 corners — a box centre, not a
   centroid) — the historical default, still right for a node with no meaningful frame.
   This reads the RENDERED mesh, which `apply_pending_pose` has already moved, so it
   needs no pending correction.
3. **The node frame**, when nothing in the subtree is meshed/visible.

**⭐ `frame` is the node's CURRENT frame, not `comp.transform`** — `_current_node_frame`
returns the cached `_pending_frames[cid]` when an unbaked edit has moved the node, and
falls back to the baked `comp.transform` otherwise. This is not cosmetic: with the
deferred bake, `comp.transform` is *the pose of the last bake*, so a Transform opened
right after a ReOrigin pivoted about the node's **old** origin and the part rotated
**and swung to a new position** (live report: *"the /Body component translated when it
shouldn't have"*). The same frame supplies the pane's *from*-basis. `_pending_frames` is
filled by `_refresh_pending_state` (which computes it anyway for the origin indicator)
and cleared when a bake lands — **never recomputed on pane open**, which would put an
O(model) walk back on an interactive path.

**Why the custom origin wins:** that frame was deliberately placed (a link / joint
frame). Rotating about the bbox centre carries it to a NEW world position — the part
points the right way but its frame *drifts*, which defeats the Set-Origin/ReOrigin work.
Rotating about the origin holds it still and changes only the orientation.

Rotation is `Tr(p)·R·Tr(−p)` (`orientation.mat4_orient_about`); **Translate is applied
AFTER the rotation**, along Main axes. The pane title names the pivot
(`… · pivot: custom origin | bbox centre | node frame`) because it is **not yet
user-settable** — an explicit pivot picker is **CS-088**.

### ⭐ A folder's edits are keyed by ID but READ by PATH — never let one go unfound
A restructure folder's `origin` and `transform` live in the **structure map**, keyed by
**folder id**. Every GUI consumer looks them up by **tree path**. Bridging that is not
optional plumbing — an entry that cannot be found by path is not "missing a nicety", it
**silently drops out of ancestor compensation and out of the pending preview**, and the
symptom appears somewhere else entirely (an origin that bakes to the wrong place).
Live-hit on testB2's `/Lid`, whose transform carries `provenance: {}`. Three layers, in
order:
1. **The open node wins.** `_origin_target_path` prefers `self._origin_cid` — the node
   whose ReOrigin window is open. It is the actual tree node, so nothing has to have
   been stamped.
2. **The stamp.** `_apply_folder_origin` / `_apply_folder_transform` write
   `provenance["path"]`. A stamp beats a derived path, which keeps a **renamed** folder
   resolving against the path its edit was authored at.
3. **Derive it.** `restructure.folder_tree_path(smap, fid)` walks the folder chain
   (`parent`: `""` = implied root, `"nK"` = another folder, `"/path"` = a carried base
   node). Used as the fallback in `_transforms_by_path`, `_folder_origins_by_path` and
   `_origin_target_path`, so an unstamped entry is **never dropped**.

**`_origins_by_path()` is the one place to ask "does this node have a custom origin?"**
— it unions the origin map with the structure map's folder origins. Reading only the
origin map is why a folder ReOrigin showed no pending indicator until a rebuild.

### ⭐ Restructure FOLDERS take a different route (the "nothing happens" bug)
A folder created in the **Source Editor** is NOT in the `transforms` map, because
that map is keyed by a path in the **post-split, PRE-STRUCTURE** walk — where the
folder does not exist yet (`apply_structure` creates it). Applying a transform to
one used to be **silently dropped** with a status-bar line (`_go()` rejected any
`folder:<nK>` key), which read as "I hit Apply and nothing happened". Live-reported
on testB2's `/Body`.
- The transform now lives on the folder entry — **`restructure.NewAssembly.transform`**
  (a `ComponentTransform`) — exactly like that folder's custom `origin`, and is
  applied by **`restructure_build._apply_folder_transforms`** immediately AFTER
  `_apply_folder_origins`. Same order as the main bake (origins→transforms), so the
  folder's custom joint frame **RIDES ALONG with the geometry**: the part points a
  new way in Main while its origin is unchanged *relative to the part*.
- Pure instance relocation (`world → T·W`, `local → P⁻¹·T·W`); the subtree rides
  along because children are relative. No geometry/face-order/color/mesh surgery.
  Planned worlds for the folder AND its descendants are restated so
  `compare_planned` still lines up; preorder means nesting composes.
- GUI: `_apply_folder_transform` (sibling of `_apply_folder_origin`) writes the
  structure map + rebuilds with rollback; **Clear Transform** routes folders there
  too; `_node_has_transform` falls back to the COARSE
  `_model_has_any_folder_transform` gate (which folder a node is can't be answered
  synchronously — `folder_key` lives on the PLANNED tree), and the Edit pane
  preloads a folder's recipe from the async `_resolve_base_path` result.
- An **unresolved** path is now a LOUD `QMessageBox`, never a status-bar line — a
  built-then-discarded transform must never look like a no-op.
- Adding the field can't force a rebuild of existing projects: the stamp compares
  the RAW STORED structure map, which is only re-dumped when the user edits the
  structure (and any such edit rebuilds anyway).
  Verified: `scratchpad/folder_transform_test.py`.
- **Config = a per-model `transforms` map** (`ModelConfigStore.get/set_transform_map`
  → `_get/_set_raw_map(model,"transforms")`; keyed by BASE-tree PATH like
  origins/splits). Value = `geometry_edits.ComponentTransform`: `matrix` (the
  RESOLVED rigid 4x4, row-major 16 floats, in the model's SOURCE world frame =
  the bake authority) + `recipe` (a Main-frame `BodyTransform`, for re-editing) +
  `pivot` (the world pivot used). `load/dump_transform_map` (dump drops a
  near-identity no-op). It IS a bake input → joined `source_to_main_inputs` +
  `has_geometry_edits` (a change triggers a rebuild); the bake stamp carries it
  (an absent key with an empty-map expected value is NOT a mismatch —
  `cache.main_rebuild_required` — so adding this map never forces a spurious
  rebuild of pre-existing projects).
- **Bake = INSTANCE RELOCATION** (`geometry_edits_build.apply_transforms`, inside
  `apply_geometry_edits` AFTER origins so a joint frame rides along): for a target
  with world `W` and parent world `P`, set the instance location to
  `L' = P⁻¹·matrix·W` (new world = `matrix·W`) via `XCAFDoc_Location.Set` +
  `UpdateAssemblies`. NO geometry surgery — product geometry, face order, color
  sidecar AND local-frame meshes all stay valid (contrast the origins leaf
  branch); nothing re-tessellates. Refuses a MULTI-INSTANCED node (instance label
  occurs >1× — relocating would move every sibling occurrence). Bake order is now
  **splits → origins → transforms → structure → orientation**. Mesh twin =
  `mesh_build.apply_transforms_mesh` (multiply the target + descendants' ABSOLUTE
  world transforms by `matrix`). Threaded through every plan + stamp exactly like
  `origins` (restructure_build / assets_build / mesh_build / mesh_assets_build).
- **Frame conversion:** the pane authors in the MAIN world frame the user sees;
  Apply resolves the `BodyTransform` → `T_main` (Orient about the subtree bbox
  centre, then Translate — elementwise `orientation` helpers) and conjugates to
  the source frame `T_source = F⁻¹·T_main·F` (`F = _main_bake_frame()`; None =
  identity, the common case incl. every generated model). Composes correctly
  through structure (which preserves world) + the final orientation bake.
- **GUI** (`main_window`): context-menu **"Transform…"** (single selection, not
  the ROOT) → **"Edit Transform…"/"Clear Transform"** when one exists. A right-side
  **Transform Edit pane** (splitter index 3, hidden until active; mutually
  exclusive with the joint pane): **Orient** radio = Offset a/b/c (° about world
  X/Y/Z) OR From/To **Basis** (CGB); **Translate** radio = Offset X/Y/Z in
  **METRES** OR **Move Point** (CGB From→To). The offset spinboxes are stacked
  VERTICALLY (a `QFormLayout` per group); the translate offset converts m→source
  units at build (`× 1/export_scale`) and source→m on preload. From Basis/Point
  DEFAULT to the node's current frame/origin so an untouched Orient/Translate is a
  no-op. Apply/Cancel.
  `_build_transform_pane`/`_start_transform`/`_on_transform_apply`/
  `_end_transform_command`; CGB picks via `_request_xform_cgb`/
  `_on_xform_cgb_finished`; write + rebuild via the shared `_apply_geometry_edit`
  (extended for `key=="transforms"` via `_geom_map_accessors`) with the rollback
  closure. Torn down on model switch (`_commit_model`) + Esc. Tree indicator = a
  **green MOVE-CROSS** (`tree_panel.TRANSFORM_ROLE` / `_TRANSFORM_COLOR` /
  `set_transform_nodes`), resolved in `_refresh_geometry_edit_indicators`.
- **Live preview** (`viewport_panel`): a **moving BBOX wireframe** of the target
  subtree (`component_world_bounds` → 8 corners → `set_transform_preview`;
  `update_transform_preview(T_main)` moves the points in place, elementwise — no
  BLAS). **v1 limit: NO interactive gizmo DRAG** — the spinboxes + CGB drive the
  transform, and the bbox tracks it live; porting the Component Editor's draggable
  arrows/rings gizmo to the main merged actor is the deferred enhancement.
- **Exports need NO change** — the transform bakes into `comp.transform`, so
  USD/OBJ/STEP inherit the moved placement automatically.
- **RIGID-only bake FAST PATH (`restructure_build._reuse_edges_rigid`)** — a
  transform/orientation main bake only rigidly RELOCATES subtrees; local
  geometry, colors, and mesh face-order are unchanged, so meshes are already
  reused (no re-tessellation). The DOMINANT remaining cost was
  `build_combined`+`extract_feature_edges` over ~20k parts (minutes,
  GIL-holding). Since feature edges are **rigid-invariant**, the bake now REUSES
  the SOURCE stage's edge cache and RE-TRANSFORMS each edge point by its
  component's world delta (`main · source⁻¹`, elementwise — no `@`/BLAS) instead
  of re-extracting. Per-point component = the source edge npz's per-cell
  `cell_component` spread to the line endpoints; index→cid via
  `build_combined(base_asm).component_ids` (same deterministic meshed-leaf order
  that produced the cache — rigid moves preserve finiteness so it matches).
  Gated by `rigid_only = (not split_map and not origin_map and smap.is_empty())`
  AND `reuse_meshes` (source mesh+edge caches fresh at the bake quality — the
  load-time prebuild writes them). ANY missing/mismatched piece → clean
  FALLBACK to `_extract_and_save_edges` (the `build_edges=False` flag on
  `_build_derived_caches` splits the mesh write from the edge write). Applies
  ONLY to the ROOT main bake — asset generation keeps `build_edges=True`.
  Verified `scratchpad/edge_reuse_test.py` (6): reused edges are IDENTICAL to a
  fresh extraction of the moved geometry (Jaccard 1.0), moved edges == `T·source`,
  un-moved unchanged. Byte-neutral for a no-op/faithful-copy bake (all-identity
  deltas). **STEP-only** — mesh bakes already skip tessellation + build edges
  in-thread on reload, so they're fast without this.
- **Verified**: `scratchpad/transform_test.py` (24 — config round-trip; STEP
  apply_transforms leaf/subtree move, siblings unmoved, empty-map no-op = the
  non-destructive drop, origin+transform compose, multi-instance refusal; mesh
  twin + non-destructive revert) + `scratchpad/transform_gui_offscreen.py` (16 —
  real MainWindow pane/command flow offscreen: open, measure-ends-on-open, bbox
  preview, pivot, offset→matrix, one rebuild, persisted `ComponentTransform`, Edit
  reload, orient-about-pivot, Clear, multi-instance refusal, Basis identity no-op).
  GL preview + the CGB pick RENDER are USER live-test.
- **v1 limits**: base-path-keyed (a structure-moved node's glyph/menu won't
  resolve — cosmetic; the transform still bakes); NO gizmo drag (above); a
  restructure FOLDER can't be transformed (no base-tree identity — refused).

