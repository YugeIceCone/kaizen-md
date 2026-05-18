# Brain migration: Remember → kaizen ownership + relocation under `.kaizen/`

## Status
- **State:** draft (not yet executing)
- **Owner:** YugeIceCone + Claude (Opus 4.7)
- **Started:** 2026-05-17
- **Scope:** ~18 files modified, 1 physical move of ~2.7 MB at `~/.claude/brain/`

## Motivation

The Remember plugin is already structurally retired (marketplace dir at
`~/.claude/local-marketplaces/remember-md-retired-20260511T201108Z/`,
not enabled). Brain skills are vendored into kaizen
(`skills/brain/`, `skills/remember/`, `skills/self-improving/brain/`,
8 `brain_*` Python modules + 8 test files). But the data dir
`~/.claude/brain/` is still positioned as if Remember owns it:

1. Env knob is `REMEMBER_BRAIN_PATH` in `~/.claude/settings.json`
2. Three different env vars resolve the path:
   - `_brain.py` uses `KAIZEN_BRAIN_PATH` > `REMEMBER_BRAIN_PATH` > default
   - `rules.py` uses `KAIZEN_BRAIN` (shorter, no SSOT)
   - `knowledge_index.py` uses `KAIZEN_BRAIN` (shorter, no SSOT)
3. 16+ files hardcode `~/.claude/brain` as a literal string (mostly doc
   references in SKILL.md / yaml; a few are code paths)
4. `_paths.py` — the SSOT for every other `KAIZEN_*_DIR` — doesn't
   know about brain

User wants:
- Full ownership in kaizen so they can customize freely
- Brain data under `~/.claude/.kaizen/brain/` (per the assignment
  framework from the prior conversation — kaizen owns its slice
  top-to-bottom)
- Identification of where customization typically happens (capture
  flow, evolve rules, promotion criteria, PARA conventions)
- Replace orphaned `~/.claude/scripts/inject-context.sh` with kaizen
  equivalent (currently a SessionStart hook in user settings)

## Non-goals

- Re-implementing the brain logic (already in kaizen, just consolidating)
- Touching `~/.claude/projects/<slug>/memory/` — that's Claude
  Code's per-project transcript dir convention, leave alone
- Touching the user's brain CONTENT (no edits to Persona.md, Notes/,
  etc.) — only the directory location moves
- Phase F of envelope retrofit (separate plan)

## Verification commands

```bash
# Suite + targeted brain tests
cd /home/cherry86/workspace/kaizen-md/plugins/kaizen && \
  python3 -m unittest discover -s tests -p "test_*.py"

# Brain MCP smoke
python3 plugins/kaizen/skills/workflow/scripts/brain.py status

# Knowledge index rebuild
python3 plugins/kaizen/skills/workflow/scripts/knowledge_index.py stats

# Rules surface
python3 plugins/kaizen/skills/workflow/scripts/rules.py list

# Iron-laws + surface validate
kaizen iron-laws check --staged && kaizen surface validate
```

## Phases

Each phase = one commit. Each ends green on the suite + iron-laws.

### Phase 1 — `_paths.py` SSOT entry for brain

- Add `BRAIN_DIR = Path(os.environ.get("KAIZEN_BRAIN_DIR", KAIZEN_USER_DIR / "brain"))`
- Add `BRAIN_DB = BRAIN_DIR / "brain.db"` (currently inline in `_paths` as
  `KAIZEN_USER_DIR / "brain.db"` — needs to follow brain location)
- Add module-level docstring entry for `KAIZEN_BRAIN_DIR`
- Add unit test in `tests/test_paths.py` if it exists, else inline
- Default path is `~/.claude/.kaizen/brain` — **NEW** location
- Commit: `feat(_paths): add KAIZEN_BRAIN_DIR + BRAIN_DIR SSOT (defaults to .kaizen/brain)`

### Phase 2 — refactor `_brain.py` + `rules.py` + `knowledge_index.py` to use SSOT

- `_brain.py::brain_path()` — consult `_paths.BRAIN_DIR` first, then
  legacy `KAIZEN_BRAIN_PATH` / `REMEMBER_BRAIN_PATH` for back-compat
- `rules.py::BRAIN` — same
- `knowledge_index.py::brain_path()` — same
- Drop the `KAIZEN_BRAIN` short form (kept only in back-compat path —
  emit deprecation note via stderr when used)
- Commit: `refactor(brain): use _paths.BRAIN_DIR as SSOT (legacy envs still honored)`

### Phase 3 — sweep hardcoded `~/.claude/brain` literals

