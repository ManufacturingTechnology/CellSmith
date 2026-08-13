# Asset splitting (Feature B) & composed export

Prototype-based asset splitting: marking, prototype grouping, Generate / Update / Clear Assets, the assets-stamp + `assets_up_to_date` predicate, the direct-`.xbf` builds and per-asset `R_root`, the Model Tree panel + menu matrix, the one-file `ModelConfigStore` section model, and Export Composed (USD base/override + payload, OBJ, STEP). Read when touching asset generation, the Model Tree, or composed export. Verify against `src/`; may lag.

---

> ⭐ **If an asset's body origins / body locations moved after a Main restructure, the cause
> is almost certainly UPSTREAM, not here.** `asset_root_declares_origin` reads the ROOT bake
> stamp's `folder_origin_frame_paths`; if a restructure Apply nulled the folder origins, that
> list goes empty, every asset regenerates WITHOUT its de-rotation, and each asset's local
> frame moves under its authored origins. Read the **BLAST RADIUS** section of
> `restructure-and-transform-source.md` before debugging generation.

## Asset splitting (Feature B — Model Tree; PROTOTYPE-BASED since 2026-07;
## headless-verified; prototype rework user live-test PENDING)
Splits the scene into individually-editable MODELS: ONE asset per marked
**PROTOTYPE GROUP** (all occurrences of one prototype — marking any occurrence
marks them all); everything else becomes one **Static** model. Each model is
edited exactly like the source (viewport + component tree + per-node state +
exports).

- **Prototype grouping (`src/model/asset_marks.py`, pure — no OCC/Qt).**
  `group_key(comp)`: the prototype NAME when non-empty and not a useless CAD
  fallback (Solid1/Body2… — local `_is_useless_name` mirror), else the exact
  product identity (`product_entry`). NAME grouping is deliberate: real files
  (testB1) export the "same" robot as 3 DISTINCT STEP products with one
  prototype name (SolidWorks re-exports per posed "Free Drag" variant) — the
  user confirmed those must merge into ONE asset (built from the FIRST
  occurrence in preorder; the exported drag articulations are intentionally
  lost — telemetry poses the rig). `expand_marks` (cids → whole groups),
  `mark_conflicts` (ancestor/descendant, both directions),
  `build_asset_groups(assembly, marks, prior=stamp)` (grouping + naming),
  `stamp_payload` (the membership record). **Naming**: prototype name,
  fallback the canonical occurrence's cleaned name; deduped `-2` against
  `RESERVED_MODEL_NAMES`; **NAME CONTINUITY** — a group whose occurrence
  paths intersect a prior `assets-stamp.json` entry reuses that entry's
  name+slug verbatim, so an Update can never rename a surviving asset (the
  name is simultaneously the config key, the `asset:{Name}` model id, and —
  via the slug — the cache dir).
- **Model ids vs cache variants.** GUI/config layer uses MODEL IDS `"source" |
  "static" | "asset:{Name}"` (`scene_config.MODEL_SOURCE/MODEL_STATIC/asset_model()`);
  the cache layer uses directory VARIANTS `"root" | "static" | "asset-{slug}"`
  plus a STAGE per read/write (`asset_slug(name)` sanitizes;
  `ModelConfigStore.variant_for_model` maps — the GUI always uses STAGE_MAIN).
- **Marking** (`_set_asset_nodes`, blue DOT indicator `tree_panel.ASSET_ROLE` /
  `set_asset`): right-click "Mark/Unmark as Asset", SOURCE model only — BOTH
  paths run through `expand_marks`, so a group always marks/unmarks WHOLE.
  **The config stays NORMALIZED: every occurrence of a marked prototype
  carries the path-keyed `is_asset` mark** (this invariant is what lets
  `assets_up_to_date` compare plain path sets, no assembly needed);
  `_commit_model` re-normalizes on load (one-time migration of legacy
  per-occurrence marks, persisted immediately). Guards: implied root
  rejected; a fan-out that would nest inside another marked asset (or
  contain one) REFUSES the WHOLE mark with a `QMessageBox.warning` naming
  the conflicting occurrence + container — zero state mutated;
  `assets_build._validate_roots` re-checks headlessly over ALL occurrence
  subtrees. The old multi-instance info box is GONE (fan-out is the designed
  behavior; the status line reports the occurrence count instead).
