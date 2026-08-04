# CLAUDE.md

## Project: STEP → Isaac Sim rigging tool (CAD inspector + link grouper)

### What this project is
A desktop GUI tool to prepare messy imported-STEP robot models for use as
rigged assets in NVIDIA Isaac Sim, for a **digital shadow** (telemetry-driven
pose visualization, NOT physics simulation).

The tool loads a STEP file, shows its component/assembly tree alongside a 3D
viewport, and lets the user select components in the tree (highlighted in 3D)
and in the 3D view (highlighted in tree). The user groups components into
kinematic **links**, defines **joints** between links, and exports a rigged
USD asset for Isaac Sim.

This exists because commercial tools (PiXYZ) are cost-prohibitive and the
SolidWorks → STEP → Isaac CAD Importer workflow loses hierarchy and produces
unusable, un-riggable geometry.

### ⭐ HARD PRIORITY — B-rep is the center of the universe (MAINTAIN THIS)
**The B-rep / STEP workflow (OpenCASCADE) is PRIORITY #1 — the center of this
application. Everything revolves around it.** A planned mesh-file import feature
(OBJ/STL/USD and more, via trimesh + pxr) is **strictly ADDITIVE and
SUBORDINATE — a far-behind bonus**. It must **never complicate, slow, or risk
regressing the STEP path**. Architecturally this is enforced by keeping the
XCAF/OCC code paths untouched and default, adding mesh support as an early-
branching PARALLEL path, and gating via capabilities that are a **no-op (full
capability) for STEP** so STEP behavior stays byte-for-byte unchanged. When in
doubt, protect the STEP workflow. See `docs/src/AI/Reference/mesh-import.md` (the mesh path is now BUILT).


### Current focus — Selection Filter + Construction Geometry Builder
The SF/CGB redesign is **fully implemented** (headless/offscreen-verified; GL live-test pending). As-built: `docs/src/AI/Reference/selection-and-cgb.md`. Design spec: `docs/src/AI/Specs/construction_geometry_builder_definitions.md`.

### Context / constraints (important — do not suggest working around these)
- CAD package is **SolidWorks Design Standard**. Cannot switch packages,
  cannot assume premium add-ins. URDF export from SolidWorks is off the table
  (models are imported STEP dumb-solids with no mates/feature tree).
- Robots are **downloaded STEP models**, not clean vendor robot models. They
  may have good component names or may be "Solid1, Solid2…". Handle both.
- Six robots + a static manufacturing cell. Robots need rigging; cell does not.
- Real files are **large**: test1 ≈ 875 MB / ~20k components / 112k colors;
  test2 ≈ 637 MB / ~2k components. Design for thousands–tens-of-thousands of
  parts. Test files live in `test_files/` (gitignored).
- **Digital shadow, not simulation**: we pose joints from telemetry. We do NOT
  need collision meshes, mass, inertia, or dynamics tuning.
