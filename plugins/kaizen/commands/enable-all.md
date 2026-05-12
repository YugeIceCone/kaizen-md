---
name: enable-all
description: One-shot kaizen setup. Default scope is project (wires pre-commit gate) AND the curated best-default global stack (disable-dupes, statusline, shell env). Slow/intrusive steps (indexers, browser, daemon, trace-proxy) are opt-in via --with-* flags. Each underlying installer is idempotent; safe to re-run.
argument-hint: [--dry-run|--no-globals|--no-project|--with-index|--with-browser|--with-daemon|--with-trace-proxy|--yes]
---

# kaizen enable-all

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/enable_all.sh $ARGUMENTS`
