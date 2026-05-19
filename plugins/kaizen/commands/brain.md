---
name: brain
description: "Second Brain - capture / search / promote / audit / evolve + zero-roundtrip block-level edits. Triggers - "remember this", "search the brain", "promote a belief", "audit memory", "evolve brain"."
argument-hint: "(empty = multiSelect verb checklist) | [capture <text>|search <q>|promote|audit|evolve|status|path|detect|stats|blocks --file X|show --file X --block PATH|edit --file X --block PATH --replace BODY]"
allowed-tools: ["AskUserQuestion", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain/brain.py:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/indexers/build_index.py:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain/brain_promote.py:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain/brain_audit.py:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain/brain_evolve.py:*)"]
---

# /kaizen:brain

## Interactive menu (when `$ARGUMENTS` is empty)

When invoked with **no arguments**, step the user through a single
multiSelect AskUserQuestion call over the 4 most-frequent verbs.
Dispatch each pick sequentially via the args-mode body below. For
the less-common verbs (`detect`, `path`, `promote`, `evolve`,
`migrate`, `index`, `stats`, `seed`), pass them as `$ARGUMENTS`
directly — the menu intentionally curates the high-frequency surface
to respect the 4-option-per-question ceiling.

### Question — verb picker

```
question:    "Which brain operations should I run?"
header:      "Verb"
multiSelect: true
options:
  - label: "Capture"
    description: "Write a thought to the brain — agent will prompt for the text body separately, then route by type."
  - label: "Search"
    description: "Semantic + frontmatter-filter search — agent will prompt for the query separately."
  - label: "Audit"
    description: "End-of-session discovery audit (dry-run unless --apply)."
  - label: "Status"
    description: "File counts per brain subdir (read-only diagnostic)."
```

### After the pick

For each selected verb, prompt the user for the per-verb input it
needs, then dispatch via this slash's args-mode body:

| Verb pick | Follow-up prompt           | Dispatch                                 |
|-----------|----------------------------|------------------------------------------|
| Capture   | "What to capture?"         | `/kaizen:brain capture "<text>"`         |
| Search    | "Search query?"            | `/kaizen:brain search "<query>"`         |
| Audit     | "Apply changes (--apply) or dry-run?" | `/kaizen:brain audit [--apply]` |
| Status    | (none — no parameters)     | `/kaizen:brain status`                   |

Verbs not in the picker (`detect`, `path`, `promote`, `evolve`,
`migrate`, `index`, `stats`, `seed`) are reachable directly:
`/kaizen:brain <verb> [args]`. See the args-mode help below for the
full list.

## Args-mode dispatch

!`bash -c '
set -e
ARGS="${ARGUMENTS:-status}"
SUB="$(echo "$ARGS" | awk "{print \$1}")"
REST="$(echo "$ARGS" | cut -d" " -f2-)"
case "$SUB" in
  capture|detect|status|path)
    exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/brain/brain.py" $ARGS ;;
  search|stats|get|clear)
    [ "$SUB" = "stats" ] && exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/indexers/build_index.py" stats
    exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/indexers/build_index.py" $ARGS ;;
  index)
    exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/indexers/build_index.py" $REST ;;
  promote)
    exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/brain/brain_promote.py" $REST ;;
  audit)
    exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/brain/brain_audit.py" $REST ;;
  evolve)
    exec python3 "${CLAUDE_PLUGIN_ROOT}/scripts/brain/brain_evolve.py" $REST ;;
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
