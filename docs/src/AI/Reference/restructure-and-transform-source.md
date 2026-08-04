# Tree restructure (Feature A) & the Transform Source window

The arbitrary tree-restructure feature (StructureMap, the `plan_tree` planner as single source of truth, XCAF label-surgery build, per-asset re-apply) and the unified Transform Source editor window that hosts restructuring, the orientation/datum settings, and the Edit Bodies entry point. Read when touching restructuring, the Transform Source window, or its Apply/bake flow. Verify against `src/`; may lag.

---

## ⭐ READ FIRST — the restructure BLAST RADIUS (why "one restructure shredded everything")

A Main restructure is the single highest-leverage edit in the app: it re-bakes Main AND
forces asset regeneration, so it re-runs every downstream stage at once. A live testB2
incident — the user moved ONE part (`41099-01-060-01-*`) into the `/MoldTending` folder —
broke Main poses, every asset's body origins, and a robot's joints. **It was TWO
independent defects firing together**, and a future agent chasing any one symptom will
mis-diagnose it without the whole chain. Diagnostic probe:
`scratchpad/probe_b2_restructure_damage.py` (reports, per generated model, whether its
recipe still fits and whether its joint paths resolve).

**Cause 1 — map-only state was destroyed (FIXED, `CS-131`, ADR-0008).**
`diff_edited_tree` rebuilt each folder from the editor's rows, which do not carry a
folder's `origin`/`transform` → both reset to `None` on EVERY Apply.

```
one Apply
  → all 6 folders: origin=null, transform=null      ← Main geometry snaps to raw source poses
  → root bake stamp folder_origin_frame_paths = []  ← was all six
     → scene_config.asset_root_declares_origin() = False for every asset
        → generation bakes R_root = the Main rotation instead of IDENTITY (no de-rotation)
           → each asset's LOCAL FRAME changes under its authored body origins
              → "the asset origins and body locations got screwed up"
```
Nothing failed to propagate — **the upstream inputs had been deleted.** That distinction
matters: the symptom looks like a stale-cache / re-keying bug and is not one.

**Cause 2 — the Edit-Bodies recipe stopped fitting (guarded, `CS-132`; real fix `CS-133`).**
The moved part joined the asset root's subtree, taking it from **15 solids to 141**;
`initial_count` no longer matched, so `apply_splits(tolerant=True)` dropped the whole
recipe — and the drop was invisible (see the tolerant-drop invariant).

```
recipe dropped → /Base … /Link6 never created
   → the 6 per-body origins have no body to attach to
   → all 7 joints dangle (joints are keyed by MAIN-STAGE path; the JointDefs
     survive in the config and return the moment the bodies do)
```
Only the model whose membership changed was affected; the other five assets' recipes still
fit. **A dangling joint is a symptom, not a cause** — do not go looking for a joint bug.

**What is NOT recoverable:** folder origins/transforms already nulled are gone from the
config (the bake stamp's copy is nulled too). They must be re-authored. Recovery order that
works: restore/re-author the folder frames → Rebuild Main → **Clear + Generate** Assets (a
full regenerate: a declared-origin asset must be rebuilt from scratch for the de-rotation to
be re-baked; the fast/Update path reuses its existing source stage) → re-author any recipe
whose subtree genuinely changed. Joints then reappear on their own.

---

## Tree restructure (Feature A — "Main" model; COMPLETE, headless-verified; GUI pending user live-test)
CAD trees are structured by ASSEMBLY; rigging needs structure by MOVEMENT. Feature
A lets the user ARBITRARILY rearrange any model's component tree: MOVE subtrees by
drag-and-drop and ADD new assembly "folders" — at two levels: coarse (whole scene →
**Main**) and fine (inside a generated asset/Static, e.g. regroup a robot into
links). The durable artifact is a compact **structure map in the config**
(config-driven: every restructured model is rebuildable headlessly from base
geometry + map); geometry is BAKED by XCAF label surgery on Apply.

- **Main REPLACES Source in the Model Tree** (user decision — they never edit a
  raw "Source"). The base model KEEPS internal id `MODEL_SOURCE` (zero churn/
  migration); only the LABEL is "Main" (`MAIN_DISPLAY_NAME`;
  `_model_label(MODEL_SOURCE)="Main"`). Since the Source→Main pipeline, Main is
  ALWAYS the baked **main STAGE of the root dir** (`geometry-main.xbf` beside
  `geometry-source.xbf`) — even with zero edits it's a faithful copy (+ the
  scene frame). `store.variant_for_model(MODEL_SOURCE)` returns `ROOT_VARIANT`
  unconditionally; freshness/staleness is the bake stamp's concern
  (`main_rebuild_required` — `load_model` fails loud on a missing stage, never
  silently serves the source). `list_asset_variants` matches only `asset-*`.