- **Generate Assets** (right-click the Model Tree's `Assets` node;
  `_on_generate_assets` → subprocess `assets_build <step> <plan.json>`): plan
  carries `{assets:[{name,slug,root_id,root_path,occurrence_paths}],
  keep_variants, build_static, cleanup, assets_stamp, deflection, angular}` —
  `root_id` = the group's CANONICAL occurrence (the build root);
  `assets_stamp` = `stamp_payload` of the FULL desired membership (drives the
  Static exclusion set + the occurrence validation + is written to the cache
  root on success). **`cleanup` is EXPLICIT** — an empty `assets` list must
  never mean cleanup (an incremental Update legitimately sends one); the
  0-marks GUI path sends `cleanup: true`. FULL-SYNC semantics: regenerate
  every listed asset, DELETE variants not in `keep_variants`, rebuild static.
  After the subprocess: `cache.close_variant_docs` on every touched variant
  (mandatory), then refresh the Model Tree. Config sections of deleted assets
  are KEPT (remark+regen restores edits). The plan also carries the DISPLAY
  quality: generation builds each model's **mesh + edge caches** too
  (`_build_derived_caches`), so the first Model Tree switch renders instantly.
  - **Both model kinds are DIRECT `.xbf`→`.xbf` builds** (file-copy the ROOT
    MAIN stage + XCAF label surgery; NO STEP round-trip — an earlier build wrote +
    reparsed a temp STEP per asset, minutes each on test1; direct = seconds).
    Generation ALWAYS splits the root MAIN stage — it already carries the scene
    orientation + datum, so NO orientation flows through the plan anymore:
    - **Per asset** = keep-only-the-subtree: copy the root main `.xbf` →
      `Open` → KEEP set = `_product_entry` (referred product) of every subtree
      component → `_prune_free_shapes` iteratively `RemoveShape`s free labels
      outside it (removals orphan children's products → new free labels →
      repeat). The canonical occurrence's PRODUCT ends up the single free
      root — real name, structure 1:1 with the base subtree. **The CANONICAL
      occurrence's Main ORIENTATION is baked into that root — rotation only
      (`_rotation_loc(src_root.transform[:3,:3])` prepended via
      `_bake_rotation`), translation ZEROED so the asset stays at its own
      origin.** So a standalone asset appears exactly as it sits in Root.Main
      (Z-up robots; a part whose design frame ≠ the scene frame — e.g. a
      platen lying with its normal horizontal — reoriented to match Main),
      NOT its raw design frame (which for the platen would show the raw
      +Y-up Source look — the "one asset isn't transformed" bug). This
      rotation `R_root` is occurrence-INDEPENDENT (one fixed rotation per
      asset), so ONE file still serves every occurrence — the composed
      exporter places occurrence k at `W_k · R_root⁻¹` (compose_cli). A
      user-declared origin frame (origins map, baked upstream) composes under
      this cleanly. The pruned+oriented doc = the asset's SOURCE stage (+
      transplanted sidecar); its own splits→origins→structure produce its
      MAIN stage. NOTE: `R_root` is rotation-ONLY and occurrence-independent —
      the historical bug that made it grouping-incompatible was baking the
      full per-occurrence pose; the canonical rotation is safe.
    - **Static** = remove-the-subtrees: same copy →
      `RemoveComponent(comp.source_label)` per occurrence root — **EVERY
      occurrence of every marked prototype** (the exclusion set = the union
      of the plan's `assets_stamp` occurrence paths; occurrences sharing an
      instance label dedupe to one removal) → `_prune_free_shapes` with KEEP
      = the original free roots. NO rotation bake (it keeps the base WORLD
      frame — already oriented+datum'd). Its pruned doc = Static's SOURCE
      stage; its own maps produce its MAIN stage.
    - Neither path touches a STEP writer during the build; both reload + verify
      + transplant colors afterwards. Faithful STEP re-export FROM the pruned
      docs verified. Generated models default to `+Z`/0 config — orientation
      is a ROOT-ONLY concept now (no per-model orientation editing).
  - **Colors** = positional TRANSPLANT from the (appearance-baked) source
    assembly: both sides are preorder-DFS over the same structure, so
    `assets_build._transplant_colors` copies resolved base+per-face colors by
    INDEX (name-asserted per position) into the variant's color sidecar. NOTE:
    `assembly.descendants()` is NOT preorder — filter `assembly.components`
    (which IS, walk adds parent before children) for ordering.
  - **Mesh reuse**: when the source's mesh cache is fresh at the plan quality,
    its meshes are COPIED positionally onto each generated model (local-frame
    vertices are placement-independent) instead of re-tessellating; edges are
    still extracted per variant.
- **Assets stamp + THE dirty predicate** (`cache.py`, beside the bake-stamp
  helpers): `assets-stamp.json` in the cache root = `{cache_version,
  assets:[{name, slug, prototype, canonical_path, occurrence_paths}]}` —
  written by `assets_build` as the LAST action of a successful full/update
  generation (never by `rebuild_only`; a failed build keeps the old stamp so
  the predicate stays dirty); deleted by cleanup/Clear. **NO poses stored** —
  consumers re-derive occurrence transforms from the root Main walk at use
  time (stored poses would go silently stale on a Main rebuild).
  **`cache.assets_up_to_date(step, marked_paths)`** is the single "generation
  matches the marks" predicate (Model Tree dirty state, Update availability,
  composed-export gate, compose_cli's own re-check): False on missing/
  version-stale stamp, on-disk variants ≠ stamp slugs, static main missing
  while assets exist; else `marked_paths == union(stamp occurrence_paths)`
  (exact because the GUI keeps marks normalized). Takes `marked_paths` as
  data (`store.source_asset_paths()`) — no store/assembly dependency.
- **Update Assets** (Assets-node menu, offered when generated AND dirty AND
  ≥1 mark; `_on_update_assets`): INCREMENTAL regeneration — diff the desired
  groups (with name continuity) against the stamp by slug (+ variants missing
  on disk count as new; a missing/version-stale stamp regenerates all): plan
  lists ONLY the new groups, `keep_variants` = the FULL desired set (the
  existing full-sync deletion then removes exactly the unmarked ones —
  verified: kept variants' mtimes untouched), `build_static: true` (membership
  changed), `cleanup: false`, fresh `assets_stamp`. Eviction list = new ∪
  removed ∪ static only. Gated on `main_rebuild_required` like Generate (a
  stale Main refuses with "Rebuild Main first" — the rebuild clears assets
  anyway and the normal offer flow takes over). Pre-upgrade caches (no stamp)
  read dirty → the first Update is effectively a full regenerate and sweeps
  legacy occurrence-named variants via full-sync.
- **Export Composed** (Assets-node menu: "Export Composed as USD/OBJ/STEP…",
  enabled only when generated AND up to date — `set_composed_export`, fed
  from the ONE predicate; worker `export_composed` → `src/export/compose_cli.py`
  `<fmt> <step> <out> <deflection> <angular> <scale>`): re-composes ALL
  generated assets + Static into the full scene, every occurrence placed at
  its pose from Root.Main. **Placement math: `X_occ = W_occ · R_root⁻¹`** —
  the occurrence's full world 4x4 from the root Main walk, times the inverse
  of the asset's baked CANONICAL-occurrence rotation (`_rot_inv4` = `[Rᵀ|0]`
  of occurrence_paths[0]'s Main transform). Asset geometry is `R_root·design`,
  so `X_occ·(R_root·p) = W_occ·p` reproduces Main exactly for every occurrence
  (the canonical one gets identity relative rotation). R_root is
  occurrence-independent → one file serves all N. A declared origin frame
  needs no extra term (baked upstream); Static has no bake → placed at
  identity. Each model loads with ITS OWN config section (suppressed
  exclusion + colors via `bake_effective_appearance`); all source docs stay
  alive until the write returns (own subprocess — no `_open_docs`
  interaction).
  - **USD (base/override two-layer at BOTH levels)**: user picks `main.usda`.
    - ⭐ **The SCENE is layered too** (not just each asset): the composed
      occurrences go to **`{stem}_base.usda`** (OVERWRITTEN every export) and the
      file the USER CHOSE becomes a create-once **override wrapper** referencing it
      (`write_override_wrapper(base_main, out_path, replace_unstamped=True)`), so
      scene-level settings authored there — stage metadata, an added light or camera,
      per-occurrence `over`s — SURVIVE a re-export. The base sits BESIDE the wrapper,
      so its relative `./assets/…` payloads still resolve. **Migration:** a
      pre-layering `main.usda` is a full composed scene that used to be overwritten
      every time, so leaving it in place would make a re-export look like a no-op —
      wrappers therefore carry a `customLayerData` stamp (`usd_writer.WRAPPER_STAMP`)
      and an UNSTAMPED `main.usda` is replaced. `replace_unstamped` is **never** set
      for the ASSET wrappers: theirs predate the stamp and hold real user overrides.
      The GUI's completion message names which file was rewritten and which is the
      persistent one, because `QFileDialog`'s generic "overwrite?" prompt implies the
      opposite. Verified `scratchpad/compose_main_override_test.py` (16) +
      `probe_testb2_main_layer.py` (8, the real testB2: 2022 meshes resolve from
      `main.usda`, a user edit survives a second full export).
    - In a sibling `assets/` dir each asset (+ Static) writes **TWO** files,
      named by slug:
    - **`{slug}_base.usd`** = the full authored export (`usd_writer.
      write_model_usd` — single root → the existing subtree body; multi-root
      Static → synthetic `/Root` Xform). **OVERWRITTEN every export.** Each
      model's own **Simplify Bodies** marks apply here (`load_one` returns them
      alongside `frames`/`joints`), so a merge multiplies across every occurrence
      that payloads the asset — see `export.md` § *Simplify Bodies*. `load_one`
      also VALIDATES them before anything is written, so a stale mark fails the
      build naming its model rather than part-way through authoring.
    - **`{slug}.usda`** = a thin **OVERRIDE wrapper** whose single default prim
      **references** `./{slug}_base.usd` (`write_override_wrapper`; the old name
      `write_asset_override_wrapper` is kept as an alias — the helper now serves the
      scene level too). **Created ONLY if absent — never clobbered**, so END-USER
      edits made in it (visibility, materials, added prims, retimed joints…) PERSIST
      across re-exports (a re-export rewrites only the base). Typeless def mirroring
      the base's default-prim NAME so the base's TYPE (a single-leaf asset's Mesh)
      shows through the reference.
    `write_composed_main` composes the SCENE BASE (`{stem}_base.usda`) — one prim per OCCURRENCE with a
    **PAYLOAD of the `.usda` WRAPPER** (NOT the base) RELATIVELY (folder
    relocatable) carrying `[R_occ | s·t_occ]` (asset points are meter-baked →
    only the translation scales), so the persistent overrides flow into the
    composed scene. **PAYLOAD, not reference** — the Omniverse-standard
    deferred-loadable arc for a large composed scene (Isaac loads/unloads
    occurrences on demand; matches the manual "add as payload" workflow — a
    plain reference loads eagerly + shows the wrong Stage badge). **Occurrence
    prims are TYPELESS defs** — a local Xform type would override a single-leaf
    asset's MESH default prim (Mesh is Xformable, so the placement op still
    works). N occurrences of one prototype PAYLOAD the SAME wrapper; live joint
    Xforms inside base files survive (they compose under the reference +
    payload). ⭐ **The asset ROOT is EXCLUDED from the composed base's live-Xform
    frame set** (`compose_cli.load_one` `frames.discard(single_root_cid)`): the
    root's own frame is carried by the OCCURRENCE PLACEMENT here, so a live
    `xformOp:transform` on the base's DEFAULT PRIM would COLLIDE with the
    occurrence's `AddTransformOp` (pxr: "xformOp:transform already exists in
    xformOpOrder" — a folder-rooted asset ALWAYS has a root frame, so this crashed
    every composed export of one). The root frame just bakes into the points
    instead; the composed world is IDENTICAL (frame-vs-baked invariant — placement
    absorbs it). CHILD/joint frames stay live. (Static is multi-root under a
    synthetic /Root, placed with no op, so it's unaffected + skipped.) Composition
    chain per occurrence, now FOUR arcs deep: `main.usda` —reference→
    `main_base.usda` —payload→ `{slug}.usda` —reference→ `{slug}_base.usd`.
    Verified: 1905 composed mesh worlds == expected within 2.4e-7 m; the
    base/override layering (`scratchpad/compose_override_layer_test.py`, 19 checks)
    confirms the base rewrites, the wrapper survives + carries a user override
    through the payload→reference chain into the composed scene.
  - **OBJ**: one merged `.obj` + deduped `.mtl` (`obj_writer.
    write_composed_obj` over `_write_components`, one item per occurrence,
    `S·W_occ` baked into vertices, occurrence-prefixed + within-model-deduped
    `o` groups, file-global vertex index).
  - **STEP**: `src/io_step/compose_step.py` — the compose doc's assembly
    structure is built EXPLICITLY from each model's walked tree
    (`AddShape(master, False)` per unique LEAF product / `NewShape` per
    ASSEMBLY product, deduped by `product_entry` → instancing preserved;
    `AddComponent(parent, child, rel_loc)` with `parent_world⁻¹·child_world`;
    every product AND instance label named; ONE `Transfer`, layers OFF).
    **NOT `AddShape(root, makeAssembly=True)`** — that decomposes by shape
    TOPOLOGY, which on real SolidWorks exports is deeper than the product
    tree (985 vs 349 nodes on the fixture). Per-face colors via
    `AddSubShape(product_label, face)` + `SetColor(label)`; **a COMPOUND
    leaf's product color does NOT survive the STEP round trip** (the writer
    styles sub-solids; the reparse style map keys on the master) — so
    compound leaves get EVERY face styled (explicit face colors + base fill).
    Verified on the fixture: counts/names/instancing/worlds exact (0.0 dev),
    colors 11/11. This explicit-assembly builder is effectively the
    "reconstruct a filtered ASSEMBLY doc" machinery OPEN TODO #1 wants —
    reuse it there.
