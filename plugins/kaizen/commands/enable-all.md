---
name: enable-all
description: One-shot kaizen setup. Alias for `/kaizen:install --enable-all` (v1.33+ consolidation). Default scope is project (pre-commit gate) AND the curated best-default global stack (disable-dupes, statusline, shell env). Slow/intrusive steps (indexers, browser, daemon, trace-proxy) are opt-in via --with-* flags. Each underlying installer is idempotent.
argument-hint: [--dry-run|--no-globals|--no-project|--with-index|--with-browser|--with-daemon|--with-trace-proxy|--yes]
---

# kaizen enable-all

**Consolidated into `/kaizen:install --enable-all`** (v1.33+). This
command still works — it invokes the same underlying `enable_all.sh`
script — but the canonical entry point is now `/kaizen:install` with
the `--enable-all` flag (or any `--with-*` / `--no-*` flag, which
auto-delegates).

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/enable_all.sh $ARGUMENTS`
