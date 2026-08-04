---
title: 'AI Docs'
audience: both
---

# AI Docs

Internal, agent-facing documentation for CellSmith. This tree used to live at
`.claude/docs/`; it now sits inside the mkdocs source tree so it renders in a browser and
so links between it and the user docs actually resolve. `CLAUDE.md` is a lean **hub**
(guardrails + how-to-run + conventions + a one-line map); the depth lives here, read on
demand.

!!! warning "Not published to end users"

    The default build (`make`, via `mkdocs.yml`) **excludes `AI/`**. Only `make dev` (via
    `mkdocs.dev.yml`) includes it, appending an *AI Docs* nav entry. That polarity is
    deliberate — publishing internal docs should require asking for it.

    **One-way links only.** Pages under `AI/` may link out to the user docs; **user docs
    must never link into `AI/`**, or the public build emits a broken link.

## Layout

| Path | Genre | Cadence |
|---|---|---|
| `CLAUDE.md` (repo root) | **Hub** — guardrails, environment, conventions, the doc map | slow; auto-loaded every session |
| `AI/Reference/` | **Reference (as-built)** — how it works *now* + load-bearing *why* | tracks code |
| `AI/Specs/` | **Spec (design intent)** — what it *should* be / the contract | slow; may lead code |
| `AI/status.md` | **Ledger** — what's built, what's open, `CS-###` ids | constant |
| `AI/Scratch/` | **Exploration** — thinking in progress, pre-structure | churns; graduates out |
| `AI/Research/` | **Research** — dated AI self-analysis reports (`Reports/`, immutable) + their two append-only input logs | per iteration, on demand |
| `~/.claude/plans/` | **Plan** — transient build steps | throwaway |

Cross-cutting reference docs are single-authority: `Reference/invariants.md` (rules you
must not break), `Reference/decisions.md` (ADR log — *check before reversing a deliberate
design*), `Reference/glossary.md` (overloaded terms).

!!! info "Two files are called `CLAUDE.md` — they are different things"

    `~/.claude/CLAUDE.md` is **personal**, applies to every project the user opens, and is
    about *how to communicate* (response formatting, citation expectations). The repo
    `CLAUDE.md` is **project** scope, travels via **git**, and is about *how to work on
    CellSmith*. Test for the repo file: *"would a new contributor need this to avoid
    breaking something?"* Test against it: *"would I want this on an unrelated Rust
    project?"* → then it belongs in the personal file.

## Who each page is written for

Not every page here is meant for human eyes, and that changes how it should be written.

| Audience | Which pages | How to format |
|---|---|---|
| **`agent`** | `Reference/*.md` (except `decisions.md`, `glossary.md`) | Optimize for the reader that actually reads it: dense, terse, heavy on tables and exact identifiers. Rendering niceties aren't worth the tokens. |
| **`both`** | this page, `status.md`, `Specs/*.md`, `Scratch/*.md`, `Research/*.md`, `Reference/decisions.md`, `Reference/glossary.md` | Follow mkdocs-material conventions: `title` in frontmatter, admonitions, fenced code with a language, tables that fit the page, mermaid where a diagram helps. |

Declare it in frontmatter so the intent is explicit rather than inferred:

```yaml
---
title: 'Pipeline and Caching'
audience: agent
---
```

**Default to `agent` in `Reference/`, `both` everywhere else.** Note what this is *not*: an
`agent` page still has to be accurate, current, and skimmable — it just doesn't have to be
pretty.