- **Model Tree** (`src/gui/model_tree_panel.py`, above the component tree, left
  panel = wrapper QWidget[ModelTree / TreePanel("Component Tree" header)] at
  splitter index 0): roots **Main** (the base model — displayed name; internal id
  stays `MODEL_SOURCE`, see "Tree restructure") and **Assets** (BOTH always visible);
  **Static is the FIRST CHILD of Assets** (row hidden until generated); the other
  children are the GENERATED assets ONLY (files on disk — a marked-but-not-
  generated asset does NOT appear; a version-stale one shows greyed). Population
  = `cache.list_asset_variants` dir scan, display names via the config section
  matching the slug (orphan files show by slug). The panel **auto-sizes its
  height to exactly the visible rows** (`_update_height` → `setFixedHeight`), so
  everything in it is always visible without a drag divider.
  Click → `model_activated` → `MainWindow._on_model_activated` → variant
  `_LoadWorker` (fast cache load) → `store.activate(model)` (mismatch dialog:
  Cancel = stay on previous model) → **`_commit_model`** (the refactored body of
  `_on_load_ok`: swaps assembly/config/tree/selection/viewport/indicators/toolbar,
  sets `_pending_show3d` + `_pending_reset_view`, title suffix `[Static]`/
  `[Asset: N]`). A fresh model commit (file open OR a Model Tree switch) snaps the
  viewport to the default ISOMETRIC view (`_render_loaded` consumes the one-shot
  `_pending_reset_view` → `viewport.load(reset_view=True)` → `view_isometric`); a
  plain re-render (e.g. Show 3D at a new quality) keeps the current camera angle
  (`reset_camera` refit only). The `Assets` root
  is inert to clicks; its RIGHT-CLICK menu matrix (`_exec_assets_menu`;
  generated? marked? dirty?): nothing generated → **Generate Assets**
  (disabled until ≥1 mark, `set_can_generate`); generated + up to date →
  **Clear Assets** + the three **Export Composed as USD/OBJ/STEP…** items;
  generated + DIRTY + marked → **Update Assets** (primary) + Clear + composed
  (disabled, tooltip); dirty with NO marks → Clear only (Update is never
  offered with zero marks). Always last: **Delete All Configurations**
  (`delete_all_configs_requested` → `store.delete_all_model_sections` — every
  non-source section, NOT files; requires Source active). Dirty state =
  `set_assets_dirty` (italic Assets root + tooltip), composed availability =
  `set_composed_export(enabled, tooltip)` — BOTH fed by `_refresh_model_tree`
  from `cache.assets_up_to_date(step, store.source_asset_paths())`; the panel
  never computes the predicate itself. Each GENERATED model row — an asset OR the Static
  row — offers **Delete Configuration** (`delete_model_config_requested(model)` →
  `_on_delete_model_config` → `store.delete_model_section(model)`, which maps the
  model id to its `assets` section, Static included). Both deletes confirm, refresh,
  and GUARD against deleting the ACTIVE model's section (would be recreated on the
  next `save_active` — per-row blocks the clicked model, Delete-All requires Source
  active); they delete only config, not cache files (orphan files then show by slug
  — regenerate re-seeds a fresh section). Clear deletes ALL generated model FILES (every asset AND static; config
  sections KEPT; if a non-Source model is ACTIVE, switches to Source first —
  `_pending_clear_assets` — because Closing the live doc would dangle the render's
  labels). Generate requires the Source model to be active. Availability refresh =
  `_refresh_model_tree`.
