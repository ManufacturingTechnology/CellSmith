---
name: garden-claude-docs
description: Tidy the CellSmith documentation system under docs/src/AI (and the CLAUDE.md hub) — condense the status ledger, distill dev-narrative out of reference docs, fold superseded/"Redesign update" notes into the prose, refresh stale tier-3 abstracts, re-fold over-fragmented or redundant reference docs, verify cross-references resolve, and bump the last-gardened stamp. Use when asked to garden/tidy the docs, or when the status ledger or a reference doc has grown bloated with changelog narrative.
---

# Garden the CellSmith docs

The docs live in a three-tier system: the lean **hub** (`CLAUDE.md`), the **Reference/spec** library under `docs/src/AI/`, and the **status ledger** (`docs/src/AI/status.md`). Over time abstracts drift, the ledger's Done log bloats, reference docs accumulate changelog narrative, and files outgrow their scope. This skill runs the maintenance pass. It is **read-heavy and curation-minded** — condense and reconcile, and propose big structural merges/splits for the user to approve.

## Conventions to honor
Read `docs/src/AI/index.md` first — it defines the genres, the three-tier index, and the maintenance rules (especially "load-bearing *why* stays inline; archaeology goes to `status.md` + git"). Everything below serves those rules.

## ⭐ Scope — what gardening edits, and what it only reports

The docs now live inside the mkdocs tree (`docs/src/AI/`), next to user documentation that has a different audience and a different owner. Gardening edits the files listed as **Edit** below and reports on the rest.

| Target | Gardening… | Why |
|---|---|---|
| `docs/src/AI/status.md` | **Edit** — condense the ledger, merge duplicates, bump the stamp | it is the archaeology sink; keeping it readable is the whole point |
| `docs/src/AI/Reference/*.md` | **Edit** — distill dev-narrative out, refresh abstracts, re-fold | these mirror code; nobody's authorial voice is at stake |
| `docs/src/AI/index.md` | **Edit** — keep the index matching the folder | it is a generated-by-hand map |
| `CLAUDE.md` | **Edit** — check leanness, fix the tier-1 map | it is a hub; drift is the failure mode |
| `docs/src/AI/Specs/*.md` | **Light touch** — refresh the tier-3 abstract, fix broken cross-refs, fix formatting | a spec is **design intent**, authored deliberately: keep its design as written and propose design changes for the user to apply |
| **`docs/src/AI/Scratch/**`, `docs/src/AI/Research/**`** (local only, gitignored) | **Report only** — observe ("this page is 4,700 lines; §11 looks ready to graduate") and record findings in `status.md`; leave the files as they are | in-progress thinking and dated research records; their value depends on staying as written |
| **`docs/src/` outside `AI/`** (user docs) | **Leave unchanged** — outside this skill's scope | different audience, different genre (Diátaxis). See below |

**If in doubt, report instead of edit.** A gardening pass that silently rewrites a spec or a scratch page is worse than one that changes nothing.

### Why there is no separate user-docs gardening skill (yet)
The user docs are currently a stub (`docs/src/Misc/index.md` plus placeholders). A skill for maintaining content that does not exist would be speculative. **Revisit when the user docs have real tutorials/how-tos/reference pages** — at that point they need their own skill, because their maintenance rules are Diátaxis-shaped (is this page still one quadrant? is the tutorial still accurate?) and have nothing to do with tracking `src/`.

### The one cross-tree rule gardening MUST enforce
**Link from AI docs out to user docs, and keep user-doc links pointing at user docs** — `AI/` is excluded from the public build (`mkdocs.yml`), so an inbound link is a broken link on the published site. Check it (and beware two false-positive traps):

```bash
# inbound links from user docs into AI/ -- should print nothing.
# --exclude-dir=AI skips the AI tree; the grep -v drops matches inside inline
# code spans, where the pattern is being *documented* rather than used.
grep -rn '](\([^)]*/\)\?AI/' docs/src --include='*.md' --exclude-dir=AI | grep -v '`'
```

Also verify the reverse direction still resolves: links from `AI/**` to `../../Misc/...` must point at files that exist, since a moved user page breaks them silently.

## Checklist

1. **Orient.** Read `docs/src/AI/index.md` and the top of `docs/src/AI/status.md` (note the `last gardened:` stamp and how long it's been).

2. **Condense the ledger, keeping its history** (`status.md`). "Prune" here means *condense and clarify*: summarize long-settled/completed rounds into concise entries, merge duplicates, and remove only items that are genuinely obsolete or superseded. **Keep the load-bearing *why* and the fact that the work happened.** Make sure every open/backlog item still reflects reality (state/owner correct).

3. **Distill dev-narrative OUT of the reference docs.** A `Reference/*.md` should read as *current-state + load-bearing why* — not a changelog. Move accumulated dev-narrative — "Round N (items …)", "verified: `scratchpad/X` (N checks)", session-by-session play-by-play, `(NEW; … live-test PENDING)` status tags — OUT into `status.md` history (or drop if obsolete), **keeping the rule/behavior and its load-bearing reason inline.** Quick way to spot the worst offenders: `grep -cE 'Round [0-9]+|verified|live-test PENDING|\(NEW' docs/src/AI/Reference/*.md` — the high counts (historically `geometry-edits.md`, `selection-and-cgb.md`, `occ-vtk-gotchas.md`) are the targets.

4. **Reconcile superseded prose + "Redesign update" notes.** Where a doc carries a correction banner over stale text (e.g. a `> **Redesign update …**` note), **fold the correction into the body and delete the now-superseded prose** — don't leave both standing indefinitely. Similarly resolve any "predates X" / "supersedes below" notes by actually updating the below.

5. **Rewrite recorded guidance as instructions.** Look for the user's words stored in docs (quoted or not: first-person sentences, attributions such as `the user said / asked / felt`) and for prohibition-only rules in instruction files (`CLAUDE.md`, skills, `invariants.md`). Rewrite each per `CLAUDE.md` → *Recording guidance*: the behavior to perform, its situation and its reason. When the desired behavior is unclear, list it for the user as an open question.

6. **Refresh tier-3 abstracts.** For each file in `Reference/` and `Specs/`, check the top abstract still matches the file's current content and scope; update where the body has grown or shifted. Spot-check a few claims against `src/`.

7. **Re-fold structure.** If a reference file has outgrown its scope, propose splitting it (and update the README index + the `CLAUDE.md` tier-1 map). If two files overlap, propose merging. Keep a coherent stretch in one file.

8. **Verify cross-references.** Grep the docs for links to sibling files (`grep -rn '\.md' docs/src/AI`) and confirm each target exists. Confirm the hub's tier-1 map lists exactly the files in `Reference/`, that `README.md`'s index matches the folder, and that no doc (or `src/` comment) points at a moved/deleted file or a stale section name.

9. **Check the hub stayed lean.** `wc -l CLAUDE.md` — a few hundred lines at most. If guardrail/reference content has crept back in, move it to the right `Reference/` file and leave a map entry.

10. **Bump the stamp.** Update `last gardened:` in `status.md` to today's date (ask the user for the date when you can't determine it).

11. **Report** what changed, and what you propose but didn't do (structural merges/splits), for the user to approve.

## Guardrails
- **Condense, keeping the history** — history is curated into shorter form, and load-bearing rationale always survives.
- Keep `CLAUDE.md`'s hard-guardrail sections (B-rep priority, constraints) in the hub; they belong in the always-loaded file.
- Structural merges/splits change the map — always update `README.md` + the hub map in the same pass.
