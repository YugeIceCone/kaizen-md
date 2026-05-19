---
name: docs
description: "Per-package doc generator. Rust (Cargo.toml) / JS-TS (package.json) / Go (go.mod) / Python (pyproject.toml). Stdlib-only. Writes .md + .json per package."
---

# kaizen docs

Generate workspace documentation. Drop-in replacement for `cargo xtask docs --json` that also handles JS / Go / Python workspaces.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/docs_gen.py $ARGUMENTS`

## Subcommands

| arg | effect |
|---|---|
| (none) or `detect` | list detected packages (language + relative path) — read-only |
| `scan [--root .] [--output docs/crates/] [--format both]` | scan + write `.md` + `.json` per package |
| `one <pkg_dir> [--format both]` | single package, print to stdout |

`scan --format json` for machine-readable only. `scan --format md` for humans only. `both` (default) emits both.

## Schema (`kaizen.docs` v1)

Per package:

```json
{
  "schema_version": 1,
  "kind": "kaizen.docs",
  "name": "shodan-core",
  "path": "crates/core",
  "language": "rust",
  "version": "0.1.0",
  "loc": { "src": 4632, "test": 0, "total": 4632 },
  "files": { "src": 58, "test": 0, "total": 58 },
  "deps": [...],
  "dev_deps": [...],
  "public_api": {
    "fn": 42, "struct": 8, "trait": 3, "enum": 2,
    "names": ["build_registry", "Context", "Node", ...]
  },
  "scanned_at": "2026-05-11T22:50:12Z"
}
```

`public_api.names` capped at 30 entries. `loc` counts non-blank, non-comment-only lines. Test files are detected by language convention (`_test.rs`, `.test.ts`, `_test.go`, `test_*.py`).

## Skipped directories

`target/`, `node_modules/`, `.git/`, `vendor/`, `dist/`, `build/`, `.venv/`, `venv/`, `__pycache__/`, `.kaizen/`, `.workflow/`, `.claude/`, `.idea/`, and any dir starting with `.`.

## Integration with shodan

Shodan's CLAUDE.md says: "regenerate via `cargo xtask docs --json` after every workspace shape change." This generator emits the same `.md` + `.json` shape (one of each per crate) into `docs/crates/`. The schema (`kaizen.docs` v1) is portable across non-Rust workspaces, so a multi-language monorepo can use the same tool.

Run from shodan root: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/docs_gen.py scan` — emits 24 records (one per crate) plus the workspace root.