- **Config: ONE file** (`name.cellsmith.json`, schema v3) via **`ModelConfigStore`**
  (scene_config.py): top-level `version/global_settings/model_settings/nodes` =
  Source; `assets: {Name: {slug, source_node, prototype, model_settings, nodes}}` holds EVERY
  non-source model. **Static is NOT a unique top-level section — it's a reserved
  entry `assets["Static"]`** (`STATIC_MODEL_NAME`, `slug="static"`, `source_node=""`)
  so it flows through the SAME code path as any asset (`_section`,
  `ensure_asset_section`, activate/save). `asset_entries()` excludes the reserved
  Static key (it has its own fixed Model Tree row, not a listed asset); its model
  id stays `MODEL_STATIC` and its cache variant stays `"static"` (only the config
  LOCATION was unified). `global_settings` lives ONCE at the top (file-wide);
  each model owns only its `model_settings` (orientation/origin/recolor) + `nodes`
  — no repetition. Every section's `nodes` are keyed by paths WITHIN that model's
  own tree (asset `.xbf`s renumber cids from c0001 — paths make sections portable).
  Exactly ONE section is materialized (path→cid) at a time (`activate(model,
  assembly)` overlays the shared globals + the section's model settings);
  `save_active` splices back (globals → top level ALWAYS; model_settings+nodes →
  the active section); inactive sections' DATA is preserved (never path-translated
  or pruned of nodes).
  `load/save_scene_config` remain as thin source-model wrappers. v1/v2 files
  migrate on load (`_migrate_raw`), which ALSO moves a legacy top-level `static`
  section into `assets["Static"]` (idempotent).
