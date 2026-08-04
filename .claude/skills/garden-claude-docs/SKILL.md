---
name: garden-claude-docs
description: Tidy the CellSmith documentation system under docs/src/AI (and the CLAUDE.md hub) — condense the status ledger, distill dev-narrative out of reference docs, fold superseded/"Redesign update" notes into the prose, refresh stale tier-3 abstracts, re-fold over-fragmented or redundant reference docs, verify cross-references resolve, and bump the last-gardened stamp. Use when the user asks to garden/tidy the docs, or when the status ledger or a reference doc has grown bloated with changelog narrative.
---

# Garden the CellSmith docs

The docs live in a three-tier system: the lean **hub** (`CLAUDE.md`), the **Reference/spec** library under `docs/src/AI/`, and the **status ledger** (`docs/src/AI/status.md`). Over time abstracts drift, the ledger's Done log bloats, reference docs accumulate changelog narrative, and files outgrow their scope. This skill runs the maintenance pass. It is **read-heavy and curation-minded** — condense and reconcile, but propose (don't silently make) big structural merges/splits.

## Conventions to honor
Read `docs/src/AI/index.md` first — it defines the genres, the three-tier index, and the maintenance rules (especially "load-bearing *why* stays inline; archaeology goes to `status.md` + git"). Everything below serves those rules.

## ⭐ Scope — what gardening MAY and MAY NOT touch

The docs now live inside the mkdocs tree (`docs/src/AI/`), next to user documentation that has a different audience and a different owner. Gardening is **not** licensed to edit everything it can reach.

| Target | Gardening may… | Why |
|---|---|---|
| `docs/src/AI/status.md` | **edit freely** — condense the ledger, merge duplicates, bump the stamp | it is the archaeology sink; keeping it readable is the whole point |
| `docs/src/AI/Reference/*.md` | **edit freely** — distill dev-narrative out, refresh abstracts, re-fold | these mirror code; nobody's authorial voice is at stake |
| `docs/src/AI/index.md` | **edit** — keep the index matching the folder | it is a generated-by-hand map |
| `CLAUDE.md` | **edit** — check leanness, fix the tier-1 map | it is a hub; drift is the failure mode |
| `docs/src/AI/Specs/*.md` | **light touch only** — refresh the tier-3 abstract, fix broken cross-refs, fix formatting | a spec is **design intent**, authored deliberately. Do **not** rewrite, re-scope, or "improve" the design. Propose, don't apply |
| **`docs/src/AI/Scratch/**`** | **DO NOT EDIT — report only** | exploration is someone's in-progress thinking. Condensing it destroys the very half-formed material it exists to hold. You may *observe* ("this page is 4,700 lines; §11 looks ready to graduate") and record that in `status.md` |
| `docs/src/AI/Research/index.md` | **edit** — keep the series register and the file table current | it is an index, same as the tree index above |
| **`docs/src/AI/Research/Reports/**`** | **NEVER EDIT — these are immutable by design** | a report is a dated record whose whole value is that it cannot be quietly reworded away from its own numbers. The **one** permitted edit is appending the §0.6 erratum pointer, and only the method may do that. Condensing one destroys the evidence it exists to hold |
| **`docs/src/AI/Research/developer-log.md`**, **`alignment-audit.md`** | **APPEND ONLY — never rewrite an entry** | append-only logs. Rewriting history here silently changes measured inputs. Also: **never author the *felt like* field** — subjective attribution is the user's, and generating it is the one way to make the field worthless |
| **`docs/src/` outside `AI/`** (user docs) | **DO NOT EDIT** | different audience, different genre (Diátaxis), not this skill's job. See below |

**If in doubt, report instead of edit.** A gardening pass that silently rewrites a spec or a scratch page is worse than one that changes nothing.

### Why there is no separate user-docs gardening skill (yet)
The user docs are currently a stub (`docs/src/Misc/index.md` plus placeholders). A skill for maintaining content that does not exist would be speculative. **Revisit when the user docs have real tutorials/how-tos/reference pages** — at that point they need their own skill, because their maintenance rules are Diátaxis-shaped (is this page still one quadrant? is the tutorial still accurate?) and have nothing to do with tracking `src/`.

