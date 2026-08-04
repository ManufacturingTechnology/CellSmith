#!/usr/bin/env bash
# PreCompact gate — refuse to throw away context that was never written down.
#
# WHY: docs/src/AI/ is the durable memory across a compaction; the transcript is
# not. A long design session can settle a dozen decisions that live only in chat.
# This gate makes "flush the docs" a precondition of a MANUAL compaction instead
# of a thing to remember.
#
# Signal: did THIS session write a durable doc? PostToolUse(Write|Edit) sets
# .claude/.flush/<session_id>.wrote via flush-mark.sh whenever the agent edits
# CLAUDE.md or anything under docs/src/AI.
#
# MULTI-AGENT SAFETY -- why this is per-session rather than a shared timestamp.
# The gate used to ask "is any doc newer than a shared marker file?" With two
# agents in one repo that fails BOTH ways:
#   * agent A writes a doc -> agent B's gate passes, so B compacts having flushed
#     nothing of its own;
#   * agent B starts later and re-stamps the shared marker -> agent A's earlier
#     writes stop counting, so A is blocked despite having flushed.
# It also credited writes made by editors, linters, or the other agent. A flag set
# from the agent's OWN tool call is exact and needs no inference. The bypass file is
# per-session for the same reason: a shared one could be consumed by whichever
# agent compacted first.
#
# Manual  /compact -> BLOCK (the user chose to compact; they can flush + re-run).
# Automatic compact -> WARN ONLY. Blocking an auto-compact can wedge a session
#   that is already out of context, which is strictly worse than a lossy summary.
#
# Contract: stdout is JSON consumed by Claude Code; exit 0 always (the JSON, not
# the exit code, carries the decision).
#   https://code.claude.com/docs/en/hooks
set -u

dir='.claude/.flush'

# The hook payload arrives on stdin; keep it so "manual" vs "auto" and the
# session id can both be read.
payload="$(cat 2>/dev/null || true)"
# Match the trigger field specifically - a bare *"auto"* test would false-positive
# on any other field whose value happens to contain it.
case "$payload" in
  *'"trigger"'*'"auto"'*) trigger='auto' ;;
  *) trigger='manual' ;;
esac

sid="$(printf '%s' "$payload" \
  | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
[ -z "$sid" ] && sid='unknown'

wrote="$dir/$sid.wrote"
override="$dir/$sid.skip"

emit_ok() { exit 0; }

# THIS session wrote a durable doc -> compaction-safe.
[ -f "$wrote" ] && emit_ok

# Deliberate, single-use bypass - per session, so one agent cannot consume another's.
if [ -f "$override" ]; then
  rm -f "$override"
  printf '%s\n' '{"systemMessage":"Flush gate bypassed (per-session skip file consumed). Compacting with undocumented state."}'
  exit 0
fi

reason='No file under CLAUDE.md or docs/src/AI was modified this session, so any decisions, corrections, open questions, or new invariants from this conversation exist ONLY in the transcript - and a compaction summarizes the transcript lossily. Run the /flush skill to flush them into docs/src/AI/status.md (CS-### entries + next-id bump), sync any Reference/*.md that src/ changes invalidated, then re-run /compact. Deliberate bypass: touch .claude/.flush/<your session_id>.skip'

# The user must be TOLD, in their own words, why their /compact did nothing -
# `reason` is addressed to Claude; a `systemMessage` is what reaches the person.
# Someone new to this repo has no idea a flush gate exists, so name the gate, the
# rule, and BOTH ways forward.
notice='COMPACT BLOCKED by this repo'"'"'s doc-flush gate (.claude/hooks/precompact-gate.sh).

WHY: in this repo the durable memory is docs/src/AI/, not the chat. Compacting rewrites the conversation into a lossy summary, so anything decided this session that was never written down is simply gone. No file under CLAUDE.md or docs/src/AI has been modified since this session started, which means nothing was written down.

TO PROCEED, either:
  1. Ask Claude to run /flush - it writes this session'"'"'s decisions into docs/src/AI/status.md and any affected Reference/*.md, then re-run /compact; or
  2. Bypass once (nothing gets written down):  touch .claude/.flush/$sid.skip

Automatic compaction is never blocked, only warned - blocking it would wedge a session that is already out of context.'

if [ "$trigger" = 'auto' ]; then
  # Warn only - see the header comment for why auto must not be blocked.
  printf '{"hookSpecificOutput":{"hookEventName":"PreCompact","additionalContext":"%s"},"systemMessage":"Doc-flush gate: %s"}\n' \
    "$reason" 'this session modified no file under CLAUDE.md or docs/src/AI, so undocumented decisions will be lost in the summary. Auto-compact is not blocked. Consider /flush next time.'
else
  # `reason` -> Claude (what to do); `systemMessage` -> the user (what happened).
  printf '{"decision":"block","reason":"%s","systemMessage":"%s"}\n' "$reason" \
    "$(printf '%s' "$notice" | sed ':a;N;$!ba;s/\n/\\n/g')"
fi
exit 0
