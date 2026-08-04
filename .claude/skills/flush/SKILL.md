---
name: flush
description: Flush everything this session knows but has not written down into the durable docs on disk — sweep the conversation for decisions, corrections, open questions, blocked items and new invariants, record them in docs/src/AI/status.md as CS-### entries, sync any Reference/*.md that src/ changes invalidated, and verify the must-survive facts are on disk. Use BEFORE ENDING OR CLOSING A SESSION, before running /compact, when the PreCompact gate blocks a compaction, or any time the session has accumulated decisions that exist only in chat.
---

# Flush the session's knowledge to disk

**The premise:** the transcript is not durable memory. `docs/src/AI/` **is**.
Anything decided in conversation but never written down is *gone* the moment the
conversation ends — whether it ends because the session closed or because the
context was compacted into a lossy summary. This skill closes that gap.

## When to run it

**Any time knowledge would otherwise be lost with the conversation.** In rough
order of how often each comes up:

| Trigger | Why |
|---|---|
| **Before ending or closing a session** | The most common case and the easiest to forget. Nothing warns you; the window just closes. Run it as the last substantive act of any session that settled something. |
| **Before `/compact`** | A summary preserves *some* of the transcript, and reliably drops open questions and corrections. The `PreCompact` gate blocks a manual `/compact` until some doc has been written. |
| **When the `PreCompact` gate blocks you** | That is this skill being asked for by name. |
| **Mid-session, after a dense stretch** | A long design discussion, a diagnosis with several dead ends, or a pile of user decisions. Don't wait for a trigger event — the record is worth having immediately, and a crash or a disconnect is not a trigger you get to plan for. |

Running it more often than necessary costs a few minutes and a diff. Running it
too rarely costs knowledge that cannot be reconstructed. The asymmetry is the
whole argument.

## What it is *not* for

**Not** "the reference docs went stale" — the `Stop` hook already watches `src/`
mtimes for that. The failure mode this exists to prevent is the quieter one: **a
long conversation produces a pile of decisions, corrections, and open questions
that never leave the transcript.** Reference docs describe code; nothing describes
*decisions*. That's `status.md`'s job, and it is the file most often skipped.

## Do this

1. **Sweep the session, not the diff.** Re-read your own turns since the last
   flush and extract every item in these five categories. A code diff will not
   reveal any of them:
   - **Decisions** — anything settled ("we'll store degrees", "provenance is
     dropped"). Include the *why*; a decision without its rationale gets
     re-litigated.
   - **Corrections** — where the user corrected a claim, or you found a prior
     statement wrong. These are the highest-value entries because the wrong
     version is what a summary tends to preserve.
   - **Open questions** — asked of the user and **not answered**. Explicitly
     flagged in `CLAUDE.md` as compaction-critical.
   - **Blocked items** — and *what would unblock them* (an access grant, a repo,
     a live test).
   - **New invariants / gotchas** — a rule discovered the hard way.

2. **Write them to `docs/src/AI/status.md`** as `CS-###` entries, and **bump the
   next-id line**. One item per entry, self-contained: an entry that only makes
   sense if you remember the conversation has failed at its one job. Prefer
   *absolute* dates over "last week".

3. **Sync `Reference/*.md` if — and only if — `src/` changed.** These mirror
   code. If this was a docs-or-design-only session, they are already correct;
   say so rather than touching them. Verify rather than assume:

   ```bash
   git status --porcelain src/
   ```

4. **Update the indexes if the file set changed.** A new/removed/re-scoped doc
   means `docs/src/AI/index.md`'s index **and** the tier-1 map in `CLAUDE.md`.
   Also refresh the file's own tier-3 abstract.

5. **Confirm the must-survive facts are on disk.** `CLAUDE.md` names these as
   compaction-critical, but they are equally what a *next session* needs to pick
   the work up. Check each is recorded *somewhere durable*:
   - the **uncommitted-file list** (this tree carries a large uncommitted build)
   - which **live-GL tests are still pending** (the dev env has no GPU)
   - the **active `CS-###` ids** under discussion and their decisions
   - any **cache/bake state** established (which stages are fresh)
   - **unanswered questions** put to the user

6. **Validate before declaring done.** Cheap checks that catch real breakage:
   - fenced code blocks balanced (an odd count swallows the rest of the page)
   - markdown tables not ragged (equal pipe counts per row)
   - cross-file `.md` links resolve to files that exist
   - no invented dates — ask if you cannot determine today's date

7. **Report** what was recorded, and state plainly what you chose **not** to
   record and why. Then say the session's knowledge is on disk — i.e. it is safe
   both to compact and to close.

## Guardrails

- **Do not fabricate a clean bill of health.** If you skipped `status.md` for
  several turns, say that — the point is an accurate durable record, not a tidy
  report. Silent gaps are the whole problem.
- **Condense, never discard.** Same rule as `garden-claude-docs`: history gets
  shorter, load-bearing rationale always survives.
- **Do not commit.** Flushing docs is not a git operation; leave the tree for the
  user unless they ask.
- **Low-confidence decisions get marked**, not smoothed over — an entry the user
  can find and revisit beats a confident-sounding one they cannot.
- This skill **writes docs**; it does not compact and does not end the session.
  After it finishes the user may compact, close the session, or simply carry on.

## The automation around it

Four pieces, so this is not purely a matter of remembering — and all of it is
**safe with several agents in one repo**, which the first version was not.

| Piece | Where | What it does |
|---|---|---|
| Write flag | `PostToolUse(Write\|Edit)` → `.claude/hooks/flush-mark.sh` | when **this** session edits `CLAUDE.md` or anything under `docs/src/AI`, sets `.claude/.flush/<session_id>.wrote` |
| Compaction gate | `PreCompact` → `.claude/hooks/precompact-gate.sh` | **blocks a manual `/compact`** unless this session's own flag exists; only **warns** on an automatic compaction (blocking an out-of-context session would wedge it) |
| Session dir | `SessionStart(startup\|clear)` | creates `.claude/.flush/`; stale flags are pruned after 14 days |
| Drift warning | `Stop` | warns at end of turn when a `src/` file is newer than every doc |

!!! warning "Why the flag is per-session"

    The original gate compared doc mtimes against one shared timestamp. With two agents
    in the same repo that fails in **both** directions: agent A's doc write satisfies
    agent B's gate (B compacts having flushed nothing), and agent B starting later
    re-stamps the shared marker so A's earlier writes stop counting (A is blocked
    despite having flushed). It also credited edits made by editors and linters.

    A flag set from the agent's **own tool call** is exact and needs no inference. The
    bypass file is per-session for the same reason — a shared one could be consumed by
    whichever agent compacted first.

    The `Stop` drift warning stays repo-global on purpose: *"is this repo's `src/` newer
    than its docs?"* is a genuinely global question. With concurrent agents it can warn
    you about the other agent's edits, which is noise rather than error.

Bypass the gate deliberately with:

```bash
touch .claude/.flush/<your session_id>.skip
```

It is consumed on use, so it never silently disables the gate for later compactions.