### The one cross-tree rule gardening MUST enforce
**AI docs may link out to user docs; user docs must NEVER link into `AI/`** — `AI/` is excluded from the public build (`mkdocs.yml`), so an inbound link is a broken link on the published site. Check it (and beware two false-positive traps):

```bash
# inbound links from user docs into AI/ -- should print nothing.
# --exclude-dir=AI skips the AI tree; the grep -v drops matches inside inline
# code spans, where the pattern is being *documented* rather than used.
grep -rn '](\([^)]*/\)\?AI/' docs/src --include='*.md' --exclude-dir=AI | grep -v '`'
```

Also verify the reverse direction still resolves: links from `AI/**` to `../../Misc/...` must point at files that exist, since a moved user page breaks them silently.

## Checklist

1. **Orient.** Read `docs/src/AI/index.md` and the top of `docs/src/AI/status.md` (note the `last gardened:` stamp and how long it's been).

2. **Condense the ledger — curate, don't discard** (`status.md`). "Prune" here means *condense and clarify*, NOT delete: summarize long-settled/completed rounds into concise entries, merge duplicates, and drop ONLY items that are genuinely obsolete or superseded. **Always preserve the load-bearing *why* and the fact that the work happened** — never blindly delete history. Make sure every open/backlog item still reflects reality (state/owner correct).

3. **Distill dev-narrative OUT of the reference docs.** A `Reference/*.md` should read as *current-state + load-bearing why* — not a changelog. Move accumulated dev-narrative — "Round N (items …)", "verified: `scratchpad/X` (N checks)", session-by-session play-by-play, `(NEW; … live-test PENDING)` status tags — OUT into `status.md` history (or drop if obsolete), **keeping the rule/behavior and its load-bearing reason inline.** Quick way to spot the worst offenders: `grep -cE 'Round [0-9]+|verified|live-test PENDING|\(NEW' docs/src/AI/Reference/*.md` — the high counts (historically `geometry-edits.md`, `selection-and-cgb.md`, `occ-vtk-gotchas.md`) are the targets.

4. **Reconcile superseded prose + "Redesign update" notes.** Where a doc carries a correction banner over stale text (e.g. a `> **Redesign update …**` note), **fold the correction into the body and delete the now-superseded prose** — don't leave both standing indefinitely. Similarly resolve any "predates X" / "supersedes below" notes by actually updating the below.

5. **Refresh tier-3 abstracts.** For each file in `Reference/` and `Specs/`, check the top abstract still matches the file's current content and scope; update where the body has grown or shifted. Spot-check a few claims against `src/`.

6. **Re-fold structure.** If a reference file has outgrown its scope, propose splitting it (and update the README index + the `CLAUDE.md` tier-1 map). If two files overlap, propose merging. Don't fragment for its own sake — a coherent stretch belongs in one file.

7. **Verify cross-references.** Grep the docs for links to sibling files (`grep -rn '\.md' docs/src/AI`) and confirm each target exists. Confirm the hub's tier-1 map lists exactly the files in `Reference/`, that `README.md`'s index matches the folder, and that no doc (or `src/` comment) points at a moved/deleted file or a stale section name.

8. **Check the hub stayed lean.** `wc -l CLAUDE.md` — a few hundred lines at most. If guardrail/reference content has crept back in, move it to the right `Reference/` file and leave a map entry.

9. **Bump the stamp.** Update `last gardened:` in `status.md` to today's date (ask the user for the date if you can't determine it — do not fabricate it).

10. **Report** what changed, and what you propose but didn't do (structural merges/splits), for the user to approve.

## Guardrails
- **Condense, never blindly discard** — history is curated into shorter form, and load-bearing rationale always survives.
- Do not move content out of `CLAUDE.md`'s hard-guardrail sections (B-rep priority, constraints) — those belong in the always-loaded hub.
- Do not invent dates for the stamp.
- Structural merges/splits change the map — always update `README.md` + the hub map in the same pass.