Targets (16 files identified):
- `plugins/kaizen/skills/status/SKILL.md` (2 hits — REMEMBER_BRAIN_PATH refs)
- `plugins/kaizen/skills/workflow/domain/routines.yaml` (1)
- `plugins/kaizen/skills/workflow/SKILL.md` (1)
- `plugins/kaizen/skills/plugin-development/SKILL.md` (4)
- `plugins/kaizen/skills/behaviour-config/SKILL.md` (3)
- `plugins/kaizen/skills/init/SKILL.md` (3 — REMEMBER_BRAIN_PATH naming)
- `plugins/kaizen/skills/workflow/domain/git-discipline.yaml` (1)
- `plugins/kaizen/skills/workflow/scripts/health.sh` (1 — `brain_path` toml key)
- `plugins/kaizen/skills/workflow/scripts/pre-commit.sh` (1 — same)
- `plugins/kaizen/skills/workflow/scripts/setup.sh` (1 — seeds `.kaizen.toml`)
- `plugins/kaizen/skills/workflow/scripts/brain_promote.py` (1 docstring)
- `plugins/kaizen/skills/workflow/scripts/_metrics.py` (2)
- `plugins/kaizen/skills/workflow/scripts/backup.sh` (2)
- `plugins/kaizen/skills/workflow/scripts/schemas.py` (2 docstrings)
- `plugins/kaizen/skills/workflow/references/routines.md` (1)
- `plugins/kaizen/skills/workflow/references/integration.md` (1)
- `plugins/kaizen/skills/iron-laws/domain/iron-laws.yaml` (3)
- `plugins/kaizen/CHANGELOG.md` — historical, **do not touch**
- `plugins/kaizen/docs/sdd-ssot-research.md` — historical, leave

Replace strategy: in docs/SKILL.md, change `~/.claude/brain/` →
`<KAIZEN_BRAIN_DIR>/` (default `~/.claude/.kaizen/brain/`). In shell
scripts, use a `kaizen_brain_dir()` helper to be added to `_paths.sh`.

- Commit: `chore: sweep hardcoded brain path → KAIZEN_BRAIN_DIR references`

### Phase 4 — physical migration helper

- New script: `plugins/kaizen/skills/workflow/scripts/brain_migrate.py`
- Subcommands:
  - `status` — what's at old path, what's at new path, is migration needed
  - `dry-run` — print what would move (file count, total size)
  - `apply` — atomic move with rollback (rsync + verify + delete; or
    `mv` if same filesystem)
  - `rollback` — restore from backup tar
- Backs up to `~/.claude/.kaizen/backups/brain-pre-migration-<UTC>.tar.gz`
  before any move
- Idempotent: re-running `apply` is a no-op if already migrated
- Update settings.json env var: `REMEMBER_BRAIN_PATH` → `KAIZEN_BRAIN_DIR`,
  value `$HOME/.claude/.kaizen/brain`
- New tests in `tests/test_brain_migrate.py` (sandbox-isolated)
- New `bin/kaizen-brain-migrate` wrapper
- Commit: `feat(brain): brain_migrate.py — atomic relocation old → new path`

### Phase 5 — run migration (manual, requires user confirmation)

This is the only live-mutation step. User runs:

```bash
# Dry-run first
kaizen-brain-migrate dry-run

# Apply (with backup)
kaizen-brain-migrate apply

# Verify
kaizen-brain-migrate status
ls ~/.claude/.kaizen/brain/   # confirm content
python3 plugins/kaizen/skills/workflow/scripts/brain.py status
```

After confirmed: edit `~/.claude/settings.json` (the script can do this
or user does manually). No commit here — settings.json is outside the repo.

### Phase 6 — inject-context.sh decision

- Read `~/.claude/scripts/inject-context.sh` fully + compare to
  kaizen's SessionStart hooks (`session-surface-kaizen-cli.sh`,
  `session-surface-backlog.sh`, `brain-session-end.sh`)
- If kaizen's hooks already cover it → uninstall (remove from
  settings.json, delete script with backup)
- If it does something kaizen DOESN'T (e.g. workflow state, plan list,
  git unpushed-commits surface) → port the non-duplicated bits into a
  new kaizen hook `hooks/claude/session-surface-project-state.sh`
- Commit: `feat(hooks): session-surface-project-state replaces inject-context.sh`
  (or `chore(hooks): uninstall obsolete inject-context.sh`)

### Phase 7 — customization-hooks map (deliverable, not code)

New reference doc: `plugins/kaizen/skills/brain/references/customization.md`

Maps the customization surface so future tweaks are obvious:

