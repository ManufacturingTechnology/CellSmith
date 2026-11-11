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
SUBORDINATE — a far-behind bonus**. Keep the STEP path's **speed, simplicity and output exactly as they
are** (hard limit). Architecturally this is enforced by keeping the
XCAF/OCC code paths untouched and default, adding mesh support as an early-
branching PARALLEL path, and gating via capabilities that are a **no-op (full
capability) for STEP** so STEP behavior stays byte-for-byte unchanged. When in
doubt, protect the STEP workflow. See `docs/src/AI/Reference/mesh-import.md` (the mesh path is now BUILT).


### Current focus — Selection Filter + Construction Geometry Builder
The SF/CGB redesign is **fully implemented** (headless/offscreen-verified; GL live-test pending). As-built: `docs/src/AI/Reference/selection-and-cgb.md`. Design spec: `docs/src/AI/Specs/construction_geometry_builder_definitions.md`.

### Context / constraints (work within these)
- CAD package is **SolidWorks Design Standard**. Cannot switch packages,
  cannot assume premium add-ins. URDF export from SolidWorks is off the table
  (models are imported STEP dumb-solids with no mates/feature tree).
- Robots are **downloaded STEP models**, not clean vendor robot models. They
  may have good component names or may be "Solid1, Solid2…". Handle both.
- Six robots + a static manufacturing cell. Robots need rigging; cell does not.
- Real files are **large**: test1 ≈ 875 MB / ~20k components / 112k colors;
  test2 ≈ 637 MB / ~2k components. Design for thousands–tens-of-thousands of
  parts. Test files live in `test_files/` (gitignored).
- **Digital shadow, not simulation**: we pose joints from telemetry. Author geometry,
  hierarchy and joints; add collision, mass, inertia or dynamics only when asked.
- **Author plain referenced USDs** for the robot rigging output (hard limit: no instancing there).
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
  corrupt the env. Let first-time setup finish before starting another `dev`/`run`.
- VS Code: `.vscode/` hardcodes **no interpreter path** (works on Windows + Linux). Launch configs and the
  screenshot tasks use the workspace's selected interpreter — run *Python: Select Interpreter →
  CellSmithEnv* once per machine. Test tasks run `test.bat` on Windows, `make test`/`test-ci` on Linux.
- **Headless runs when `conda` isn't on `PATH`** (common here): `& "$env:LOCALAPPDATA\anaconda3\Scripts\conda.exe" run -n CellSmithEnv python …` (PowerShell); env at `%LOCALAPPDATA%\anaconda3\envs\CellSmithEnv`. Full guidance in `docs/src/AI/Reference/invariants.md`.


### ⭐ Recording guidance, and keeping personal data out (ADR-0011)
Files in this repo hold **instructions that help the next agent do the right thing**, not a record of
conversations. Treat the repo as public: it has been public, its successor will be, and git history keeps whatever was
committed. Every tracked file counts: code, comments, docs, `status.md`, configs,
test data, quoted tool output.

**Recording guidance**
1. Write each piece of guidance as an instruction in your own words: *when [situation], do [behavior], because
   [reason]*, specific enough to act on and to check. Store the instruction, never the wording that prompted it.
2. Describe the behavior to perform. Keep prohibitions for hard limits, each paired with what to do instead.
3. When guidance names a problem rather than a behavior, ask follow-up questions until you can state the
   behavior that would satisfy it, and record that. If you can't ask, record your best reading marked
   unconfirmed (❓) and raise it as an open question.
4. File it where it applies: project rules here or in the subsystem's `Reference/` doc; decisions in
   `decisions.md` with the reason and date; bugs in `status.md` as symptom + reproduction; personal working
   preferences in your private memory, outside the repo.
5. Record the rule, not the story. "User decision, YYYY-MM-DD" is enough provenance.

**What goes in a tracked file**
- **Paths:** repo-relative, computed from `__file__`, environment variables (`%WINDIR%`, `%LOCALAPPDATA%`,
  `$HOME`), or placeholders (`<isaac-sim-install>`). Standard POSIX packaging paths (`/usr/…`, `/opt/…`,
  `/etc/…`) are fine.
- **People:** roles ("a collaborator", "the fork owner"); for maintainer/author fields, AMT's role address
  `technology@amtonline.org`.
- **Models and data:** generic names (`testB2`); ask before naming a real customer's model.
- **Quoted data:** UI labels, error messages, standards, licenses, and tool output with personal paths redacted.
- **Machines:** placeholders (`<host>`) for hostnames and internal IP addresses.
- **Credentials:** read from the environment or GitHub secrets; test values obviously fake. When checking a
  secret, report whether it is set and its length, never its value.

**Hard limits** (the content check blocks them): absolute machine paths, personal names, usernames, handles or
email addresses, this machine's username, hostname and git identity, and secrets (token formats, private keys,
passwords in URLs, literals assigned to secret-named keys; masked in its report). A secret that reaches a tracked
file must be rotated, not only deleted: tell the user.

