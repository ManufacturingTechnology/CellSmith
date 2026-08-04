# Mesh-file import (OBJ/STL/USD + more)

The additive, subordinate mesh-import path (`src/io_mesh/`) that gives triangle-mesh files near-full pipeline parity with STEP: the reader/cache/slice/build/assets workers, GUI dispatch (`load_file`→`load_mesh`), the numpy-`@` / subprocess isolation rules, mesh faces, and what gates off (analytic B-rep features). Read when touching mesh import or `has_brep` capability gating. **STEP / B-rep stays priority #1 and byte-neutral.** Verify against `src/`; may lag.

---

## Mesh-file import — OBJ/STL/USD + more (BUILT; headless-verified, GUI live-test PENDING)
This document is the as-built reference (the original design plan was fully implemented). **Priority:
strictly ADDITIVE/SUBORDINATE to the B-rep workflow (see the ⭐ HARD PRIORITY note
near the top) — it NEVER touches the STEP/OCC code paths (they stay default) and
is structurally a PARALLEL path gated by `has_brep`.** What shipped:
- **Goal (delivered — FULL PIPELINE PARITY)**: open triangle-mesh files (OBJ,
  STL, USD, +PLY/GLTF/GLB/3MF/DAE/OFF) so meshes-without-B-rep can be inspected,
  restructured (Transform Source), body-edited (Component Editor — the SAME
  split/merge/transform/decompose UI, driven by the mesh engine), re-origined
  (Set Origin), reoriented (datum/orientation), asset-split + composed-exported,
  and re-exported to USD/OBJ. Only genuinely-analytic B-rep features gate OFF
  with a REASON tooltip: STEP export (subtree AND composed), adjustable
  re-tessellation quality, and analytic edge/arc/Face-B-Rep snapping (the last
  auto via `has_brep` — the CGB degrades to vertex/tessellation picks).
