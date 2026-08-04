# Source→Main pipeline & caching

The two-stage (source/main) per-model geometry pipeline — the setting taxonomy and bake order, bake stamps and the `main_rebuild_required` predicate, the open/rebuild flow, per-asset stages and fast rebuilds, and frame conversion — plus the durable per-file cache directory layout (`.xbf`/mesh/edge/color caches, freshness, one-time migration, load-time prebuild). Read when working on model loading, baking, staleness, or the cache. Verify against `src/`; may lag.

---

## Source→Main pipeline (two-stage model dirs; SEED for the future README)
Every MODEL (the root scene = "Main" in the UI, Static, each asset) has TWO
geometry STAGES side by side in its cache dir: **`geometry-source.xbf`** (the
model's INPUT — the STEP parse for the root; the pruned base for
assets/Static) and **`geometry-main.xbf`** (after that model's OWN
edits/transform — **ALWAYS baked**; the GUI displays and exports a model's
MAIN stage, never source). The root model's dir is the cache dir itself; its
variant key is `ROOT_VARIANT = "root"` — `"source"`/`"main"` are STAGES now
and `variant_dir_for` REJECTS them as variant keys (fail loud on stale call
sites). Derived caches are stage-tagged: `colors-{stage}-v4.json`,
`mesh-{stage}-v2-l{}_a{}.npz`, `edges-{stage}-l{}_a{}.npz`.

**Setting taxonomy (KEEP THIS DISTINCTION CLEAR in code + docs):**
- **Source→Main (bake inputs — change ⇒ that model's main-stage rebuild; root
  changes also CLEAR generated assets):** per model: `structure`/`splits`/
  `origins` maps; ROOT ONLY: `up_direction`, `z_rotation_deg`,
  `origin_offset_x/y/z` (the Z-datum). Bake order = **splits → origins →
  structure → orientation+datum LAST** (recipes are stored in the SOURCE
  world frame). The root frame is `orientation.source_to_main_frame(up, zrot,
  origin)` = `p' = M·(p − origin)` (None when identity), prepended to every
  free root's location (`assets_build._bake_rotation` +
  `restructure_build._loc_from_matrix4`).
- **Main→Assets (generation-time):** asset marks, color overrides + recolor
  (baked into the generated sidecars), hidden seeds, and **Main-SUPPRESSED
  subtrees are PHYSICALLY EXCLUDED from every generated model's source
  stage** (`assets_build._suppressed_exclusion` — store-driven, occurrence-
  expanded like the Static asset removal; their marks don't seed; a changed
  suppression set applies on the next regeneration — the fast rebuild reuses
  the already-pruned source stage).
- **Main→Export (export-time):** `export_scale`, export mesh quality,
  suppressed nodes, color overrides/recolor, per-export origin choice
  (Global = the baked main origin (0,0,0) / Local = component frame). Export
  CLIs NEVER apply orientation or a global offset anymore — geometry is
  pre-baked; STEP export always passes `layers=False` (every exported doc is
  a baked stage now).
- **Bake stamps** (`bake-stamp.json` per model dir): the main stage's exact
  bake inputs + `cache_version` (generated models add informational
  `base_main_mtime` — the root main it was pruned from; a FAST rebuild
  carries the previous value). `cache.main_rebuild_required(step, variant,
  expected)` with `expected = store.source_to_main_inputs(model)` = stamp
  missing/mismatch (compares ONLY the expected keys) OR main xbf older than
  its sibling source xbf. Drives the open flow, the Generate-Assets gate, and
  "Rebuild Model".
- **Open flow** (`load_step`): source stale → parse subprocess → re-enter.
  Then peek the config: `main_rebuild_required` False → load the root MAIN
  stage; else rebuild — SILENTLY when no generated models exist, with a
  warn prompt when they do (they clear on bake success, then a one-click
  "Regenerate?" offer — `_pending_regen_offer`). A FRESH PARSE with asset
  marks in the config and nothing generated auto-generates unprompted after
  Main commits (`_pending_auto_generate` → `_generate_when_idle` poll).
