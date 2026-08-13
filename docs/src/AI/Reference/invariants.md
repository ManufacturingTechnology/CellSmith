# Invariants — cross-cutting rules you must not break

Correctness-critical rules that span subsystems. Terse by design; each points to the deep doc. Breaking one silently corrupts geometry, hard-crashes the process, or regresses the STEP path. Verify against `src/`; may lag.

- **Bake order is splits → origins → transforms → structure → orientation+datum**, everywhere (the root Main bake AND the per-asset/Static post-passes). Recipes/frames are stored in the SOURCE world frame because they bake *before* orientation. → `pipeline-and-caching.md`, `geometry-edits.md`.
- **No BLAS matmul in the GUI (VTK) or export (pxr) process.** Never `@` / `np.dot` / `np.linalg` there — it hard-crashes (`0xC06D007F`) once VTK/pxr DLLs are loaded. Use elementwise math (`orientation.py`) or a subprocess worker (mesh least-squares, trimesh slicing). This also bans self-orienting `pv.*` helpers (`pv.Sphere`/`Arrow`/`Cone`) — build from raw `vtk*Source` + `pv.wrap`. → `occ-vtk-gotchas.md`.
- **The STEP / B-rep path stays byte-neutral.** Mesh import, SF/CGB, datums, and joints are additive and must not change STEP output bytes or touch the default OCC code paths. → `mesh-import.md`, `occ-vtk-gotchas.md`, `decisions.md` (ADR-0002).
- **One identity, two representations.** `component_id` (cid) is the internal key everywhere (parse → GUI → export); the config FILE keys nodes by `/`-rooted tree PATH. Translate cid↔path only at the file boundary (`build_path_maps`). → `scene-config-and-orientation.md`.
- **Layers stay decoupled.** OCC, VTK/PyVista, and USD (pxr) imports each stay inside their layer so a broken optional dep can't take down the app. **`src/gui/__init__.py` must stay EMPTY** (no eager Qt import, or headless workers drag in Qt). → `architecture.md`.
- **USD is meters, `metersPerUnit=1.0`.** Isaac reads raw magnitudes as meters and ignores `metersPerUnit`; the full export transform is baked into mesh POINTS (reference-safe), not a root Xform. → `export.md`.
- **Frames are stored in the SOURCE world frame** and converted at boundaries (origin frames picked on Main are converted back on Apply). Identity settings = no-op. → `scene-config-and-orientation.md`, `geometry-edits.md`.
- **Verify headlessly via conda** (no GPU in the dev env → the VTK render path can't run; the user live-tests rendering). **`conda` is usually NOT on `PATH`** — invoke it by full path through an env var so it's portable across users/machines (verified working):
  - **PowerShell:** `& "$env:LOCALAPPDATA\anaconda3\Scripts\conda.exe" run --no-capture-output -n CellSmithEnv python scratchpad/<t>.py`
  - **⭐ ALWAYS pass `--no-capture-output`, and redirect stdin (`< /dev/null` in bash).**
    Without it `conda run` CAPTURES the child's stdout and re-prints it via
    `print(response.stdout, file=sys.stdout)` (`conda/cli/main_run.py:120`). Under
    **Git Bash** that stdout is **cp1252**, so any non-ASCII in a test's output (`→ ⊥ ·
    ✓ —` — most suites here use them) raises `UnicodeEncodeError` **inside conda**.
    conda then prints an ERROR REPORT and **prompts** *"Would you like conda to send
    this report…? [y/N]"* — with no interactive stdin that blocks **forever** (observed:
    a 34-minute "hung" test that ran in 3 s under PowerShell). `--no-capture-output`
    streams the child directly and removes the re-encode entirely; `< /dev/null` (plus
    `CONDA_REPORT_ERRORS=false`) turns any *other* future conda crash into a fast
    failure instead of a hang. **Symptom to recognise:** a run that hangs with no output
    in bash but passes in PowerShell is this, not your code.
  - The env lives at `%LOCALAPPDATA%\anaconda3\envs\CellSmithEnv`; a **syntax-only** check may call the env python directly (`& "$env:LOCALAPPDATA\anaconda3\envs\CellSmithEnv\python.exe" -m py_compile <files>`), but **anything importing numpy/OCC/trimesh MUST go through `conda run`** — the bare env python leaves the BLAS/LAPACK DLLs off `PATH`, so `np.linalg`/`@` hard-crashes. → `occ-vtk-gotchas.md`, `mesh-import.md`.
- **⭐ A restructure Apply must PRESERVE map-only state.** `diff_edited_tree` rebuilds the
  structure map from the editor's rows, which carry only `(ident, parent, name)` — a
  folder's `origin` and `transform` live ONLY in the map, so it MUST be given `prior=` and
  carry them forward by FOLDER ID. Omitting that is silent data loss with a large blast
  radius: one testB2 Apply nulled all six robot folders' frames + poses, which (via
  `asset_root_declares_origin`) un-did every asset's de-rotation and so moved every
  authored body origin. **Generally: if a field is invisible in the editing surface, that
  surface's serializer must preserve it explicitly.** → `restructure-and-transform-source.md`,
  `decisions.md` (ADR-0008).
- **⭐ A TOLERANT drop is never silent.** Asset/Static generation deliberately drops a
  geometry-edit recipe that no longer fits (one stale edit must not block a whole build) —
  but a drop in a build subprocess whose stdout the GUI reads *only on failure* looked like
  a clean generation while a rigged asset lost every body, body origin and joint. Any new
  tolerant path must append a structured record (`geometry_edits_build._record_drop`) that
  reaches the user (`assets_build.WARN_PREFIX` → `main_window._report_build_warnings`).
  Single-model FAST rebuilds stay STRICT and raise. → `geometry-edits.md`,
  `decisions.md` (ADR-0007).
- **⭐ ONE derivation of "which components own a live frame".**
  `model/live_frames.live_frames_and_joints` is it — the USD writer authors live
  Xforms + `UsdPhysics` from it, and the OBJ CLI and the GUI use the SAME set to
  judge Simplify-Bodies marks. A second derivation would let a mark pass the
  click-time dialog and then hard-fail the export, or be fatal for USD but silently
  fine for OBJ. It lives in the MODEL layer (not `src/export/`) precisely because
  `src/gui/` must not import `src/export/`. → `geometry-edits.md`, `export.md`.
- **⭐ A merged (Simplify Bodies) mesh may never swallow a prim something else
  addresses.** A merge is one prim with one transform, so a live frame or a joint
  body inside it would be destroyed — `UsdPhysics` binds to exact paths, and a
  frame'd subtree's points are authored relative to it. Checked against **STRICT
  descendants only**: the marked node's own frame survives as the merged prim's
  `xformOp`, which is what makes "mark the link that IS Body1" work. Refused at
  mark time AND fatal at export time, because a joint can be added later.
  → `export.md`, `decisions.md` (ADR-0010).
- **⭐ An Edit-Bodies recipe is bound to the exact SET OF SOLIDS it was authored on**
  (`i0..iN` = preorder indices + an `initial_count` fingerprint). Any change to what sits
  under the target invalidates it, and a count-PRESERVING change would silently re-map
  bodies onto different solids. So: never change a rigged subtree's membership without
  warning first (`main_window._confirm_recipe_membership_change`), and treat
  `initial_count` as a fingerprint, not a mere sanity check. Content-addressed identity is
  the real fix — **CS-133**, deferred. → `geometry-edits.md`, `decisions.md` (ADR-0007).
- **⭐ A semver prerelease MUST become a `~` version in Debian, never `-`.**
  `0.1.0-alpha.1` as a Debian version parses `alpha.1` as the *debian revision*, which sorts
  **after** plain `0.1.0` — so `dpkg` ranks the prerelease as NEWER than the release it
  precedes. `0.1.0~alpha.1` sorts before it. Proven with `dpkg --compare-versions`:
  `0.1.0~alpha.1 lt 0.1.0` → true, **and** `0.1.0-alpha.1 gt 0.1.0` → also true. Handled by
  `packaging/debian/make_deb.sh` (`DEBVER="${VERSION/-/~}"`) and asserted by its own
  self-check. → `packaging.md`, **CS-143**.
- **`conda run` cannot execute a `python -c` containing NEWLINES** — it raises
  `NotImplementedError: Support for scripts where arguments contain newlines not
  implemented`. Any multi-line probe must be written to a FILE and run as
  `conda run … python path/to/probe.py`. (This is separate from, and additional to, the
  `--no-capture-output` rule above.) → **CS-150**.
- **⭐ Every path in `packaging/cellsmith.spec` must be ABSOLUTE** — built with the spec's
  own `R(*parts)` helper (`ROOT = SPECPATH/..`), never a bare relative string. The spec does
  not live at the repo root and PyInstaller resolves relative paths against **three
  different bases**: the spec's dir for `Analysis(scripts=/datas=/binaries=)` and
  `EXE(icon=/version=)`, the CWD for `hookspath`/`runtime_hooks`/`pathex` and any plain
  `open()`. No single relative convention can satisfy all three, and the failure is
  asymmetric — the script path dies loudly (`packaging\src\__entrypoint__.py not found`)
  while a mis-anchored `datas` or `EXE(icon=)` would just quietly omit the fonts/icon.
  Guarded by `tests/test_packaging_spec.py`. → `packaging.md`, **CS-138**.
- **Fail loud on ambiguous STEP structure;** log unnamed/merged/colorless components. Grouping components into links is human judgment — never auto-split fused bodies (no code can un-fuse them). → `architecture.md`.