!!! note "Diátaxis applies to the USER docs, not to this tree"

    [Diátaxis](https://diataxis.fr/) (tutorial / how-to / reference / explanation) is the
    organizing principle for `docs/src/` **user** documentation. Here it is at most a
    **loose influence** and must not drive structure — because this tree's real organizing
    axis is *relationship to the code* (lags it, leads it, tracks open work), which is not
    a Diátaxis axis at all. Two quadrants also don't apply: there is no agent **tutorial**
    (agents don't onboard), and `status.md` is a **ledger**, for which Diátaxis has no
    quadrant — forcing one is how ledgers rot into changelog prose.

    The one genuinely useful borrowing: **`.claude/skills/*/SKILL.md` are how-to guides** —
    write them as procedures with a goal, not as essays.

## Conventions (maintenance rules)

- **Three-tier index.** Tier-1 = the one-line map in `CLAUDE.md` (always loaded). Tier-2 =
  this page. Tier-3 = a 2–4 sentence **abstract at the top of every `Reference/` + `Specs/`
  file**. Tier-1/2 are purpose-level and rarely change; only tier-3 tracks content.
- **Update your abstract on edit.** Changed a file's content → update its abstract. Added,
  removed, or re-scoped a file → update this page's index **and** the `CLAUDE.md` map.
- **Folder names are navigation labels.** Directories under `docs/src/` appear **verbatim**
  in the mkdocs nav, so they are **capitalized**: `Reference/`, `Specs/`, `Scratch/`,
  `Research/`, `Reports/`. A lower-case folder renders as a lower-case nav entry.
- **Reference by concept-anchor, not line number** — files get split and re-folded.
- **Load-bearing "why" stays inline.** Pure archaeology (chronology, superseded approaches,
  verification counts) goes to `status.md` + git.
- **Staleness hygiene.** Each abstract notes "verify against `src/`; may lag." Stamp
  volatile sections with `@<commit>` when it matters.
- **Plan graduation.** Scratch plans stay in `~/.claude/plans/`; one that becomes canonical
  graduates into `Specs/`.
- **Decisions.** Before reversing a deliberate design, read `Reference/decisions.md`; if
  your change conflicts, surface the conflict + its "Revisit if" condition rather than
  silently overriding or complying. If a decision's confidence isn't stated, ask.
- **Living documentation.** These docs mirror the code. After any non-trivial `src/` change,
  update the matching `Reference/*.md` (and `status.md` for state/decisions) in the **same
  turn**, so the session stays **compaction-safe**.
- **Knowledge flush (partly enforced, mostly your job).** `status.md` records *decisions*;
  `Reference/*.md` only mirrors *code*, so a design-only session can settle a dozen things
  that never leave the transcript. The **`flush` skill** writes them down. Run it **before
  ending or closing a session**, before `/compact`, and after any dense stretch — a
  transcript is lost either way it ends. Three hooks in `.claude/settings.json` help, but
  note what they cover: the gate guards the **compaction** path only, and **nothing guards a
  session simply being closed**:
    - `SessionStart` stamps `.claude/.session-flush-marker`.
    - `PreCompact` → `.claude/hooks/precompact-gate.sh` **blocks a manual `/compact`** when
      no doc is newer than that stamp, and **only warns on an automatic compaction**
      (blocking auto-compact could wedge an out-of-context session). One-shot bypass:
      `touch .claude/.skip-flush-gate`.
    - `Stop` warns when a `src/` file is newer than every doc.
- **Tests.** `make test` runs everything; `make test-ci` runs only what works in a Linux
  container. Polarity: a test is **CI-eligible by default** and must opt out with
  `@pytest.mark.local_only`, so a forgotten marker fails loudly in CI rather than silently
  never running.
- **Gardening.** Periodically prune/re-fold (see the `last gardened:` stamp atop
  `status.md`; the `garden-claude-docs` skill runs the checklist — condense, don't discard).

## Index

**`Reference/`** (as-built):

- `architecture.md` — the three-layer stack, layer decoupling, pure mesh/edge layer, deps.
- `occ-vtk-gotchas.md` — pythonocc/OCCT + VTK hard-won rules; the no-BLAS-matmul ban.
- `pipeline-and-caching.md` — the Source→Main two-stage pipeline, bake order/stamps, cache layout.
- `scene-config-and-orientation.md` — the v3 config schema + `ModelConfigStore`, color resolution, orientation math.
- `viewport-interaction.md` — the 3D viewport: mouse/picking, depth-peeling, viewcube, settings strip, Measure.
- `selection-and-cgb.md` — the Selection Filter + Construction Geometry Builder.
- `node-state-and-color.md` — hidden/suppressed/color-override state, the color picker, Recolor, tree glyphs.
- `geometry-edits.md` — Edit Bodies (Component Editor), Custom Origins/Set Origin, Component Transform + bake engine.
- `restructure-and-transform-source.md` — tree restructure (Feature A) + the Transform Source editor.
- `asset-splitting-and-compose.md` — asset splitting (Feature B), the Model Tree, composed export.
- `kinematic-joints.md` — prismatic/revolute/fixed joints → USD.
- `export.md` — STEP/USD/OBJ subtree export.
- `mesh-import.md` — the additive OBJ/STL/USD mesh-import path.
- `packaging.md` — the PyInstaller onedir build, Inno installer, Debian package, and the
  GitHub Actions CI + release workflows.
- `licensing.md` — Apache-2.0 outbound vs. the third-party payload: the measured license
  inventory of what the build actually bundles, why LGPL deps don't block Apache-2.0, the
  six unmet obligations in the frozen build, and the ordered remediation list.
- `decisions.md` · `invariants.md` · `glossary.md` — the cross-cutting docs above.

**`Specs/`** (design intent):

- `construction_geometry_builder_definitions.md` — the SF/CGB design spec.
- `model_formats.md` — format inventory + capability matrix. **Marked INACTIVE / WIP**; its
  genre and filename are still undecided.

**`Scratch/`** (exploration — will graduate; do **not** treat as settled):

- `intro-model-structure.md` — the model taxonomy. Topology vs geometry; the STEP **graph
  model**; **CAD structures by BOM/reuse, not by motion** — the core problem the tool
  solves; the **Part / Assembly / Component / Body vocabulary**; definition-vs-instance;
  identity; robot/CNC standards incl. MTConnect; units; kinematics. **Read this for model
  vocabulary before writing about structure elsewhere.**
- `legacy-cellsmith-model-format.md` — the as-built on-disk cache format, with a measured
  container/compression comparison and the items marked for a successor design.
- `testb2-folder-frame-recovery.md` — ⚠️ **TRANSIENT + IRREPLACEABLE.** The **only copy**
  of three restructure-folder `origin`/`transform` values that `CS-131` nulled in
  `test_files/testB2.cellsmith.json` on 2026-08-03 (they are gone from both the config and
  the bake stamp; these three were rescued from a session transcript). Includes the apply
  procedure and which folders must be re-authored instead. **Delete once the frames are
  restored or re-authored.** → `CS-131`, `CS-135`, ADR-0008.
- `ai-history.md` — the AI-use **case study**: a dated timeline reconstructed from git (three eras, the instruction-density finding), telemetry analysis with real charts, and the **goal reframe** (process metrics vs outcome metrics).
- `ai-self-analysis-research-method.md` — **SPEC for the `ai-retrospective` skill**: the metric taxonomy (outcome / drag indicator / capability), the research questions, the report template, and the iteration mechanics that let successive reports evaluate each other's predictions. **Read before building any AI-workflow measurement.**
- `ai-metaanalysis.md` — **how Claude/AI is used in this repo**: the doc surfaces, the
  verification-loop design (three test tiers, golden-image vs vision review, test-fixture
  generation), and the exploration workflow. **Read before restructuring `CLAUDE.md`,
  `AI/`, or `docs/`.**

**`Scratch/Pipeline/`** (exploration — a nested sub-study):

- `index.md` · `01-input-definition.md` — the input/pipeline definition work in progress.

**`Research/`** (AI self-analysis — the folder boundary is the immutability boundary):

- `index.md` — the **series register**: one row per study, mapping a generating skill to every
  report it produced. Cite reports by **Report ID** (`AIRETRO-003`), never by filename.
- `Reports/` — **immutable**, one report per iteration. Each is self-contained: its metrics are
  embedded as Appendix E and the method that produced it verbatim as Appendix D.
- `developer-log.md` — **append-only** tier-5 input: intervention count + type with verbatim
  trigger quotes, plus capability entries. **The only input that cannot be reconstructed
  retroactively**, which is why it exists at all. Agent drafts, **user** authors *felt like*.
- `alignment-audit.md` — **append-only** tier-6 input: the repo scored against published
  best practices, one dated section per audit.

**`status.md`** — the merged status + open-todo + future-work ledger (`CS-###`).
