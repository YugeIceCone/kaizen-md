#!/usr/bin/env bash
# kaizen-env — export shell vars + aliases for interactive use.
#
# Source this from your ~/.bashrc / ~/.zshrc to make kaizen scripts
# callable from any shell:
#
#   source /home/<you>/.claude/local-marketplaces/kaizen-md/plugins/kaizen/skills/workflow/scripts/kaizen-env.sh
#
# Or have /kaizen:env install do it for you (writes one line to your rc).
#
# Sets:
#   KAIZEN_ROOT       — plugin root (the dir with .claude-plugin/)
#   KAIZEN_SCRIPTS    — $KAIZEN_ROOT/skills/workflow/scripts/
#   PATH              — prepends KAIZEN_SCRIPTS so scripts are directly callable
#
# Aliases (interactive shells only):
#   kaizen-flow       async Node+Flow demo (cwd workspace)
#   kaizen-docs       generic workspace docs generator
#   kaizen-backlog    backlog CLI
#   kaizen-cache      cache inspect/clear
#   kaizen-context    context-window state
#   kaizen-inbox      message inbox
#   kaizen-rules      brain-sourced rule lookup

# Resolve THIS script's location → derive plugin root + scripts dir
_kz_resolve() {
    # Prefer realpath for symlink resolution; fall back to python3 if absent
    local src="${BASH_SOURCE[0]:-$0}"
    if command -v realpath >/dev/null 2>&1; then
        realpath "$src"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$src"
    else
        # Best-effort: assume no symlink
        cd "$(dirname "$src")" && pwd && cd - >/dev/null || true
    fi
}

_KZ_SCRIPT_PATH=$(_kz_resolve)
KAIZEN_SCRIPTS="$(dirname "$_KZ_SCRIPT_PATH")"
# Plugin root is 3 levels above scripts/: scripts/ → kaizen/ → skills/ → <plugin-root>
KAIZEN_ROOT="$(cd "$KAIZEN_SCRIPTS/../../.." && pwd)"

export KAIZEN_ROOT
export KAIZEN_SCRIPTS

# Prepend scripts dir to PATH (idempotent)
case ":$PATH:" in
    *":$KAIZEN_SCRIPTS:"*) ;;  # already there
    *) PATH="$KAIZEN_SCRIPTS:$PATH" ;;
esac
export PATH

# Interactive aliases — guarded so non-interactive shells stay quiet
if [ -n "${PS1:-}" ] || [ -n "${ZSH_VERSION:-}" ]; then
    alias kaizen-flow='python3 "$KAIZEN_SCRIPTS/flow_demo.py"'
    alias kaizen-docs='python3 "$KAIZEN_SCRIPTS/docs_gen.py"'
    alias kaizen-backlog='python3 "$KAIZEN_SCRIPTS/backlog.py"'
    alias kaizen-cache='python3 "$KAIZEN_SCRIPTS/cache.py"'
    alias kaizen-context='python3 "$KAIZEN_SCRIPTS/context.py"'
    alias kaizen-inbox='python3 "$KAIZEN_SCRIPTS/inbox.py"'
    alias kaizen-rules='python3 "$KAIZEN_SCRIPTS/rules.py"'
fi

unset _KZ_SCRIPT_PATH
unset -f _kz_resolve
