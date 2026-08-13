# Design decisions (ADR log)

Architecture Decision Records for deliberate, non-obvious calls — especially ones a future agent might be tempted to "fix." Seeded from the "⭐ DESIGN DECISION" / "do NOT re-fix" notes in the old CLAUDE.md; **add an entry whenever a real design fork is decided.** Verify against `src/`; may lag.

## How to use this file
- **Before reversing a deliberate design, read the relevant ADR.** If your change conflicts with it, **surface the conflict + the entry's "Revisit if" condition** to the user rather than silently overriding or silently complying. (Re-*evaluating* when an assumption changed is healthy; re-*litigating* a settled call with no new information is not.)
- Each entry carries: **Context · Decision · Alternatives · Revisit if · Confidence · Status**.
- **Confidence** = how firm (high → defend it; low/tentative → stay open). If the user decides something without stating confidence and it can't be inferred, **ask**.
- **Status** = Accepted / Superseded-by-`<id>` / Deprecated. On reversal, don't delete — mark the old one Superseded and write a new entry referencing it.
- Entry ids are informal for now (the status-ledger ID scheme is designed separately); keep them stable once assigned.

---

## ADR-0001 — Asset-root de-rotate: world = robot frame (robot upright)
- **Context:** When an asset root declares a custom origin, how should the standalone asset be oriented vs. how it sits in the composed scene?
- **Decision:** Generation uses `R_root = identity` when the asset root declares a custom origin (`scene_config.asset_root_declares_origin` drives generation + compose identically). The asset's LOCAL frame becomes the chosen origin (de-rotated into the robot's coords); the composed world still reproduces Main exactly.
- **Consequence people try to "fix":** selecting the asset root then shows a WORLD-ALIGNED component-origin triad. **This is correct, not a bug** — the robot's frame IS the asset's world frame here, and the robot sits upright to match.
- **Alternatives:** bake the full frame `F` onto the asset root (robot tilted like Main, root triad shows the basis) — rejected: that makes the global-origin/gizmo/world-axes show the SCENE frame, not the robot's, which the user rejected. The two describe the same frame two ways and cannot both reflect the robot.
- **Revisit if:** the user wants the standalone asset to appear tilted like Main (scene frame) instead of upright (robot frame).
- **Confidence:** High (user-confirmed 2026-07, "do NOT re-fix"). **Status:** Accepted.
- See `asset-splitting-and-compose.md`, `geometry-edits.md`.

## ADR-0002 — B-rep / STEP is priority #1; mesh import is additive & subordinate
- **Context:** A mesh-file (OBJ/STL/USD) import path was added alongside the OCC/STEP core.
- **Decision:** The B-rep/STEP (OpenCASCADE) workflow is the center of the app. Mesh import is a strictly additive, early-branching PARALLEL path that must never complicate, slow, or regress the STEP path; STEP output stays byte-neutral.
- **Revisit if:** mesh becomes the primary workflow (not anticipated).
- **Confidence:** High. **Status:** Accepted. See `mesh-import.md`, `invariants.md`.

## ADR-0003 — Digital shadow, not simulation
- **Context:** The tool prepares rigged assets for Isaac Sim.
- **Decision:** Poses come from telemetry (a digital shadow). Do NOT author collision meshes, mass, inertia, or dynamics unless explicitly asked.
- **Revisit if:** a real physics articulation (not a kinematic shadow) is ever required.
- **Confidence:** High. **Status:** Accepted.

## ADR-0004 — No USD instancing in the authored robot USD
- **Context:** Composed/authored robot USD output.
- **Decision:** Author plain referenced USDs — no USD instancing in the authored robot USD. (OCC's own STEP re-export preserving the source file's instancing is fine and desirable — a different thing.)
- **Revisit if:** authored-USD scale makes instancing necessary AND Isaac handles it for the rig.
- **Confidence:** Medium-high. **Status:** Accepted.

## ADR-0005 — Packaging is onedir, not onefile
- **Context:** The PyInstaller distributable; the app re-launches its own exe as worker subprocesses.
- **Decision:** onedir. onefile would re-extract the ~1.4 GB payload on every worker launch.
- **Revisit if:** the worker model changes so re-extraction cost disappears.
- **Confidence:** High. **Status:** Accepted. See `packaging.md`.