- **No instancing** in the *authored robot USD* (author plain referenced USDs).
  (Note: OCC's own STEP *re-export* preserves the source file's part instancing —
  that's fine and desirable; the "no instancing" rule is about the USD rigging output.)
- Cost matters. Prefer free/open-source libraries only.

## Environment (Windows) — how to run
- **conda**, not a pip venv: `pythonocc-core` has no pip wheel. Env name `CellSmithEnv`.
  `packaging/environment.yml` is the source of truth; `dev.bat` creates it, `run.bat` runs
  `python -m src.main` (forwards args, e.g. `run.bat test_files\test2.step`).
  `build.bat` / `make build` produce the PyInstaller distributable (see "Packaging").
- **Pin `python=3.12`** (PySide6/pyvista wheels lag on 3.14) and
  **`pythonocc-core=7.9.3=novtk_*`**. The default `all_*` build pulls VTK →
  `viskores`, whose header paths blow past Windows' 260-char MAX_PATH and crash
  extraction. We use pyvista's own VTK (pip) for the viewport, so `novtk` is fine.
- `dev.bat` has a lock (`.env_setup.lock`) so two concurrent env-creates can't
  corrupt the env. Don't run dev/run twice in parallel during first setup.
- Interpreter for VS Code / launch.json: `…/anaconda3/envs/CellSmithEnv/python.exe`.
- **Headless runs when `conda` isn't on `PATH`** (common here): `& "$env:LOCALAPPDATA\anaconda3\Scripts\conda.exe" run -n CellSmithEnv python …` (PowerShell); env at `%LOCALAPPDATA%\anaconda3\envs\CellSmithEnv`. Full guidance in `docs/src/AI/Reference/invariants.md`.


### Coding conventions / preferences
- Python 3.12 (env is pinned there). Type hints. Small, testable functions.
- Keep OCC, VTK/PyVista, and USD imports isolated to their layers.
- One source of truth for component IDs across parsing → GUI → export.
- Fail loud on ambiguous STEP structure; log unnamed/merged/colorless components.
- No collision/mass/inertia authoring unless asked (digital shadow scope).
- Verify OCC behaviors headlessly (small scripts) before wiring into the GUI —
  interactive GL behavior still needs the user. **But offscreen rendering DOES work
  here** — see the note below before assuming you can't see your own output.

### When something doesn't work — diagnose, don't report inability
**"X doesn't work" is a symptom, not a finding.** Work the **`diagnose` skill** (it should fire automatically; invoke it if it doesn't) and report what it produced. Never conclude a technical limitation from a first error message — a missing library, a wrong flag, and an unsupported feature look identical at that distance. **Show evidence, not assertions**: the command run and what it returned; mark unverified claims ❓. **Prefer a sandbox** for anything exploratory (scratch script, throwaway container, temp dir, WSL) — a probe that cannot damage anything needs no caution, and being wrong there costs nothing.

**⭐ RED LIST — finding an option is not permission to take it.** Proceed alone on reversible, in-scope, technical choices. **STOP AND ASK** when the change would:
- add or remove a **dependency**
- **cross a layer boundary** (OCC / VTK / USD / GUI)
- change an **on-disk format, config schema, or export output**
- alter **behavior a user would notice**
- **contradict `docs/src/AI/Reference/decisions.md`**
- be **hard to reverse** (deletes data, rewrites history, touches many files)
- touch the **B-rep/STEP path's** behavior (see the hard-priority section above)

Otherwise proceed and say what you did. **In a throwaway sandbox treat the list as advisory** — "hard to reverse" mostly evaporates there. **Test for "is this architecture?"** — would the change alter what another part of the system can *assume*? If yes, ask. If it only changes how this part accomplishes something, it isn't.

### Units / conventions
- SolidWorks STEP is typically **mm**. USD/Isaac default is **meters, Z-up**.
  Convert units on USD export and make up-axis explicit (config, not hardcoded).

### Known hard problem (flag, don't pretend to solve)
Grouping components into links is **human judgment** — the tool assists, it does
not automate the semantics. If a STEP file has **fused/merged bodies** (a link is
not a separable solid), fusion destroyed the **seam information**, so no code can
*infer* where to split — **never auto-split**; detect/warn when a component spans
what should be multiple links. The user then separates it **manually with the Edit
Bodies Split tool** (a core CellSmith feature — it exists precisely so this doesn't
require a CAD license). Recovering the *original* boundary is impossible; producing
a usable separation is normal workflow.


### Dependencies
All free / open source; full list in `docs/src/AI/Reference/architecture.md`. Core: `pythonocc-core` (novtk), `PySide6`, `pyvista`/`pyvistaqt`, `numpy`, `pydantic`, `usd-core` (`pxr`, export only), `trimesh` + `scipy`/`shapely`/`mapbox_earcut` (mesh import).

### When helping on this repo
- If a robot is a real commercial arm (UR, KUKA, Fanuc, ABB…), existing URDFs / Isaac assets may make custom rigging unnecessary — ask early.
- Before rigging, check whether STEP bodies are **separated** (not fused). No code can *infer* a lost seam, so never auto-split — but the user can split manually via Edit Bodies (that's the point of the Split tool), so fused geometry is a workflow step, not a blocker.
- **You CAN see your own rendering — offscreen works** (probe-verified 2026-07-30, correcting a long-standing claim here that it doesn't). With `QT_QPA_PLATFORM=offscreen`: `QApplication` constructs, `pyvista.Plotter(off_screen=True).screenshot()` produces a correctly shaded/occluded image, and `QWidget.grab()` captures widgets. **One gotcha:** the offscreen platform has **zero font families**, so captured text is tofu boxes — fix with `QtGui.QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\segoeui.ttf")` in the harness. Write PNGs and **read them back** to check your work. ❓ Unconfirmed whether this used hardware or software GL (`PySide6/opengl32sw.dll` is present); **interactive** behavior (camera feel, depth peeling, hover) still needs the user. Details + the three test tiers: `docs/src/AI/Scratch/ai-metaanalysis.md` §3.1.
- Verify OCC/config logic with small scripts (`conda run --no-capture-output -n CellSmithEnv`; **`--no-capture-output` is REQUIRED** — without it conda re-encodes captured stdout to cp1252 under Git Bash, crashes on any non-ASCII test output, and then HANGS on its crash-report prompt. See `docs/src/AI/Reference/invariants.md`). Test files (gitignored): `test_files/test1.step` (875 MB / ~20k parts, needs color recovery), `test2.step` (637 MB / ~2k, native colors).
- **Cite your sources.** When a claim comes from outside this repo — a standard, a vendor doc, a library's behavior, a spec — **include the source as a markdown link in the doc you write**, not just in chat. Prefer primary sources (ISO/standards bodies, official library docs, the vendor's own spec) over blog posts. When a claim is *unverified*, mark it **❓** rather than stating it flatly. When a claim comes from a probe you ran, say so and say what you probed — that is a source too.
- Before reversing a deliberate design decision, check `docs/src/AI/Reference/decisions.md` — if your change conflicts with an entry, surface the conflict + its "Revisit if" condition rather than silently overriding or complying.

### Keeping docs current (living documentation)
Treat `CLAUDE.md` + `docs/src/AI/**` as a **living mirror of the code**, not write-once. **After any non-trivial `src/` change, update the matching `Reference/*.md` (and `status.md` for state/decisions) in the SAME turn**, before finishing. This keeps the docs a faithful snapshot so the session can be **compacted at any time without losing context** — the docs, not the chat history, are the durable memory. Record non-obvious learnings (a gotcha, a design decision, a new invariant) in the right doc as you go. Conventions: `docs/src/AI/index.md`.

### ⭐ Run the `flush` skill — what must survive the conversation ending
A conversation ends in one of two ways and **both lose the transcript**: the session closes, or the context is compacted into a lossy summary. So the rule is not "flush before compacting", it is **flush before the knowledge can be lost** — before ending or closing a session, before `/compact`, and after any dense stretch that settled things. Don't wait for a trigger event; a disconnect is not a trigger you get to plan for.

Always on disk before that point: (1) the **uncommitted-file list** (this tree carries a large uncommitted build); (2) which **live-GL tests are still pending**; (3) the **active `CS-###` ids** under discussion and their decisions; (4) any **cache/bake state** established (which stages are fresh, what was rebuilt); (5) **open questions asked of the user that were not answered**. Everything else is recoverable from `docs/src/AI/`.

`Reference/*.md` mirrors *code*, so a docs-or-design-only session can settle a pile of decisions that never leave the chat — `status.md` is where those go. A `PreCompact` hook **blocks a manual `/compact`** until some doc has been written this session (auto-compact only warns); one-shot bypass is `touch .claude/.skip-flush-gate`. Note the gate only guards the *compaction* path — **nothing at all guards a session simply being closed**, which is why the skill's first trigger is you remembering. Details in `docs/src/AI/index.md` → Conventions.

## 📁 Documentation map
Detail lives in `docs/src/AI/`. Read the file whose topic matches your task. Landing page + doc-system conventions: `docs/src/AI/index.md`. Rules you must not break: `docs/src/AI/Reference/invariants.md`. Term definitions: `docs/src/AI/Reference/glossary.md`. Open work + status: `docs/src/AI/status.md`.

| Read this `Reference/` file | When you're working on |
|---|---|
| `architecture.md` | the layer layout / where a subsystem lives / dependencies |
| `occ-vtk-gotchas.md` | any OCC/XCAF/STEP-export or VTK geometry code — **read first**; the no-BLAS-matmul ban |
| `pipeline-and-caching.md` | model load/bake, Source→Main stages, staleness, the cache |
| `scene-config-and-orientation.md` | config load/save, per-model/global settings, color baking, transforms |
| `viewport-interaction.md` | viewport rendering, picking, camera, the settings strip, Measure |
| `selection-and-cgb.md` | the Selection Filter / Construction Geometry Builder |
| `node-state-and-color.md` | hide/suppress/override, Recolor, tree indicator glyphs |
| `geometry-edits.md` | Edit Bodies / Component Editor, Set Origin, Component Transform |
| `restructure-and-transform-source.md` | tree restructuring + the Transform Source window — **read its ⭐ BLAST RADIUS section before diagnosing anything that broke "after a restructure"** |
| `asset-splitting-and-compose.md` | asset marking/generation, the Model Tree, composed export |
| `kinematic-joints.md` | joint definition + USD joint authoring |
| `export.md` | STEP/USD/OBJ subtree export |
| `mesh-import.md` | mesh (OBJ/STL/USD) import + `has_brep` gating |
| `testing.md` | **tests/CI** — tiers, marker polarity, and the Linux system packages offscreen rendering needs |
| `packaging.md` | the build, spec, hooks, installer, the **`.deb`**, and the **GitHub Actions CI/release workflows** |
| `licensing.md` | Apache-2.0 outbound, third-party licenses, what the build must attribute — **read before adding a dependency or shipping a build** |
| `decisions.md` | before reversing a deliberate design (ADR log) |

The SF/CGB design spec is `docs/src/AI/Specs/construction_geometry_builder_definitions.md`.

**User docs** live in `docs/` (mkdocs-material, built via `docs/makefile` under WSL — its `venv/` is a WSL venv, so don't run it from Git Bash). `docs_dir` is `docs/src`. **Two builds:** `make` uses `mkdocs.yml` and **excludes `AI/`** (the public site); `make dev` uses `mkdocs.dev.yml`, which cancels that exclusion and appends an *AI Docs* nav entry for local reading. `docs/src/AI` is currently a **symlink to `docs/src/AI/`** — note `core.symlinks=false` here, so it will not survive a fresh checkout, and relative links from the AI tree out to `docs/src/` don't resolve in the browser; the recommendation to move `docs/src/AI/` into `docs/src/AI/` is `CS-051`. **Rule while the split exists: AI docs may link to user docs, but user docs must NEVER link into `AI/`** (it's excluded from the public build → broken link). Two pages there are worth knowing about when working on model structure or persistence: `docs/src/AI/Scratch/intro-model-structure.md` (the model taxonomy — topology vs geometry, the STEP **graph** model, **BOM-vs-motion structuring** = the core problem, the Part/Assembly/Component/Body vocabulary, definition-vs-instance, identity, robot/CNC standards, workflow flags) and `docs/src/AI/Scratch/legacy-cellsmith-model-format.md` (the as-built cache format). `docs/src/Misc/` is a temporary placeholder. Format capability matrix: `docs/src/AI/Specs/model_formats.md` (INACTIVE / WIP). **`docs/src/AI/Scratch/ai-metaanalysis.md`** analyzes how AI/Claude is used in this repo and recommends workflow improvements — read it before restructuring the doc system.