**Where personal material goes:** gitignored places only: `scratchpad/`, `.claude/*.local.json`,
`.claude/confidential-terms.txt` (names no pattern can know), `test_files/`, `docs/src/AI/Scratch/`,
`docs/src/AI/Research/`.

**Before committing:** read `git status` (untracked files too) and `git diff --cached`, stage files
deliberately, and commit with the GitHub no-reply identity (`git config user.email`).

**How it's enforced:** `.github/scripts/check-content.py` (which also flags guidance attributed to a person or
quoted in the first person in `CLAUDE.md`, `contributing.md`, `docs/src/` and the skills) runs as a PreToolUse hook that blocks a Write/Edit
adding a match to a tracked file, as `tests/test_content_check.py` in CI, via `make content-check`, and as the
pre-commit hook (`git config core.hooksPath .githooks`). Shell-command writes reach only the test and the
pre-commit hook, and the hook lets a write through if the checker itself crashes. Recorded guidance, other
people's names and customer names are judgment calls, so check those yourself. When a finding looks like a
false positive, ask, and keep the rule as written until the user decides.

### Coding conventions / preferences
- Python 3.12 (env is pinned there). Type hints. Small, testable functions.
- Keep OCC, VTK/PyVista, and USD imports isolated to their layers.
- One source of truth for component IDs across parsing → GUI → export.
- Fail loud on ambiguous STEP structure; log unnamed/merged/colorless components.
- Author collision/mass/inertia only when asked (digital shadow scope).
- **Finishing a fix:** run the full test suite (`make test` / `test.bat`) and the checks for neighboring
  features before reporting the fix done; when a fix touches shared code, list the features it affects.
- Verify OCC behaviors headlessly (small scripts) before wiring into the GUI —
  interactive GL behavior still needs the user. **But offscreen rendering DOES work
  here** — see the note below before assuming you can't see your own output.