- **Transform Source window** (`src/gui/transform_source_window.py`;
  Commands-toolbar "Transform Source…" + every Model Tree row's menu): the
  UNIFIED source→main editor for the ACTIVE model at BOTH levels (root
  Source→Main AND each asset/Static's own source→main — same button, same
  window). FOUR columns: (1) read-only SOURCE tree, header **"Source Structure
  (Read-Only)"** (collapsible arrow strip), (2) the EDIT tree, header **"Main
  Structure (Editing)"** (restructure gesture/colors/folders VERBATIM + drag/drop
  REFUSAL REASONS in the status label), (3) a viewport showing the model's
  SOURCE stage untouched (background-loaded; `mesh-source-*` + the
  `edges-source-*` overlay built ONCE by the edges_build subprocess when
  missing — `_ts_prepare_and_show`; never in-process, GIL), with the corner
  gizmo tracking pending orientation + a datum marker that follows the shared
  **Show Global Origin** toggle (`_refresh_transform_preview` reads
  `bus.show_global_origin`; subscribed via `_on_bus_changed_for_datum` — fixed a
  bug where it always showed), (4) settings pane (ROOT ONLY; hidden for assets)
  with a bold **"Settings"** heading, ~20% wider by default. The two trees have
  a **minimum width (220/240px)** and the splitter proportions are re-applied in
  `showEvent` via `_apply_initial_splitter` off the WINDOW width (`setSizes` in
  `_build_ui` runs while the splitter is 0-wide → the trees came up collapsed
  until a manual resize/maximize; the min-width floor + window-width proportions
  fix it). Column contents:
  a **"Z-Origin Orientation"** `QGroupBox` (Up (Z) + **Z-Rotation** combos + a
  **Clear** → +Z/0) and a **"Z-Origin Datum"** `QGroupBox` of three editable
  **X/Y/Z rows** `[label, spinbox, Pick]` + a Clear. Each spin sets its offset
  component; each per-axis **Pick** captures that axis from a viewport click
  (the viewport's built-in hover marker previews the point). Changing the
  orientation RESETS the datum to zero and paints the previously-set fields
  **yellow** (`_datum_highlight` — "re-enter in the new orientation"); editing
  or picking a field clears its highlight. **Edit Bodies** lives in this
  window's context menus (both trees + viewport) — a single LEAF or an
  ASSEMBLY (merge-then-edit; see Geometry edits) — recipes PENDING in a working
  copy; this window shows NO split bodies and an edited assembly is an opaque,
  movable node (children + same-prototype occurrences collapsed) —
  recipe-bearing nodes get the orange-diamond glyph in both trees, on EVERY
  occurrence sharing the recipe's `product_entry` (recipes resolve per product
  at bake), and right-click Edit Bodies/Clear from ANY occurrence edits the ONE
  shared recipe — `_open_edit_bodies` redirects to its owning occurrence
  (`_recipe_owner_for`). Selection
  syncs tree↔tree↔window-viewport (the old translate-to-main-viewport sync
  is GONE); transient Hide/Show drives the WINDOW's viewport only. ONE Apply
  = validate → (root, when generated models exist) warn-clears prompt → save
  structure map (+`rekey_nodes`) + split map + (root) settings → ONE bake
  (root → main bake + regen offer; asset/Static → fast rebuild);
  `_restructure_rollback` restores ALL pieces on bake failure. Up change
  resets the pending datum. Open auto-switches the Model Tree to the edited
  model first (`_open_transform_source_when_idle` poll).
- **Frame conversion (CORRECTNESS-CRITICAL):** split planes / origin frames
  are STORED in the SOURCE frame (they bake before the frame). SPLIT recipes
  are now authored IN the Transform Source window on the SOURCE-stage
  geometry — natively source-frame, NO conversion. ORIGIN frames are still
  picked in the main window on the BAKED Main, so MainWindow converts those
  at the boundary: `_main_bake_frame()` +
  `geometry_edits.transform_origin_frame` (forward on open, `mat4_inv_rigid`
  backward on Apply; `transform_split_recipe` is kept as a helper). Identity
  settings = no-op; root model only (assets carry no orientation). Cut
  PROVENANCE picks are NOT converted (display-only; re-editing re-picks).
