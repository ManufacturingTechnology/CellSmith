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