- **Minimal serialization**: every `_write` runs `_minimize_raw` — it re-dumps each
  section's `global_settings`/`model_settings`/`nodes` with `exclude_defaults=True`
  (by_alias for globals) and DROPS any sub-dict that ends up empty (and an empty
  `assets`). So the file only ever carries MODIFIED fields; a node/section that
  returns to defaults vanishes. Identity keys (`slug`/`source_node`/`prototype`/
  `version`) are untouched. This is why generated assets (default `+Z`/0 orientation,
  colors baked into sidecars) usually have NO `model_settings` at all. Loading
  re-supplies defaults, so the round-trip is lossless.
  - **Asset-section identity fields** (refreshed every generation): `slug` =
    filesystem-safe form of the display NAME → the cache subdir `asset-{slug}/`
    (NOT a STEP concept). `source_node` = the marked node's `/`-rooted tree PATH in
    the Source tree — **CONSUMED by `_launch_single_model_rebuild`** as the asset's
    `root_path` for a single-model regenerate (Edit Bodies / Origin / Restructure
    Apply on an ASSET). `prototype` = the marked node's STEP PROTOTYPE (referred
    product/master) name, `""` if it has none (recomputed every load, no sidecar).
  - **⚠️ `source_node` is FRAGILE — write path vs materialize path.** ONLY
    `ensure_asset_section` writes it (full Generate → all groups; Update → all
    DESIRED groups since the source_node fix — was NEW groups only, which left a
    kept asset's stale/empty source_node unrepaired). But `_section()` freely
    materializes an asset section `{model_settings,nodes}` **WITHOUT** source_node
    whenever a map is saved or the asset is activated — so an asset can be fully
    generated yet have a config section lacking source_node (repro'd
    `scratchpad/asset_source_node_test.py`). This caused the live bug "This asset's
    config has no source node recorded — regenerate assets first" on an asset Edit
    Bodies Apply even right after regenerating. FIX: `_launch_single_model_rebuild`
    RECOVERS `root_path` from the **assets stamp** (`canonical_path` by slug — the
    authoritative generation record, always written) when the config lost
    source_node, and HEALS the section (`ensure_asset_section` + save, keeping the
    section's split recipe/edits). Verified 8/8.
- **Tolerant loading**: `activate` validates each piece (`global_settings`,
  `model_settings`, and each `NodeConfig`) INDEPENDENTLY via `_coerce_model`, which
  defaults missing fields and drops only INVALID ones (iteratively removing the
  offending key and retrying) — a hand-deleted `model_settings` or one bad value
  no longer wipes the whole section, and one bad node can't drop its siblings.
  A file that won't parse as JSON at all sets `store.load_error`; the GUI
  (`_on_load_ok`) shows a `QMessageBox.warning` naming the file + error (previously
  this was a silent log line) and proceeds with defaults.
- **Generation seeding** (`_on_generate_assets`; the scene frame — orientation
  + datum — is entirely inside the ROOT MAIN stage generation splits, so
  NOTHING orientation-related is seeded or planned anymore; generation is
  GATED on `main_rebuild_required` — a stale Main prompts "Rebuild now?" and
  auto-continues into generation via `_pending_auto_generate`):
  - **PER-MODEL EDITS are SNAPSHOT-at-creation** (applied only when a section is
    FIRST created — `ensure_asset_section` returns a `created` flag and never
    re-seeds nodes, so regeneration can't clobber a model's own node customizations):
    - **Colors are BAKED into the sidecars**: `assets_build` applies the base's
      effective appearance (node overrides collapse to constants; recolor remaps
      base + per-face) to the in-memory base assembly BEFORE the positional
      transplant — generated sidecars snapshot exactly what the user saw; generated
      models start with empty recolor/no overrides (regenerate to re-sync).
    - **Node states copy**: HIDDEN marks inside an asset's subtree are
      path-remapped into its section (`_subtree_node_seed` — strip the asset-root
      path prefix; sibling `#n` dedup is identical by construction); surviving
      nodes' hidden marks copy into Static verbatim (`_static_node_seed`).
      SUPPRESSED subtrees are NOT seeded — generation physically EXCLUDES them
      from every generated model's source stage (see the setting taxonomy).
      Color overrides are NOT carried (baked); `is_asset` never nests.
- **Per-model everything**: mesh + edge caches live in the model's dir keyed by
  STAGE (vs that stage's `.xbf` mtime, so a regenerated model re-tessellates
  instead of serving stale meshes); Show-3D/edges/`edges_build` (argv 5 =
  variant, argv 6 = stage, both defaulting to root/main) and all THREE export
  CLIs take the model — `--model=<source|static|asset:Name>` as an optional
  FIRST arg (`parse_model_arg`); exports always read the model's MAIN stage.
  An asset exports with ITS OWN config section. STEP export always passes
  `layers=False` now (every exported doc is a baked stage — see the
  SetLayerMode gotcha).
- Source STEP revision does NOT auto-invalidate generated models directly
  (explicit-regeneration model) — but it DOES flag the root's main stage
  stale (open-flow rebuild → assets cleared with consent → regen offer).
  `_set_busy` gates the Model Tree (whose Assets menu hosts Generate/Clear).

