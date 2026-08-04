# Scene config (v3) & orientation math

The persisted scene-config schema (`GlobalConfig`/`ModelSettings`/`NodeConfig`, `ModelConfigStore`, minimal + tolerant serialization, color resolution, cid↔path identity, cross-revision reconciliation) and the pxr/OCC/VTK-free orientation math (`orientation.py`, elementwise, never BLAS `@`). Read when touching config load/save, per-model or global settings, color baking, or any source→main / export transform. Verify against `src/`; may lag.

---

## Scene config (persisted per file — schema v3: GLOBAL vs per-MODEL split)
`src/model/scene_config.py` (pydantic): `SceneConfig{version, global_settings:
GlobalConfig, model_settings: ModelSettings, nodes: {component_id: NodeConfig}}`.
Since **v3** the old all-in-one global_settings is SPLIT:
- **`GlobalConfig`** = FILE-WIDE workflow/view preferences, stored ONCE at the top
  level and shared by every model: display + export mesh quality, `export_scale`
  (mm→USD units, default 0.001), `show_edges`, `origin_indicator`. Mesh-quality
  fields keep SHORT Python attr names (`deflection`, `angular_deg`,
  `export_deflection`, `export_angular_deg`) but **serialize with GUI terminology**
  via pydantic aliases (`allowable_linear_mesh_error` etc.; dumped with
  `model_dump(by_alias=True)`; `AliasChoices` + `populate_by_name` still LOAD the
  legacy short keys). Angular is DEG (→ radians only at `tessellate_shape`).
- **`ModelSettings`** = PER-MODEL data (Source / Static / each Asset owns its own):
  `up_direction` (±X/±Y/±Z, source axis → world +Z), `z_rotation_deg`
  (0/90/180/270), `origin_offset_x/y/z` (mm, THIS model's frame), **`recolor`**
  (`List[ColorRemap]`, the "Recolor" dialog). `SceneConfig` needs
  `ConfigDict(protected_namespaces=())` (pydantic reserves the `model_` prefix).
- **Migration**: `ModelConfigStore._migrate_raw()` upgrades v1/v2 on load — model
  keys move out of each `global_settings` into `model_settings`; v2 sections'
  per-section global_settings copies are DROPPED (top level wins). Idempotent.
`NodeConfig` = hidden, suppressed, color_override(RGB 0..1), **is_asset** (blue
dot; source model only). Saved as `<base>.cellsmith.json` on every change;
`update_node()` prunes back-to-default nodes. The FILE also carries the per-model
`static`/`assets` sections managed by **`ModelConfigStore`** (see Asset splitting) —
`load/save_scene_config` are thin wrappers over it for the Source model, and
saves are read-modify-write: `global_settings` ALWAYS writes to the top level
(editing quality while an asset is active persists file-wide);
`model_settings`+`nodes` write into the ACTIVE section; inactive sections
round-trip verbatim.
- **Color resolution.** Base/per-face colors come from the parse (see OCC gotchas).
  On top: `resolve_color_overrides` (per-node, nearest ancestor-or-self wins) and the
  global per-color `recolor`. **VIEWPORT** applies these separately: node overrides
  per-component (`set_overrides`, they WIN) + recolor **per-cell** on the base color
  (`set_recolor` ← `recolor_rules_8bit`), so multi-colored parts keep per-face detail.
  OBJ export is one-color-per-component and uses `resolve_effective_colors`
  (`resolve_global_recolor` of the base color + node overrides). The
  PER-FACE-AWARE export bake is **`scene_config.bake_effective_appearance(cfg,
  assembly)`** (override wins → constant; else base + per-face get the recolor
  remap) — the ONE shared implementation behind usd_cli, export_cli,
  assets_build's generation bake, and compose_cli (the four used to inline
  identical loops). Matching is 8-bit quantized (`_quantize`). `unique_colors`
  (base + per-face) feeds the Recolor dialog; `recolored_component_ids`
  (per-face aware, minus overridden) drives the purple-square indicator.