- **Map schema** (`src/model/restructure.py`, pure — no OCC/Qt): the base model's
  map lives at the config TOP level as `"structure"`; each asset's (Static incl.)
  in its `assets[Name]["structure"]`. `StructureMap{next_id, assemblies:{nK:
  {name,parent,seq,origin?}}, moves:{"/origin/path": {parent,seq}}}`. Parent
  keys: `""` = implied root, `"nK"` = new folder, `"/path"` = a carried node's
  ORIGIN path in the model's BASE tree. **`origin`** (optional `OriginFrame`) =
  the folder's custom joint frame — the ONE place a restructure folder's origin
  lives (folders have no base-tree identity for the origin map); default-None =
  the parent-frame placeholder. See the folder-origin bullet in "Geometry edits". Unlisted components stay put; no-op moves never emitted;
  `next_id` never reused (re-keying can't mis-bind); `seq` = global append order
  so folders+moves interleave per-parent exactly as edited. Sibling order:
  APPEND-TO-END (moved/new after surviving originals — matches XCAF AddComponent).
  `_minimize_raw` leaves `structure` untouched (unknown keys round-trip).
- **Planner = single source of truth** (`restructure.plan_tree(base, smap) →
  PlannedTree{assembly (stub, cids like the real walk), origin, folder_key,
  base_to_planned}`): the GUI editor, the build, and the verification all consume
  it, so WYSIWYG is structural (editor preorder == planned == rebuilt walk).
  Validates fail-loud (`RestructureError` lists all problems): unknown paths,
  cycles (unreachable check), empty folders (an EMPTY folder survives the xbf but
  reloads as a shape-bearing leaf — always blocked), leaf targets, and the
  INSTANCING constraints (see the gotcha). `diff_edited_tree` (editor→map),
  ⭐ **which MUST be given the map being edited (`prior=`) or it WIPES every folder's
  `origin` and `transform`.** The editor's rows carry only `(ident, parent, name)`; a
  folder's frame and placement live ONLY in the map, so rebuilding each `NewAssembly`
  from the rows reset both to `None` — meaning **any** restructure Apply silently
  destroyed them. Live blast radius on testB2 from ONE Apply moving ONE part: all six
  robot folders' joint frames + poses nulled, so Main's geometry snapped back to raw
  source poses; and because `scene_config.asset_root_declares_origin` reads those
  origins, the root bake stamp's `folder_origin_frame_paths` went `[]` → **every asset
  regenerated WITHOUT its de-rotation** (`R_root` = the Main rotation instead of
  identity) → each asset's local frame changed under its authored body origins, which
  is what "the asset origins and body locations got screwed up" was. Carried forward by
  FOLDER ID (`nK` is stable and never reused, so a rename or re-parent keeps it); a
  folder absent from `prior` is new and correctly starts frameless. Guarded by
  `scratchpad/restructure_folder_frame_survives_test.py` (8, incl. the without-`prior`
  case that still loses them). ⚠️ **Values already lost this way are NOT recoverable
  from the config — they must be re-authored.**
  `rekey_nodes` (old map + new map → node configs follow their components across
  Applies; marks on deleted folders dropped+reported), `subtree_stub`/
  `exclude_stub` (asset/Static base trees cut from the Main assembly — no doc
  load needed to EDIT a map), `compare_planned` (build acceptance),
  `InstancingInfo` (movable/valid_target gates). `orientation.mat4_inv_rigid`
  ([Rᵀ|−Rᵀt], elementwise) gives the compensating location.
- **Build** (`src/io_step/restructure_build.py`, Qt-free CLI `python -m … <step>
  <plan.json>`; plan = `{target_variant, base_variant, structure, deflection,
  angular}`): copy base `.xbf` → target variant → `apply_structure(doc, walked,
  smap, planned)` (capture entries/worlds/instance-names → create named folders →
  Pass A all RemoveComponent → Pass B all AddComponent in planned preorder,
  naming every new instance label → one UpdateAssemblies → free-set EQUALITY
  check) → save → reopen → `compare_planned` 1:1 (names/parents/world transforms)
  → ORIGIN-ALIGNED reuse of the positional machinery (`_transplant_colors` +
  `_build_derived_caches` get the base components re-listed in the NEW preorder;
  planner stubs fill folder slots — mesh reuse still valid, local verts are
  placement-independent). Main is ALWAYS baked — an empty map + no edits still
  produces a copy (+ the scene frame); `build_restructured_variant` also serves
  a generated model's FAST rebuild via `base=(asset_variant, STAGE_SOURCE)`.
  testB1: ~40s total incl. edges; testA1 planner 0.08s/20k.
- **Per-asset/Static maps re-apply DURING generation** (`assets_build`):
  generation is always from the root MAIN stage; `rebuild_only` regenerates
  just the listed models — from each model's OWN source stage when present
  (fast path, no re-prune), else the full prune fallback
  (`static_exclude_root_ids`/`_paths` carries the full exclusion list for a
  static full rebuild); `_apply_saved_structure` runs as a post-pass right
  after prune+pose-bake (walk the pruned doc → plan that model's map →
  surgery → verify+transplant via `_aligned_src`/`_verify_structured`). A map
  that no longer fits the regenerated subtree FAILS that build loudly (fix or
  delete the model's map). Headless-verified: new-folder-as-asset-root, robot
  asset with own map (LinkGroup), Static with own map, rebuild_only isolation.
- **The restructure EDITOR lives inside the Transform Source window**
  (`src/gui/transform_source_window.py`, column 2 — restructure_window.py +
  transform_window.py were MERGED into it and deleted; single instance on
  `MainWindow._transform_win`). Everything below moved VERBATIM: **node
  moving is a MANUAL mouse gesture — Qt's ENTIRE drag stack
  (QDrag/OLE/MIME/dragEnter…) is unused** (`setDragDropMode(NoDragDrop)`): on
  Windows it kept vetoing drops on nested rows (red no-drop cursor) below
  every override attempted. `_EditTree` implements press →
  move-past-`startDragDistance` → live receiver highlight (`set_drop_hover`
  background tint) + move/forbidden cursor → release moves via
  `takeRow`/`appendRow` (roles intact, O(1)/move); Esc cancels; manual 400 ms
  hover auto-expand + edge auto-scroll. **Refused drags/drops now surface
  their REASON in the status label** (`show_refusal`;
  `draggable_selection`/`drop_target_at` return `(result, why)` from
  `InstancingInfo.movable/valid_target` — the parked red-cursor bug's
  diagnostic). **Targeting is FULL-ROW, no zones**: anywhere on a container
  row moves INTO it; a LEAF row receives for its parent; gated
  (shared-product) assemblies stay un-targetable; self/descendant targets
  refused. Moves always APPEND (the planner's ordering). Colors (full
  change-guarded decoration pass, `_refresh_all_decorations`): **GREEN** =
  new folder, **RED** = EMPTY new folder — kept in the tree but **PRUNED
  from the map on Apply** (the planner still hard-blocks empty folders),
  **BLUE** = moved (tooltip = origin path), **GRAY** = carried assembly,
  **MAGENTA** (`_NOMOVE` = `205,70,150`) = a node that CAN'T be moved because
  it sits inside a MULTI-INSTANCED assembly (its instance label occurs >1× —
  the SAME gate as `InstancingInfo.movable`; `_blocked_by_instancing`, tooltip
  names the occurrence count). Roots (also non-movable) are NOT magenta — the
  flag is scoped to the multi-instanced children the user asked to identify.
  Ancestors of any change get the blue caret (`MODIFIED_DESC_ROLE`); the
  orange DIAMOND (`SPLIT_ROLE`) marks pending body recipes in BOTH trees.
  Right-click: Add Child…, Rename/Delete (folders; delete only when empty),
  Reset (moved nodes → original parent at source-order slot), Edit
  Bodies…/Clear Bodies (single leaf), Hide/Show. Buttons: Reset Structure
  (structure only — recipes/settings kept), Apply (validate structure +
  recipes → `applied(model, smap, split_raw, settings|None)`), Cancel.
  **Selection syncs WINDOW-INTERNALLY** (tree↔tree↔window viewport under a
  `_syncing` guard; a viewport pick selects in both trees; single selection
  shows the component-origin triad) — the old translate-to-the-MAIN-viewport
  sync is GONE (the window owns a viewport of the base geometry, cids match
  directly). Right-click **Hide/Show** = TRANSIENT visibility in the
  WINDOW's viewport only (flat set expanded over the EDIT tree's current
  arrangement, re-pushed on every structural change; never the config; dies
  with the window). The left tree is COLLAPSIBLE via the slim arrow strip
  (`_toggle_left`). Window `FOLDER_ROLE` stays at UserRole+21 (clear of the
  shared `_IndicatorDelegate`'s roles). **The root Apply prompt decides the
  regeneration UP FRONT** (three buttons: Apply + Regenerate Assets [default]
  / Apply Only / Cancel — `_regen_after_bake` True/False/None): bake +
  regeneration then run as ONE unattended chunk (`_on_main_bake_finished`
  sets `_pending_auto_generate` instead of `_pending_regen_offer`; "Apply
  Only" suppresses the post-bake offer too; other flows — Rebuild Model,
  origin edits — keep the one-click offer, `_regen_after_bake=None`).
  Offscreen-tested (QT_QPA_PLATFORM=offscreen, stub ViewportPanel):
  construction (4 columns, settings pane root-only), pending-state machine,
  selection sync, refusal reasons, transient hide, synthesized-QMouseEvent
  move gesture, Apply payload; real-GL probe (probe_ts_window.py): zero
  wglMakeCurrent errors incl. an Edit Bodies child auto-decomposing live.
- **MainWindow wiring**: ONE "Transform Source…" Commands-toolbar action
  (ACTIVE model) + Model Tree row menus — Main row: "Transform Source…" +
  "Rebuild Model" (re-bake from the saved Source→Main inputs; ALWAYS offered
  — Main is always baked; warn-prompts when generated assets exist);
  asset/Static rows: "Transform Source…" above "Delete Configuration" (the
  Model Tree signal is still named `restructure_requested`). The edited
  model must be ACTIVE — invoking while another model is active AUTO-SWITCHES
  and opens once the switch settles (`_open_transform_source_when_idle` POLLS
  busy at 200 ms; a canceled switch gives up quietly). Open flow ALWAYS
  background-loads the model's SOURCE stage (`_base_load_target` →
  `_on_ts_base_ok`; trees + viewport share the ONE load; meshes from the
  stage's mesh cache or a tessellate worker, saved back). **Worker-chaining
  gotcha (cost a live "hang")**: a QThread worker's ok-handler that chains a
  SECOND worker must close `self._progress` first (overwriting the attr
  leaks the WindowModal dialog on screen FOREVER — blocks the whole window
  group), and `_cleanup_worker` guards with `self.sender() is self._worker`
  so the superseded worker's `finished` can't tear down the successor's
  dialog/busy state. **A SECOND stuck-dialog bug (fixed): the open chains
  load → tessellate → edges PROCESS. The tessellate worker's `done` handler
  (`_on_ts_meshed`) used to open the edges dialog directly — but `done` fires
  BEFORE the worker's `finished`, so it OVERWROTE `self._progress` (orphaning
  the "Tessellating source" dialog on screen forever) and then
  `_cleanup_worker` (finished) closed the just-opened EDGES dialog (the
  worker WASN'T superseded by another worker, so the guard didn't fire). FIX:
  handlers that chain a NEW dialog-owning op register a one-shot
  `self._after_worker_cleanup` thunk instead of opening the dialog inline;
  `_cleanup_worker` runs it AFTER closing the finishing worker's own dialog +
  clearing busy. `_on_ts_base_ok` (mesh-fresh + stub cases) and `_on_ts_meshed`
  both defer `_ts_prepare_and_show`/window-show through it.** Main → the root
  source stage; asset/Static → its OWN source stage when present (direct)
  else a stub cut from a background-loaded root-main assembly (window keeps
  `_backing_assembly` alive; NO 3D preview then). The window base is built
  WITHOUT split stubs (`_build_edit_base(with_bodies=False)`). Asset/Static
  Apply passes BASE-model PATHS (`root_path`/`static_exclude_root_paths`),
  and recommits the rebuilt ACTIVE model on success
  (`_post_generate_reload`). **The clears-assets warning moved to APPLY**
  (open touches nothing): Continue → save → bake; the actual clear runs on a
  SUCCESSFUL bake (`_clear_assets_after_bake` consumed in
  `_on_main_bake_finished`, then the one-click regen offer) — a failed Apply
  loses nothing.
  **Apply flow** (`_on_transform_source_applied`): rekey node configs
  (`get/set_raw_nodes`) → store structure map + split map + (root)
  `bake_model_settings` with live-config sync → close window → ONE bake:
  Main → `restructure_build` into the **`main-tmp` staging dir, whose files
  move into the root dir on success** (the old bake survives failure;
  `_restructure_rollback` restores ALL config pieces on ANY bake failure);
  asset/Static → single-model `assets_build` `rebuild_only` (fast path from
  its source stage). An empty (Reset) map still bakes — Main never reverts
  to a raw source alias.
  **Open flow** (file open): see `pipeline-and-caching.md`.
  Generate's name dedup seeds `RESERVED_MODEL_NAMES` ({"Static","Main"}) so a
  part named "Main"/"Static" dedupes to "-2" instead of colliding.
- **Reader additions**: `Component.label_entry` + `product_entry` (TDF entry
  strings, recomputed every load) power the instancing gates + all surgery
  identity; `_label_entry()` helper in reader.py.

