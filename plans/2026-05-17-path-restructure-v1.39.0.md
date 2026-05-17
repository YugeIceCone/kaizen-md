# Path restructure — flatten + categorize (v1.39.0)

## Status
- **State:** draft (not yet executing)
- **Owner:** YugeIceCone + Claude (Opus 4.7)
- **Started:** 2026-05-17
- **Scope:** ~9 _paths.py constants + path_migrate.py + live migration of 8 dirs + 4 files in `~/.claude/.kaizen/`

## Motivation

After the brain migration consolidated everything under `~/.claude/.kaizen/`, an audit found 3 layout pain points:

1. **Heterogeneous root-level singletons** — `handoff.db`, `manifest.json`, `manifest.lock`, `profile.env` all bare at root with no semantic grouping.
2. **Search/index dirs scattered** — `trace/`, `knowledge/`, `scrape/`, `claude-docs/` each hold an index.db + maybe a companion file, but there's no umbrella signaling "all the search-style state lives here".
3. **Legacy archive misnamed** — `_legacy/` uses a hidden-file prefix but is a normal dir; should be `archive/`.

## Decisions (locked)

Same pattern as the brain migration:
- **Single-user clean cut** — no back-compat envs. Old paths become `LEGACY_PATHS` entries the migrator consumes; consumers read only the new SSOT.
- **rsync + checksum verify** for every move.
- **Backup tarball** to `~/.claude/.kaizen/backups/path-restructure-<UTC>.tar.gz` before any change.
- **Atomic** where applicable.
- **Auto-rerunnable** — re-applying is a no-op.

## Non-goals

- Touching the project-side `<repo>/.kaizen/` layout (already clean — backlog.json/state.json/etc. at sensible depth).
- Cleaning up `~/.claude/.kaizen/scripts/` (vestigial embed pipeline — separate concern; preserve for now).
- Renaming individual files inside the feature dirs (e.g. `trace/events.jsonl` stays as `events.jsonl`; only the parent dir moves).

## Concrete mapping

```
OLD                                        NEW
─────────────────────────────────────────────────────────────────
~/.claude/.kaizen/trace/                → ~/.claude/.kaizen/indexes/trace/
~/.claude/.kaizen/knowledge/            → ~/.claude/.kaizen/indexes/knowledge/
~/.claude/.kaizen/scrape/               → ~/.claude/.kaizen/indexes/scrape/
~/.claude/.kaizen/claude-docs/          → ~/.claude/.kaizen/indexes/claude-docs/
~/.claude/.kaizen/daemon/               → ~/.claude/.kaizen/data/daemon/
~/.claude/.kaizen/handoff.db            → ~/.claude/.kaizen/data/handoff.db
~/.claude/.kaizen/manifest.json         → ~/.claude/.kaizen/data/manifest.json
~/.claude/.kaizen/manifest.lock         → ~/.claude/.kaizen/data/manifest.lock
~/.claude/.kaizen/profile.env           → ~/.claude/.kaizen/data/profile.env
~/.claude/.kaizen/observe/snapshots/    → ~/.claude/.kaizen/snapshots/  (hoist 1 level)
~/.claude/.kaizen/_legacy/              → ~/.claude/.kaizen/archive/    (rename, drop _)

UNCHANGED (already correctly shaped):
~/.claude/.kaizen/brain/        — PARA structure, kaizen-owned
~/.claude/.kaizen/inbox/        — operational queue
~/.claude/.kaizen/backups/      — per-repo nesting carries meaning
~/.claude/.kaizen/schemas/      — user-defined templates
~/.claude/.kaizen/blobs/        — content-addressed
~/.claude/.kaizen/install.log   — single user-visible log
~/.claude/.kaizen/scripts/      — vestigial; separate concern
```

## Verification commands

```bash
# Suite + targeted tests
cd /home/cherry86/workspace/kaizen-md/plugins/kaizen && \
  python3 -m unittest discover -s tests -p "test_*.py"

# Migration smoke
kaizen-path-migrate status
kaizen-path-migrate dry-run
kaizen-path-migrate apply
kaizen-path-migrate status   # should report all 'already-migrated'

# Consumer smoke (each touches paths from _paths.py)
python3 plugins/kaizen/skills/workflow/scripts/observe.py layers
python3 plugins/kaizen/skills/workflow/scripts/brain.py status
python3 plugins/kaizen/skills/workflow/scripts/metrics.py session
python3 plugins/kaizen/skills/workflow/scripts/trace.py stats
```

## Phases

### Phase 1 — `_paths.py` + `_paths.sh` + `config.py` SSOT update
- Add `INDEXES_DIR`, `DATA_DIR`, `SNAPSHOTS_DIR`, `ARCHIVE_DIR` constants
- Refactor existing constants to nest under them:
  - `TRACE_DIR = INDEXES_DIR / "trace"` (was `KAIZEN_USER_DIR / "trace"`)
  - `KNOWLEDGE_DIR = INDEXES_DIR / "knowledge"`
  - `SCRAPE_DIR = INDEXES_DIR / "scrape"`
  - `CLAUDE_DOCS_DIR = INDEXES_DIR / "claude-docs"`
  - `DAEMON_DIR = DATA_DIR / "daemon"`
  - `OBSERVE_SNAPSHOTS = SNAPSHOTS_DIR` (or hoist OBSERVE_DIR out entirely)
- Add bare singletons:
  - `HANDOFF_DB = DATA_DIR / "handoff.db"`
  - `MANIFEST_JSON = DATA_DIR / "manifest.json"`
  - `MANIFEST_LOCK = DATA_DIR / "manifest.lock"`
  - `PROFILE_ENV = DATA_DIR / "profile.env"`
- Add to `LEGACY_PATHS` for the migrator
- Mirror in `_paths.sh`
- Commit: `feat(_paths): umbrella dirs indexes/ + data/ + snapshots/ + archive/ (v1.39.0)`

### Phase 2 — `path_migrate.py` migrator
- New CLI: `plugins/kaizen/skills/workflow/scripts/path_migrate.py`
- Subcommands: `status` / `dry-run` / `apply` / `rollback`
- Per-move: rsync+checksum verify+backup
- Single tarball backup of the WHOLE `~/.claude/.kaizen/` tree before any move
- Idempotent (re-runs are no-ops)
- Envelope output (`--json`)
- TDD: write the test class first (sandboxed tempdir + fake legacy tree), watch RED, implement
- Bin wrapper + plugin.json permission
- Commit: `feat(paths): path_migrate.py — atomic v1.38 → v1.39 layout relocation`

### Phase 3 — Live migration
- `kaizen-path-migrate status` → dry-run → apply
- Verify each new location reads correctly
- No repo commit (user-global state move)

### Phase 4 — Doc sweep + plugin.json bump
- Update SKILL.md / references / CHANGELOG entry
- Bump `plugin.json::version` to `1.39.0`
- Commit: `chore(release): bump v1.39.0 — layout restructure`

### Phase 5 — Final verification
- Full suite green
- iron-laws + surface validate clean
- Smoke each major consumer (observe, brain, metrics, trace, daemon)

## Rollback plan

- Phases 1, 2, 4 are git-revertable
- Phase 3 (live move): `kaizen-path-migrate rollback` restores from backup tarball

## Effort estimate

- Phase 1: ~20 min (mechanical _paths.py edit + mirror)
- Phase 2: ~60-90 min (script + 15+ tests, TDD-disciplined)
- Phase 3: ~5 min (run, verify)
- Phase 4: ~15 min (doc sweep)
- Phase 5: ~5 min (validation)

**Total: ~2 hours, 4-5 commits.**