| Concern | File | What to edit |
|---|---|---|
| **PARA folder names** | `assets/templates/remember.md` + setup logic in `init/SKILL.md` | Rename `Notes/Areas/Projects/Resources/Tasks/Inbox/Journal/People/Templates/Archive` |
| **Note frontmatter schema** | `assets/schemas/note.schema.json` | Add/remove fields, change enums (`type`, `freshness`) |
| **Capture triggers** | `hooks/claude/brain-*.sh` + `brain_capture` MCP tool | Edit the regex list that detects "remember this" / "save this" |
| **Promotion criteria** | `brain_promote.py::should_promote()` | Change `sources_count >= 2` or `promote: true` rule |
| **Confidence thresholds** | `brain_audit.py`, `brain_evolve.py` | Tune the freshness / confidence cutoffs |
| **Persona Top Beliefs** rules | `brain_evolve.py::reflect()` | Change what gets surfaced into `Persona.md ## Top Beliefs` |
| **Kaizen-rule frontmatter** | `assets/schemas/kaizen-rule.schema.json` + `rules.py` | Add new rule categories the gate consumes |
| **Inbox naming** | `brain_audit.py` | Change `draft-<today>-<slug>.md` template |
| **Embedding model** | `config.py::EMBED_MODEL` | Switch from `all-MiniLM-L6-v2` to another model |
| **Hook bypass knobs** | `KAIZEN_BRAIN_*_DISABLE` env vars per `hooks/claude/brain-*.sh` | Disable specific brain hooks |

Plus: link to the brain-related MCP tools (`brain_capture`, `brain_search`,
`brain_status`, `brain_promote_preview`, `brain_promote_apply`,
`brain_audit`, `brain_index_build`, `brain_index_stats`) and their CLIs.

- Commit: `docs(brain): customization.md reference — map of editable surfaces`

## Rollback plan

- Phases 1-3 + 6-7 are git-revertable
- Phase 4 (`brain_migrate.py`) ships with `rollback` subcommand
- Phase 5 (live move) writes to backup tar BEFORE moving — restorable via:
  ```bash
  tar -xzf ~/.claude/.kaizen/backups/brain-pre-migration-*.tar.gz -C /
  ```

## Decisions (locked 2026-05-17)

- **Legacy env vars** → **RIP OUT NOW**. Only `KAIZEN_BRAIN_DIR` resolves.
  No back-compat for `REMEMBER_BRAIN_PATH` / `KAIZEN_BRAIN` /
  `KAIZEN_BRAIN_PATH`. Single user, no installed base.
- **Move strategy** → **rsync + checksum verify ALWAYS**, even on
  same filesystem. Belt-and-suspenders for irreplaceable beliefs.
  Sequence: `rsync -a --checksum src/ dst/` → verify file count +
  total size match → unlink source only on success.
- **Settings.json edit** → **auto-apply with diff preview + backup**.
  Print the unified diff, write backup to
  `~/.claude/settings.json.bak-<UTC>.json`, then atomic write
  (tempfile + `os.replace`). Use stdlib `json` only; the user's
  settings.json is plain JSON (no comments observed).

### Settings.json foolproof patterns (research deliverable in Phase 4)

Patterns to bake into `brain_migrate.py::edit_settings()`:

1. **Atomic write**: tempfile in same directory + `os.replace()`
   (POSIX atomic rename). Never write partial JSON.
2. **Backup-first**: copy to `settings.json.bak-<UTC>.json` BEFORE
   any read of the original. If the read/parse fails, the backup is
   already there.
3. **Parse-validate-write loop**: load, mutate dict, dump, **re-parse
   the output**, verify the expected key/value is present. Only then
   write. Catches dump bugs (encoder dropping a key silently).
4. **JSON shape preservation**: use `indent=2`, `sort_keys=False`,
   `ensure_ascii=False`. Matches Claude Code's own writer output
   (verified by reading current settings.json — uses 2-space indent,
   key-insertion order).
5. **Schema validation (best-effort)**: if `~/.claude/schemas/` has
   a Claude Code settings schema, validate against it; warn but don't
   block on schema miss (schema may evolve).
6. **Cross-process safety**: Claude Code may read settings.json mid-
   write. Atomic write + same-FS rename guarantees a reader sees
   either the OLD or NEW file, never a partial. No advisory lock
   needed for this property.
7. **Diff preview**: print `difflib.unified_diff(old, new, fromfile,
   tofile)` to stderr before any write. User sees the exact change.
8. **Rollback recipe**: print the one-line restore command on success
   (`mv settings.json.bak-<UTC>.json settings.json`).

## Effort estimate

- Phases 1-3 (refactor + sweep): ~2-3 hours
- Phase 4 (migration script + tests): ~1-2 hours
- Phase 5 (live run): ~5 min user-driven
- Phase 6 (inject-context.sh decision): ~30 min read + ~30 min port
- Phase 7 (customization map): ~30 min

**Total: ~5-7 hours of focused work, 6 commits.**