## ADR-0006 — Prototype-NAME grouping for assets
- **Context:** Real STEP files export the "same" robot as several distinct products sharing one prototype name (one per posed "Free Drag" variant).
- **Decision:** Group asset occurrences by prototype NAME (when it's not a useless CAD fallback), so those merge into ONE asset (built from the first occurrence in preorder); the exported drag articulations are intentionally lost (telemetry poses the rig).
- **Revisit if:** a file legitimately needs same-named prototypes kept as separate assets.
- **Confidence:** Medium (user-confirmed for the current files). **Status:** Accepted. See `asset-splitting-and-compose.md`.

## ADR-0007 — Edit-Bodies body identity is POSITIONAL; a misfit recipe is DROPPED and reported, not re-bound
- **Context:** A `SplitRecipe` identifies its initial bodies as `i0..iN` — indices into
  `_solids_of(target_compound)` in preorder — plus an `initial_count` fingerprint, and
  every `BodyOp` targets those ids. So the recipe is tied to the **exact set of solids it
  was authored on**. Changing what sits under the target (a Main restructure moving a part
  into an asset's folder, a suppression change) makes it stop fitting. Live incident on
  testB2: moving one part into `/MoldTending` took that subtree from **15 solids to 141**,
  so the recipe no longer applied and the asset lost all 7 links — with them its 6 body
  origins and 7 joints. Worse, a count-PRESERVING membership change would silently re-map
  `i0..iN` onto different solids, which is not detectable at all.
- **Decision (current):** keep positional identity, and make the misfit **loud** rather
  than trying to re-bind. Two guards, both shipped:
  1. asset/Static generation stays TOLERANT (one stale edit must not block a whole build)
     but now emits a structured `CELLSMITH-WARN` record per drop — model, `authored →
     actual` counts, the body paths that were NOT created, and the joints thereby
     dangling — which `main_window._report_build_warnings` shows on a SUCCESSFUL build;
  2. Transform Source **Apply on Main warns BEFORE writing anything** when a move changes
     the membership of a subtree a generated model's recipe targets
     (`_confirm_recipe_membership_change`), offering Cancel as the default.
  The single-model FAST rebuild path is deliberately **strict** and raises instead.
- **Alternatives:** content-addressed initial-body identity (`body_sort_key`'s rounded
  volume+centroid, or the owning leaf's `product_entry` + a within-leaf solid index) so a
  recipe RE-BINDS across membership changes and reports only genuinely new/missing solids.
  **Not rejected — deferred**, tracked as **CS-133**. It changes the durable `SplitRecipe`
  format (migration for every existing recipe + remapping every op target), so it wants a
  deliberate window, not a slot between bug fixes.
- **Revisit if:** re-grouping after rigging turns out to be common in practice (the metric
  the user is deliberately gathering), or a count-preserving silent re-map is ever
  observed. Then do CS-133.
- **Confidence:** Medium — the *warn-don't-rebind* call is explicitly an interim, chosen
  because (b) converts data loss into a dialog. The user has stated they **do** want the
  content-addressed fix long-term. **Status:** Accepted (interim). See `geometry-edits.md`,
  `restructure-and-transform-source.md`, status `CS-132`/`CS-133`.

## ADR-0008 — Map-only state must survive a re-serialization of the thing that carries it
- **Context:** `diff_edited_tree` rebuilds the structure map from the Source Editor's rows,
  which carry only `(ident, parent, name)`. A restructure folder's `origin` and `transform`
  live ONLY in the map, so rebuilding each `NewAssembly` from the rows reset both to None —
  **any** Apply silently destroyed every folder frame and pose in the model. One testB2
  Apply nulled all six robot folders, which (via `asset_root_declares_origin`) also un-did
  every asset's de-rotation and so moved every authored body origin.
- **Decision:** a serializer that reconstructs a container from a partial view MUST be
  handed the prior value and carry the unrepresented fields forward, keyed by the STABLE
  identity (`nK` folder ids — never reused, so a rename or re-parent keeps the frame).
  Generalised: **if a field is not visible in the editing surface, the editing surface's
  serializer must preserve it explicitly.**
- **Alternatives:** put folder frames in a separate side map keyed by folder id (would
  dodge the problem but split one concept across two homes); make the editor rows carry
  frames (couples the view to geometry it does not display).
- **Revisit if:** folder state grows enough that a side-map keyed by folder id becomes the
  cleaner home.
- **Confidence:** High — this was pure data loss with no upside. **Status:** Accepted.
  See `restructure-and-transform-source.md`, status `CS-131`.

---

## ADR-0009 — The PR gate builds the full release artifacts, not a cheap approximation
- **Context:** `ci.yml`'s `build-*` jobs ran PyInstaller only — no tar.gz, no `.deb`, no
  zip, no Inno installer — deliberately, to keep the gate ~15 min shorter. The packaging
  half therefore ran for the first time during a release. On the 2026-08-04 release push
  the two costliest defects were both in that unrun half: `make_deb.sh` died with
  `printf: write error: Broken pipe` the first time it saw a real (2111-file) payload, and
  the release version guard had never worked at all — an unanchored parse of
  `src/__version__.py` that matched the module docstring, inlined identically in *both*
  workflows.
- **Decision:** the PR gate runs the **same build as the release**, defined **once** in
  `.github/actions/build-{linux,windows}/action.yml` (composite actions) and `uses:`d by
  both workflows. Release-specific work — collecting artifacts, uploading, tagging,
  creating the dev branch — stays in `release.yml`. Artifact-existence assertions live in
  the shared action, not the release-only collect step, so "no installer was produced"
  fails on the PR. `tests/test_ci_release_parity.py` enforces all of it.
  Additionally: `version-check` validates that `__version__` parses and is semver on
  **every** PR, not only PRs into `release/X.Y`.
- **Alternatives:** (a) keep the cheap gate and accept release-day discovery — rejected,
  it is the most expensive place to find a packaging bug and it blocks a release;
  (b) duplicate the release steps into `ci.yml` as YAML — rejected, duplicated steps are
  what produced two identically-broken version parses; (c) run the full build only on PRs
  into `release/*` — rejected, that still lets a defect sit on `main` and it is the
  feature→main PR that introduces it.
- **Revisit if:** gate wall-clock becomes the bottleneck. The escape hatch is a
  `paths`-filter or a label-gated job (skip the build when a PR touches only docs) —
  **not** a cheaper build, which is precisely the thing that failed.
- **Confidence:** High — the trade was tested empirically and lost twice in one week.
  **Status:** Accepted. See `packaging.md` § *The PR gate runs the RELEASE build*,
  status `CS-160`.

## ADR-0010 — Simplify Bodies merges TRIANGLES, and a stale mark is fatal EVERYWHERE
- **Context:** Isaac Sim degrades badly when a robot/CNC link is hundreds or
  thousands of separate `UsdGeom.Mesh` prims — the cost is per-prim/per-draw-call,
  not per triangle. "Mark Simplify Bodies" (CS-162) exports a marked subtree as one
  mesh. Two forks had to be settled.
- **Decision (a) — triangle concatenation, NOT an OCC boolean.** `_baked_tris`
  already puts every component in the same export space, so `_author_merged_mesh`
  is vertex-index offsetting + `np.concatenate`. Triangle count and per-triangle
  colors are unchanged; no seam is invented.
  - **Alternatives:** `BRepAlgoAPI_Fuse` on the solids — rejected: minutes-to-hours
    on thousands of solids, fails often, and destroys the per-face color indices
    `_per_triangle_rgb` depends on. It also solves a problem nobody has (fewer
    *surfaces*) instead of the one measured (fewer *prims*). Note this matches the
    existing precedent: Edit-Bodies "Merge" is already deliberately compound
    grouping, not a boolean (`geometry_edits_build.merge_bodies`).
  - Corollary: because the writer has NO UsdShade materials and NO GeomSubsets,
    merging is **color-lossless** — concatenated `uniform` displayColor says
    exactly what N separate prims said. Verified on real geometry: `testB2` Static,
    755 bodies → 1 prim, 3.78 M triangles and 924 k per-triangle colors identical.
- **Decision (b) — a mark whose subtree contains a live frame or joint body is
  REFUSED, and a STALE mark is FATAL on every export path** (subtree USD, composed
  USD, OBJ). Checked against **STRICT descendants only** — the marked node's own
  frame is fine and is preserved, which is what makes "mark each link" (the link IS
  the joint's Body1) the workflow.
  - **This deliberately diverges from ADR-0007's** "asset generation stays TOLERANT,
    warn-don't-block" stance for dropped split recipes. Justified because the
    failure modes are opposites: a dropped recipe **loses authored data**, so
    blocking a build over it costs more than it saves; a silently-unmerged asset
    **loses nothing** but silently reproduces the exact performance problem the
    feature exists to fix, and the user would not notice until Isaac is slow again.
    The user chose strict-everywhere explicitly (2026-08-06).
  - The strictness is made livable by catching it EARLY, not by softening it:
    `_set_simplify_nodes` refuses at click, and `_confirm_frame_breaks_simplify`
    warns when Create Joint / ReOrigin would invalidate an existing mark.
  - **Alternatives:** auto-split the merge at each frame boundary (fewest clicks,
    but a mark then silently means something different from what was clicked);
    tolerant + `CELLSMITH-WARN` (rejected per above).
- **Revisit if:** (a) Isaac turns out to be bottlenecked by `uniform` displayColor
  rather than prim count — then group by color into one mesh per material instead;
  (b) strict export refusals become a nuisance in practice, i.e. marks are
  routinely invalidated by later rigging. Then reconsider tolerant-with-warning.
- **Confidence:** Medium-high — (a) is measured and firm; (b) is a user preference
  chosen with the tradeoff stated. **Status:** Accepted. See `export.md` §
  *Simplify Bodies*, `kinematic-joints.md`, status `CS-162`.
