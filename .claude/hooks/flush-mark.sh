#!/usr/bin/env bash
# PostToolUse(Write|Edit|NotebookEdit): record that THIS session wrote a durable doc.
#
# WHY this replaced the old mtime heuristic: the gate used to ask "is any doc newer
# than a shared timestamp file?" That is not attributable. With two agents in one
# repo it fails BOTH ways -- agent A's writes satisfy agent B's gate (B compacts
# having written nothing), and a later SessionStart overwrites the shared stamp so
# A's earlier writes stop counting (A is blocked despite flushing). It also counted
# writes by editors and linters as if the agent had made them.
#
# A per-session flag set from the agent's own tool call is exact: the hook fires for
# THIS session's edit, so attribution needs no inference.
#
# Contract: emit nothing, exit 0 always. This hook must never interrupt a turn.
set -u

payload="$(cat 2>/dev/null || true)"

# Only durable-memory paths count. Deliberately narrow: writing src/ or scratchpad/
# is not flushing decisions.
case "$payload" in
  *docs/src/AI*|*CLAUDE.md*) ;;
  *) exit 0 ;;
esac

sid="$(printf '%s' "$payload" \
  | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
[ -z "$sid" ] && sid='unknown'

dir='.claude/.flush'
mkdir -p "$dir" 2>/dev/null || exit 0
: > "$dir/$sid.wrote" 2>/dev/null || true

# Opportunistic cleanup: drop flags untouched for 14 days so the dir cannot grow
# without bound. Failure here is irrelevant to the turn.
find "$dir" -maxdepth 1 -type f -mtime +14 -delete 2>/dev/null || true
exit 0