- **New package `src/io_mesh/`** (import-light `__init__`; trimesh/pxr are
  WORKER-ONLY):
  - `formats.py` (pure): `MESH_EXTENSIONS`, `is_mesh_path`/`is_usd_path`, and
    `assembly_has_brep` (== `any(c.shape is not None)` — the SAME derivation as
    `SelectionCapabilities.from_assembly`; reused, not duplicated).
  - `mesh_reader.py` (WORKER-ONLY): `read_mesh(path)→Assembly`, `shape=None`.
    trimesh path uses `load(process=False, force="scene", split_object=True,
    group_material=False)` to keep the `o`/`g`-group LEAVES (not collapse to one
    mesh/material); hierarchy/transforms via `scene.graph.to_edgelist()` (NOT
    `graph.get`, which CRASHED). USD path (pxr) recurses `GetChildren`, world via
    `ComputeLocalToWorldTransform` **transposed** (Gf row-vector → our M·p, the
    silent trap), fan-triangulates n-gons, honors `leftHanded`. Colors: OBJ
    material `main_color`/`baseColorFactor`, USD per-face `displayColor`
    (count==faceCount)/constant/GeomSubset material → the OCC `(color, face_colors,
    tri_faces)` convention. `.mtl` is OPTIONAL/first-class (a materialless OBJ →
    grey base, no crash).
  - `mesh_cache.py` (pure numpy/json + reuses `io_step.cache` helpers): a
    **mesh-only `structure-{stage}.json`** stands in for the `.xbf` (id/name/
    parent/transform/prototype/entries/has_mesh). Colors reuse the color sidecar,
    geometry the mesh `.npz` under a FIXED native key (`l0_a0` — a mesh never
    re-tessellates → one mesh per stage). `save/load_mesh_model`,
    `mesh_model_is_fresh`, `mesh_main_rebuild_required` (mesh twins of
    `cache_is_fresh`/`main_rebuild_required`). **The `.xbf`/XCAF cache is the
    B-rep backend, UNCHANGED.** `io_step/cache.py` got 3 tiny STEP-safe edits:
    `structure_path_for` + a `.xbf`-absent→structure-JSON fallback in
    `stage_reference_mtime`, and the two color-sidecar shape guards softened
    `c.shape is None` → `c.shape is None and not c.has_mesh` (STEP byte-identical;
    includes mesh leaves).
  - `mesh_slice.py` (WORKER-ONLY, trimesh): `run_body_ops_mesh` mirrors
    `geometry_edits_build.run_body_ops` — decompose (union-find connected
    components, no graph dep), `run_one_cut` (native `slice_mesh_plane`, cap via
    shapely+earcut; world-frame plane → local via `world4⁻¹`), `merge_bodies`
    (concat), transform (`body_transform_local` = the `body_transform_world4`
    math, numpy). Lineage-ids match `SplitRecipe.replay_ids()` EXACTLY
    (`body_sort_key` order); `split_stub_assembly` predicts the same tree.
    manifold3d NOT required (native slicing is primary). **Decompose WELDS
    vertices by POSITION** (`_weld_indices` → `_connected_components(tris,
    verts)`): a CAD tessellation meshes each B-rep face independently and
    duplicates the boundary vertices, so index-based connectivity would shatter
    ONE part into an island per face (testD1 "Ground": 986 index-islands → 2 real
    bodies). Welding (quantize to `span·1e-6`, `np.unique`) merges coincident
    positions for connectivity WITHOUT altering the stored geometry.
  - `mesh_build.py` (WORKER-ONLY + engine): the numpy-native `restructure_build`
    twin. Same bake order **splits → origins → structure → orientation+datum**;
    because mesh `vertices` are LOCAL and `transform` is ABSOLUTE world,
    reparent/re-origin/reorient are pure matrix updates (no geometry surgery).
    `apply_splits_mesh` (verified against `split_stub_assembly`),
    `apply_origins_mesh` (leaf: `v→inv(F)·W·v`, transform=F; assembly: transform=F),
    `apply_structure_mesh` (`plan_tree` + geometry carry), `apply_orientation_
    datum_mesh` (left-mult `source_to_main_frame`). Consumes the IDENTICAL plan
    shape `restructure_build` does.
  - `mesh_cache_build.py` (WORKER): import → write the root source stage.
  - `mesh_assets_build.py` (WORKER): the numpy-native `assets_build` analog —
    generate mesh asset/Static models. The prune is a PURE Assembly rebuild
    (`_prune_assembly`: keep/remove cids + rebase transforms; NO XCAF surgery):
    each asset keeps its subtree rebased by `R_root·W_canonical⁻¹` (canonical
    occurrence's Main orientation, own origin); Static removes every marked
    occurrence (base world frame, no rotation). Writes both stages via
    `mesh_cache.save_mesh_model`, the MAIN via `mesh_build.build_mesh_main_variant
    (base=(variant,SOURCE), tolerant=True)`, + the SAME `assets-stamp.json`.
    REUSES the pure `assets_build` helpers (`_suppressed_exclusion`,
    `_validate_roots`) + `asset_marks.*` verbatim. Three new `--worker`s in
    `src.main._WORKERS`: `mesh_cache_build`/`mesh_build`/`mesh_assets_build`.
    `cache.py` gained `stage_geometry_present` (`.xbf` OR structure JSON) so
    `list_asset_variants` / `assets_up_to_date` / `cache_is_fresh` see mesh
    variants (they only checked `geometry-main.xbf`). Composed export
    (`compose_cli`) branches to `load_mesh_model` for a mesh scene (USD/OBJ work;
    the `W_occ·R_root⁻¹` placement is backend-agnostic); STEP compose is refused
    (no B-rep).
- **GUI wiring (`main_window`)**: `load_file(path)` dispatches STEP→`load_step`
  (unchanged), mesh→`load_mesh` (mirrors load_step: fresh source cache → in-proc
  `_LoadWorker` [mesh branch → `mesh_cache.load_mesh_model`]; else the
  `mesh_cache_build` subprocess → re-enter; then `mesh_main_rebuild_required` →
  `_launch_main_bake` [mesh branch → `mesh_build`] or load Main). `_render_mesh_
  model` renders directly (triangles already on the components; no tessellate, no
  quality knob; edges in-thread from the combined VTK mesh — no OCC edge
  subprocess). `_render_stale` False for mesh; `_model_has_brep()`/`_is_mesh_
  source()`/`_assets_worker()` helpers. Export CLIs (`usd_cli`/`obj_cli`) branch
  to `load_mesh_model`. usd/obj writers select leaves by `has_mesh` (was `shape
  is not None` — that dropped every mesh leaf; STEP identical since a STEP leaf's
  has_mesh is True post-tessellation). **Edit Bodies (Component Editor)** opens
  for a mesh leaf/assembly — `EditBodiesWindow._mesh_mode` routes decompose /
  test / preview / transform through `mesh_slice` (bodies are `MeshBody`, not OCC
  shapes; `MeshBody.shape` is None so shared display code works; the split
  cut-count, gizmo centroid + preview transform, and old-body overlay branch on
  `_mesh_mode`; the CGB is vertex/tess-gated; mesh-assembly merge-then-edit builds
  the stub via `mesh_build._assembly_edit_source`).
  **CRITICAL — the mesh CUT must run in a SUBPROCESS, never the GUI process:**
  trimesh's plane slice calls `numpy.linalg.svd`, a LAPACK/BLAS call that
  HARD-CRASHES (`0xC06D007F`) once VTK's DLLs are loaded — the same ban as
  numpy `@`. So a recipe with a SPLIT op is replayed via the `mesh_ops_worker`
  subprocess (`_mesh_finals` → `_run_mesh_op_worker`, a blocking QProcess), and
  `_commit_split`'s piece-count runs a `count_cut` in that worker too. Decompose /
  merge / transform stay in-process (pure numpy — BLAS-free), so opening the
  editor + decomposing is instant; only actual cuts pay the subprocess round-trip.
  The worker reuses the SAME `mesh_slice` engine the bake uses (no divergence).
  **CRITICAL follow-on — a worker subprocess needs the conda env's `Library\bin`
  on its `PATH`, or the SAME `0xC06D007F` crash happens INSIDE the (VTK-free)
  worker.** A worker is spawned with `sys.executable` (the env's `python.exe`)
  but WITHOUT conda activation, so `<env>\Library\bin` is NOT on PATH. pythonocc
  finds its TK DLLs via `os.add_dll_directory` (so the STEP workers survive), but
  **numpy's MKL/LAPACK delay-loads its sibling DLLs via `PATH` only —
  `os.add_dll_directory` does NOT satisfy MKL (probe-verified: `adddll` mode
  still crashed, `path` mode worked)** → `numpy.linalg.svd` (trimesh's slice)
  hard-crashed the mesh_ops_worker with exit `-1066598273` (= `0xC06D007F`). FIX:
  `src/main._ensure_worker_dll_path()` (called at the top of `_run_worker`,
  BEFORE the worker imports numpy/trimesh) prepends the conda activation DLL dirs
  (`<env>\Library\bin` first) to `os.environ["PATH"]` — dev/Windows only (skipped
  when frozen: PyInstaller bundles the DLLs). Launch-independent (fixes conda-run,
  QProcess, direct); harmless for the STEP workers (OCC+LAPACK coexist,
  probe-verified). This is why the app no longer NEEDS `conda run` to reach the
  mesh workers, though `run.bat` still uses it. **Generate / Update / Clear
  Assets + Export Composed USD/OBJ** work for mesh (`_assets_worker()` picks
  `mesh_assets_build`; `set_can_generate` no longer gates mesh out). STEP export +
  STEP compose stay gated (no B-rep). **"Show B-Rep Edges" stays ENABLED for a
  mesh model** (user decision — briefly disabled, then re-enabled): a STEP model
  overlays true topological B-rep edges; a mesh has no B-rep, so the SAME toggle
  overlays VTK's **dihedral feature edges** instead (`extract_feature_edges` by
  crease angle on the combined mesh — the tessellation approximation of "hard"
  edges, `_start_edges_thread` / `build_edges_from_loaded`). Both are useful
  clean-contour overlays; "Show Tess Edges" (the FULL triangle wireframe) is the
  separate, noisier all-edges overlay.
- **Process isolation (numpy-`@` ban)**: GUI(VTK)/trimesh-worker/pxr-worker are
  DISJOINT processes. GUI never imports trimesh/pxr (only `formats`/`mesh_cache`,
  which are numpy/json). trimesh may use `@`; GUI + pxr paths use `orientation.py`
  elementwise math. NOTE for DEV: running the env python DIRECTLY (not via
  `conda run -n CellSmithEnv`) leaves the env's BLAS DLLs off PATH → even plain
  numpy `@` HARD-CRASHES (exit 127) — use `conda run` for all headless dev/tests.
- **Faces on meshes (HYBRID partition)**: `tri_faces` from material/subset groups
  (OBJ per-triangle color, USD per-face displayColor/GeomSubset) else derived
  coplanar facets via numpy quantized-normal grouping (`trimesh.facets` needs a
  graph engine we don't depend on). ONE authoritative mesh (no view/export
  fidelity split; fixed native key). Mesh face SELECTION works via the existing
  Face→Tessellation path. TODO (cross-cutting, deferred with the alpha work):
  per-FACE color OVERRIDE persistence (needs a config schema for per-face
  overrides) + whole-group highlight for Face→Tessellation.
- **Deps (pip-only; NOT conda-forge; in `packaging/environment.yml`)**: `trimesh`,
  `manifold3d` (OPTIONAL — only trimesh's boolean backend; the slicer uses native
  `slice_mesh_plane`/`section`, graceful when absent), `mapbox_earcut`, `scipy`,
  `shapely` (the last two back trimesh slicing + cap triangulation). Python 3.12
  has prebuilt cp312 wheels for ALL of them → no source build. Contingency for a
  wheel-less python/arch: `pip install manifold3d --config-settings=cmake.args=
  "-DMANIFOLD_PAR=NONE"` (the `../AMT-DTP-Isaac-Sim-Service-Private/coprocessor/
  dev.bat` workaround) — wired as a NON-fatal fallback in `build.bat`/`makefile`.
  Bundled via `packaging/hooks/hook-trimesh.py` (+ io_mesh hiddenimports in the
  spec; the mesh workers ride `_WORKERS`).
- **Verified headless** (`conda run -n CellSmithEnv`; 8 suites in
  `scratchpad/mesh_test_*.py`): reader on testD1.obj (with AND without `.mtl`) +
  testE1.usd + a box STL; cache round-trip; mesh_slice
  (decompose/cut/merge/transform + `replay_ids` parity); mesh_build E2E (faithful
  copy, orientation bake, split, origin world-preservation, structure move);
  Component-Editor engine (`decompose_count`/`run_body_ops_mesh return_all`/
  `body_transform_world`); mesh ASSET E2E (import → root main → mark → generate
  asset+Static → stamp → `assets_up_to_date` → composed USD/OBJ, STEP refused);
  `--worker` dispatch; mesh USD/OBJ export round-trip. **STEP regression guard:
  unchanged (byte-neutral color sidecar + faithful STEP export).** GUI/GL render +
  picking + the Component-Editor live pick/preview on a mesh are USER live-test.
- **Fixtures** (in `test_files/`, round-trip from testC1): `testD1.obj`
  (+`testD1.mtl`; test WITH and WITHOUT the `.mtl`), `testE1.usd`, `testC1.step`.
- **Mesh follow-up (deferred)**: per-FACE color OVERRIDE persistence + whole-group
  highlight for Face→Tessellation — cross-cutting (needs a config schema for
  per-face overrides), belongs with the alpha/transparency round. (Edit Bodies and
  asset splitting/composed export are NO LONGER deferred — full parity shipped.)