### When something doesn't work — diagnose before reporting
**"X doesn't work" is a symptom, not a finding.** Work the **`diagnose` skill** (it should fire automatically; invoke it if it doesn't) and report what it produced. Treat a first error message as a symptom: a missing library, a wrong flag, and an unsupported feature look identical at that distance, so isolate the failing layer before concluding anything. **Show evidence, not assertions**: the command run and what it returned; mark unverified claims ❓. **Prefer a sandbox** for anything exploratory (scratch script, throwaway container, temp dir, WSL) — a probe that cannot damage anything needs no caution, and being wrong there costs nothing.

**⭐ RED LIST — ask before taking an option on this list, even one you found yourself.** Proceed alone on reversible, in-scope, technical choices. **Stop and ask** when the change would:
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

### Known hard problem (flag it; the user decides)
Grouping components into links is **human judgment** — the tool assists, it does
not automate the semantics. If a STEP file has **fused/merged bodies** (a link is
not a separable solid), fusion destroyed the **seam information**, so no code can
*infer* where to split — **leave splitting to the user** (hard limit: no automatic split); detect and warn when a component spans
what should be multiple links. The user then separates it **manually with the Edit
Bodies Split tool** (a core CellSmith feature — it exists precisely so this doesn't
require a CAD license). Recovering the *original* boundary is impossible; producing
a usable separation is normal workflow.


### Dependencies
All free / open source; full list in `docs/src/AI/Reference/architecture.md`. Core: `pythonocc-core` (novtk), `PySide6`, `pyvista`/`pyvistaqt`, `numpy`, `pydantic`, `usd-core` (`pxr`, export only), `trimesh` + `scipy`/`shapely`/`mapbox_earcut` (mesh import).

### When helping on this repo
- If a robot is a real commercial arm (UR, KUKA, Fanuc, ABB…), existing URDFs / Isaac assets may make custom rigging unnecessary — ask early.
- Before rigging, check whether STEP bodies are **separated** (not fused). No code can *infer* a lost seam, so leave the split to the user, who does it manually via Edit Bodies (that's the point of the Split tool); fused geometry is a workflow step, not a blocker.
- **You CAN see your own rendering — offscreen works** (probe-verified 2026-07-30, correcting a long-standing claim here that it doesn't). With `QT_QPA_PLATFORM=offscreen`: `QApplication` constructs, `pyvista.Plotter(off_screen=True).screenshot()` produces a correctly shaded/occluded image, and `QWidget.grab()` captures widgets. **One gotcha:** the offscreen platform has **zero font families**, so captured text is tofu boxes — fix with `QtGui.QFontDatabase.addApplicationFont(os.path.join(os.environ["WINDIR"], "Fonts", "segoeui.ttf"))` in the harness. Write PNGs and **read them back** to check your work. ❓ Unconfirmed whether this used hardware or software GL (`PySide6/opengl32sw.dll` is present); **interactive** behavior (camera feel, depth peeling, hover) still needs the user. Details + the three test tiers: `docs/src/AI/Scratch/ai-metaanalysis.md` §3.1.
- Verify OCC/config logic with small scripts (`conda run --no-capture-output -n CellSmithEnv`; **`--no-capture-output` is REQUIRED** — without it conda re-encodes captured stdout to cp1252 under Git Bash, crashes on any non-ASCII test output, and then HANGS on its crash-report prompt. See `docs/src/AI/Reference/invariants.md`). Test files (gitignored): `test_files/test1.step` (875 MB / ~20k parts, needs color recovery), `test2.step` (637 MB / ~2k, native colors).
- **Cite your sources.** When a claim comes from outside this repo — a standard, a vendor doc, a library's behavior, a spec — **include the source as a markdown link in the doc you write**, not just in chat. Prefer primary sources (ISO/standards bodies, official library docs, the vendor's own spec) over blog posts. When a claim is *unverified*, mark it **❓** rather than stating it flatly. When a claim comes from a probe you ran, say so and say what you probed — that is a source too.
- Before reversing a deliberate design decision, check `docs/src/AI/Reference/decisions.md` — if your change conflicts with an entry, surface the conflict + its "Revisit if" condition rather than silently overriding or complying.

### Keeping docs current (living documentation)
Treat `CLAUDE.md` + `docs/src/AI/**` as a **living mirror of the code**, not write-once. **After any non-trivial `src/` change, update the matching `Reference/*.md` (and `status.md` for state/decisions) in the SAME turn**, before finishing. This keeps the docs a faithful snapshot so the session can be **compacted at any time without losing context** — the docs, not the chat history, are the durable memory. Record non-obvious learnings (a gotcha, a design decision, a new invariant) in the right doc as you go. Conventions: `docs/src/AI/index.md`.

### ⭐ Run the `flush` skill — what must survive the conversation ending
A conversation ends in one of two ways and **both lose the transcript**: the session closes, or the context is compacted into a lossy summary. So the rule is not "flush before compacting", it is **flush before the knowledge can be lost** — before ending or closing a session, before `/compact`, and after any dense stretch that settled things. Flush as soon as something is settled; a disconnect gives no warning.

Always on disk before that point: (1) the **uncommitted-file list** (this tree carries a large uncommitted build); (2) which **live-GL tests are still pending**; (3) the **active `CS-###` ids** under discussion and their decisions; (4) any **cache/bake state** established (which stages are fresh, what was rebuilt); (5) **open questions asked of the user that were not answered**. Everything else is recoverable from `docs/src/AI/`.

`Reference/*.md` mirrors *code*, so a docs-or-design-only session can settle a pile of decisions that never leave the chat — `status.md` is where those go. A `PreCompact` hook **blocks a manual `/compact`** until some doc has been written this session (auto-compact only warns); one-shot bypass is `touch .claude/.skip-flush-gate`. Note the gate only guards the *compaction* path — **nothing at all guards a session simply being closed**, which is why the skill's first trigger is you remembering. Details in `docs/src/AI/index.md` → Conventions.

## 📁 Documentation map
Detail lives in `docs/src/AI/`. Read the file whose topic matches your task. Landing page + doc-system conventions: `docs/src/AI/index.md`. Rules to uphold: `docs/src/AI/Reference/invariants.md`. Term definitions: `docs/src/AI/Reference/glossary.md`. Open work + status: `docs/src/AI/status.md`.

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

**User docs** live in `docs/` (mkdocs-material, built via `docs/makefile` from WSL, since its `venv/` is a WSL venv). `docs_dir` is `docs/src`. **Two builds:** `make` uses `mkdocs.yml` and **excludes `AI/`** (the public site); `make dev` uses `mkdocs.dev.yml`, which cancels that exclusion and appends an *AI Docs* nav entry for local reading. `docs/src/AI/` is a real directory (moved out of `.claude/docs/` and the symlink dropped by `CS-051`, done 2026-07-30). **Rule: link from AI docs out to user docs, and keep user-doc links pointing at user docs** (the public build excludes `AI/`, so a link into it breaks). Two pages there are worth knowing about when working on model structure or persistence: `docs/src/AI/Scratch/intro-model-structure.md` (the model taxonomy — topology vs geometry, the STEP **graph** model, **BOM-vs-motion structuring** = the core problem, the Part/Assembly/Component/Body vocabulary, definition-vs-instance, identity, robot/CNC standards, workflow flags) and `docs/src/AI/Scratch/legacy-cellsmith-model-format.md` (the as-built cache format). `docs/src/Misc/` is a temporary placeholder. Format capability matrix: `docs/src/AI/Specs/model_formats.md` (INACTIVE / WIP). **`docs/src/AI/Scratch/ai-metaanalysis.md`** analyzes how AI/Claude is used in this repo and recommends workflow improvements — read it before restructuring the doc system.
