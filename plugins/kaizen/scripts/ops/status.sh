#!/usr/bin/env bash
# kaizen status — at-a-glance health-check for this repo.
# Surfaces: config, hook state, backlog summary, active routine, backup count,
# migration candidates. Read-only.

set -uo pipefail

REPO=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "kaizen status: not in a git repo"
    exit 0
}
cd "$REPO"
# v1.30.0+ — unified backup path from _paths.sh (SSOT).
_SCRIPT_REAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SCRIPT_REAL_DIR/../../skills/workflow/scripts/_paths.sh"  # _paths.sh deferred at legacy

echo "Repo:        $REPO"
echo ""

# ─── Config ──────────────────────────────────────────────────────────
echo "── Config ──"
if [ -f .kaizen.toml ]; then
    grep -vE '^#|^\s*$' .kaizen.toml | head -10
else
    echo "  (no .kaizen.toml — run /kaizen:setup)"
fi
echo ""

# ─── Hook ────────────────────────────────────────────────────────────
echo "── Hook ──"
if [ "$(git config core.hooksPath)" = ".kaizen/hooks" ]; then
    TGT=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" .kaizen/hooks/pre-commit 2>/dev/null || echo '(broken)')
    echo "  ✓ active: .kaizen/hooks → $TGT"
else
    echo "  ∘ inactive (core.hooksPath not set to .kaizen/hooks)"
fi
echo ""

# Resolve project workflow dir via the SSOT helper (handles legacy fallback).
# Use a repo-relative path so the existing `cd "$REPO"` keeps the heredocs short.
WF_DIR=$(kaizen_resolve_workflow_dir "$REPO")
WF_DIR="${WF_DIR#$REPO/}"

# ─── Backlog ─────────────────────────────────────────────────────────
echo "── Backlog ──"
if [ -f "$WF_DIR/backlog.json" ]; then
    WF_DIR="$WF_DIR" python3 - <<'PY'
import json, os
wf = os.environ["WF_DIR"]
data = json.load(open(f"{wf}/backlog.json"))
items = data.get("items", [])
sec = {}
for it in items:
    sec[it["section"]] = sec.get(it["section"], 0) + 1
print(f'  source: {wf}/backlog.json (v{data.get("schema_version", "?")})')
print(f'  in_flight={sec.get("in_flight",0)} next_up={sec.get("next_up",0)} done={sec.get("done",0)} parked={sec.get("parked",0)}')
print(f'  decisions: {len(data.get("decisions", []))}')
PY
else
    echo "  (no $WF_DIR/backlog.json yet — run kaizen-backlog add)"
fi
echo ""

# ─── Workflow-routing ────────────────────────────────────────────────
echo "── Workflow-routing ──"
if [ -f "$WF_DIR/state.json" ]; then
    WF_DIR="$WF_DIR" python3 - <<'PY'
import json, os
wf = os.environ["WF_DIR"]
s = json.load(open(f"{wf}/state.json"))
cur = s.get("current", 0)
st = s.get("stages", [])
status = "complete" if cur >= len(st) else f"stage {cur+1}/{len(st)} = {st[cur]}"
print(f'  routine: {s.get("routine", "?")}  |  {status}')
PY
else
    echo "  (no active routine)"
fi
echo ""

# ─── Backups ─────────────────────────────────────────────────────────
echo "── Backups ──"
SLUG=$(echo "$REPO" | sed 's|^/||; s|/|-|g')
BAK_DIR="$KAIZEN_BACKUP_DIR/$SLUG"
COUNT=$(ls -1 "$BAK_DIR"/*.tar.gz 2>/dev/null | wc -l)
if [ "$COUNT" -gt "0" ]; then
    LAST=$(ls -1t "$BAK_DIR"/*.tar.gz 2>/dev/null | head -1 | xargs -I {} basename {} .tar.gz)
    echo "  $COUNT backup(s) | latest: $LAST"
    echo "  list: kaizen-backup list"
else
    echo "  (no backups yet — run kaizen-backup create)"
fi
echo ""

# ─── Migration candidates (quick scan) ───────────────────────────────
echo "── Migration candidates (quick scan) ──"
LOOSE_COUNT=0
for s in tdd onion-ddd-workflow workflow kaizen kiss yagni solid dry \
         separation-of-concerns law-of-demeter boy-scout-rule \
         convention-over-configuration detect-stack brainstorming \
         dispatching-parallel-agents executing-plans \
         finishing-a-development-branch receiving-code-review \
         requesting-code-review subagent-driven-development \
         systematic-debugging test-driven-development using-git-worktrees \
         using-superpowers verification-before-completion writing-plans \
         writing-skills remember process evolve status init; do
    [ -d "$HOME/.claude/skills/$s" ] && LOOSE_COUNT=$((LOOSE_COUNT + 1))
done
MARKETPLACES=""
[ -d "$HOME/.claude/local-marketplaces/remember-md" ] && MARKETPLACES="remember-md "
[ -n "$LOOSE_COUNT" ] || LOOSE_COUNT=0
echo "  loose duplicate skills: $LOOSE_COUNT  |  duplicate marketplaces: ${MARKETPLACES:-none}"
echo "  full scan: kaizen-migrate scan"
