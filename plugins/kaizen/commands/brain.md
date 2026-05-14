---
name: brain
description: Schema-driven Second Brain — capture / search / promote / audit / evolve. Replaces the retired remember plugin's Node.js scripts with Python + Node+Flow engine + MCP tools. Subcommands - capture <text> [--type T] [--confidence X] [--tier brain|project] [--subject S] | detect <text> | status | path | search <q> [--type T] [--min-confidence X] | promote [--apply] | audit [--apply] | evolve [--stale-days N] | stats
argument-hint: [capture <text>|search <q>|promote|audit|evolve|status|path|detect|stats]
---

# /kaizen:brain

!`bash -c '
set -e
ARGS="${ARGUMENTS:-status}"
SUB="$(echo "$ARGS" | awk "{print \$1}")"
REST="$(echo "$ARGS" | cut -d" " -f2-)"
case "$SUB" in
  capture|detect|status|path)
    exec python3 "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/brain.py" $ARGS ;;
  search|stats|get|clear)
    [ "$SUB" = "stats" ] && exec python3 "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/brain_index.py" stats
    exec python3 "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/brain_index.py" $ARGS ;;
  index)
    exec python3 "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/brain_index.py" $REST ;;
  promote)
    exec python3 "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/brain_promote.py" $REST ;;
  audit)
    exec python3 "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/brain_audit.py" $REST ;;
  evolve)
    exec python3 "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/brain_evolve.py" $REST ;;
  ""|"help")
    echo "/kaizen:brain — Second Brain operations"
    echo
    echo "Subcommands:"
    echo "  capture <text> [--type T] [--confidence X] [--tier T] [--subject S]"
    echo "                       — classify, journal, route, write a thought"
    echo "  detect <text>        — show inferred type without writing"
    echo "  search <q> [--type] [--subdir] [--min-confidence]"
    echo "                       — semantic + frontmatter-filter search"
    echo "  promote [--apply]    — project-memory -> brain (when sources_count>=2)"
    echo "  audit [--apply]      — end-of-session discovery audit"
    echo "  evolve [--stale-days N] — duplicates / freshness / persona drift"
    echo "  status               — file counts per brain subdir"
    echo "  path                 — resolved brain + index + project-memory paths"
    echo "  stats                — index stats (per type / subdir / freshness)"
    ;;
  *)
    echo "unknown subcommand: $SUB"
    exit 1 ;;
esac
'`