- **Per-asset stages (same machinery at both levels):** full generation
  writes BOTH stages per model — prune from root main + bake the canonical
  occurrence's Main ORIENTATION (rotation-only `R_root`; see Asset splitting)
  → save the SOURCE stage + its sidecar → apply the model's own maps → save
  the MAIN stage + sidecar + mesh/edge caches + stamp. `rebuild_only` with a
  fresh asset source stage takes the FAST path
  (`build_restructured_variant(base=(asset_variant, STAGE_SOURCE))` — no
  re-prune of the root; ~1s vs ~34s on testB1); absent (legacy-migrated dir)
  → full re-prune fallback. **The fast path is ALSO skipped when the asset's
  source stage is STALE vs the current root main** (`_fast_rebuild` compares the
  asset stamp's `base_main_mtime` to the root main mtime) — else Root body edits
  (splits/merges) baked into Main AFTER the source stage was pruned would never
  reach the asset on an Update/fast rebuild. The Transform Source window (and the origin
  editor's base-path translation) loads an asset's own source stage as its
  base when present (`_base_load_target`), else the stub-from-root fallback
  (trees only — the window then opens WITHOUT a 3D preview).

### Caching (durable, transparent) — one cache DIRECTORY per source file
The scene config lives beside the STEP as `foo.cellsmith.json`; all other caches
go inside a sibling directory `foo.cellsmith.cache/` (via `cache.py` /
`scene_config.py`). Layout (see the pipeline section above):

    foo.cellsmith.cache/                  ROOT model dir (= the cache dir)
      geometry-source.xbf                 STEP parse result
      geometry-main.xbf                   baked Main stage
      bake-stamp.json                     the main stage's bake inputs
      colors-source-v4.json / colors-main-v4.json
      mesh-{stage}-v2-l{}_a{}.npz / edges-{stage}-l{}_a{}.npz
      layout-v2                           migration marker (never delete)
      static/  asset-{slug}/              same file pattern inside each

`cache.ensure_cache_dir()` creates the directory; every write site routes
through the stage-aware helpers (`save_cache`, `save_color_sidecar`,
`save_mesh_cache`, `mesh_ops.save_edges_npz`), which all take
`(variant, stage)`.
- **Freshness**: a stage's derived caches are judged against that stage's own
  `.xbf` (`stage_reference_mtime`); the root SOURCE xbf itself against the
  STEP. Main-vs-source staleness is the SEPARATE `main_rebuild_required`
  predicate (stamp + sibling mtime). Generated stages are explicit artifacts —
  the STEP being newer never invalidates them directly.
- **Migration** (`_migrate_cache_layout`, one-time, pure renames — no reparse
  of multi-minute caches; called from `cache_is_fresh`/`list_asset_variants`):
  top-level untagged files → source-stage tags; an old `main/` variant dir
  folds into the root's main stage; a generated dir's single xbf becomes its
  MAIN stage (its source stage stays absent until the next full generation).
  The `layout-v2` marker file prevents new-layout files (where both stages
  legitimately coexist) from ever being re-interpreted as legacy.
- Helpers: `variant_dir_for`/`ensure_variant_dir`, `cache_path_for(step,
  variant, stage)`, `list_asset_variants` (dir scan on the MAIN stage),
  `asset_variant(name)`, `delete_variant_files` (rmtree a non-root subdir),
  `delete_main_stage` (main files + stamp only, source kept),
  `delete_variant_derived(…, stage)`, bake-stamp helpers, and
  **`close_variant_docs(step, variants, stages=both)`** (evict from
  `_open_docs` + `app.Close` — MANDATORY after a stage is regenerated/deleted,
  else the next `Open` of that path returns an EMPTY doc). `asset_slug()` +
  the variant/stage constants live in `scene_config.py` (pure, no OCC) and are
  re-exported by `cache.py`.
- **`.xbf` geometry cache**: first open of `foo.step` parses it (slow, minutes
  for ~600 MB) and writes the root `geometry-source.xbf` (binary XCAF); later
  opens load it in seconds (~48× faster) and skip STEP parsing. Colors/names/
  labels/structure survive in the `.xbf`. `cache_is_fresh` requires BOTH the
  `.xbf` and a version-matched color sidecar, so a `CACHE_VERSION` bump still
  forces a reparse.
- **Mesh cache**: `Show 3D` writes tessellated meshes keyed by stage +
  deflection params, so re-rendering is instant. **Edge cache**: feature edges
  extracted ONCE per stage+deflection (subprocess) — instant toggles after.
  `edges_build` now **tessellates + writes the mesh cache itself when it's
  missing** (previously it required a pre-built mesh cache), so ONE subprocess
  call builds both mesh + edges from just the `.xbf`.
- **Source-stage PREBUILD on load** (`MainWindow._maybe_prebuild_source`): after
  a file settles, a SILENT background `edges_build` on the ROOT SOURCE stage
  (`root`/`source`) builds its mesh + edge caches at the display quality, so
  opening **Transform Source** on Main is instant (it renders that stage). It's
  one-shot per file (`_want_source_prebuild`, armed in `load_step`), polls until
  the load/render pipeline is idle and Main is active, skips when the caches are
  already fresh, and does NOT gate `_busy()` (the user keeps working).
  `_open_transform_source` AWAITS `_prebuild_proc` (poll) so it never starts a
  duplicate build racing the same cache files; `load_step` kills a prebuild from
  a previously-open file.
- **Color sidecar**: the part-appearance colors resolved from the STEP style
  layer at parse time can't be recovered from the `.xbf` (no presentation
  layer there), so they're persisted per stage and reapplied on cache load.
  Written by `load_model`, the parse subprocess (`cache_build`), and every
  bake/generation (both stages).
- `*.cellsmith.cache/`, `*.cellsmith.json`, `.env_setup.lock` gitignored. **The
  `scratchpad/` dir (all the dev-only probe/test scripts — the repo has no formal
  test suite, so tests live there) is ALSO gitignored** — RECURSIVELY: the
  `scratchpad/` pattern ignores the whole subtree (any nested subdirectory, any
  depth) so future scratchpad subfolders are covered (verified via `git
  check-ignore`). Untracked; never committed.