- **Identity**: `component_id` remains the internal key EVERYWHERE (parse→GUI→export).
  The config FILE, however, keys nodes by readable **tree path** that is ABSOLUTE
  from an implied root and always starts with `/` (`/Arm/Link1`) — the top-level
  assembly name is OMITTED so paths survive a renamed root across STEP revisions.
  `build_path_maps(assembly)` + `save/load_scene_config(..., assembly)` translate
  cid↔path at the file boundary (duplicate siblings get `#n`). The intended behaviour
  is that the **implied root is NOT shown in the tree** (`assembly.implied_root_ids()`
  = roots that have children); its children are the top-level rows. **TEMPORARY: the
  flag `tree_panel.SHOW_IMPLIED_ROOT` is currently `True`, so the root IS shown as a
  row (to allow whole-scene export) — this does NOT affect paths (still `/`-rooted);
  flip it back to `False` to revert (OPEN TODO).** A childless single-solid root stays
  visible (`/Solid1`). `load_scene_config` returns `(config, unmatched)`: keys that don't
  resolve in THIS file are dropped and listed; legacy `Root/…` and raw-id keys still
  migrate (`_resolve_node_key`).
- **Config reuse across STEP revisions** (updatability): rename a `name.cellsmith.json`
  to match a newly-received STEP and open it — matched paths carry their settings over;
  `_confirm_config_mismatch` shows the unmatched entries and asks **Apply matched /
  Cancel**. Cancel aborts BEFORE any window state or the config file is
  touched. **Apply matched PERSISTS the pruned section immediately**
  (`_save_config` right after the commit — live-test fix: an ASSET section's
  stale key, e.g. a suppressed node that generation now physically excludes,
  re-prompted on EVERY switch because nothing ever wrote the prune back).
  **Modal-dialog-in-ok-handler gotcha (cost the same live test — EMPTY
  viewport with a populated tree)**: the mismatch dialog's nested event loop
  dispatches the load worker's `finished` BEFORE `_commit_model` runs, so
  `_cleanup_worker` consumed nothing and the `_pending_show3d` flag dangled —
  `_commit_model` now schedules `_maybe_auto_show3d` via a 0-timer (no-ops
  while a worker is busy; cleanup keeps the normal path — never double-
  renders). ANY future modal prompt inside a worker ok-handler has this
  hazard. See OPEN TODO for the planned, more-robust reconciliation + change
  highlighting.
- up_direction/z_rotation_deg + the origin offset are the ROOT model's
  **Source→Main bake inputs** (see `pipeline-and-caching.md`) — consumed ONLY by the
  Main bake, edited ONLY in the Transform Source window, and BAKED into the
  geometry (exports never reapply them; the viewport shows the truly-oriented
  Main). `export_scale` (default 0.001 = mm→m) tunes USD units (Isaac reads
  magnitudes as meters, metersPerUnit=1.0). ADD NEW SETTINGS HERE — decide per
  field: file-wide preference → `GlobalConfig`; Source→Main bake input or other
  model data → `ModelSettings` (bake inputs must ALSO join
  `source_to_main_inputs` + the stamp); per-node → `NodeConfig`.

## Orientation math (`src/model/orientation.py`, pxr/OCC/VTK-free)
`orientation_matrix(up_direction, z_rotation_deg)` = 3x3 source→export (chosen axis →
+Z + spin). `export_transform(up, rot, scale, origin)` = 4x4 `p' = scale·M·(p−origin)`
(origin = local-origin shift). `source_to_main_frame(up, rot, origin)` = the
root's unit-scale bake frame (None when identity); `frame_point`/`frame_dir`
apply a rigid 4x4 elementwise. `mat4_mul`/`mat4_inv_rigid`/`_mat3_*` are
elementwise — **never `@`** (BLAS matmul crashes with VTK *or* pxr loaded).
Shared by the Main bake, the recipe frame conversion, the writers' local-origin
shift, and the Transform window's indicators so the frame is computed one way.

