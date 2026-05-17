# Brain — customization map

Kaizen now owns the Second Brain end-to-end (post Remember-plugin
retirement, v1.38.0). This doc maps the editable surface — what's
hardcoded vs configurable vs schema-driven — so customizations are
obvious and don't require code archaeology.

If you want to do X, edit Y.

---

## 1. Path layout — where brain lives on disk

| Want to change | Edit | Notes |
|---|---|---|
| Brain directory location | `KAIZEN_BRAIN_DIR` env (or `_paths.py::BRAIN_DIR`) | Default `~/.claude/.kaizen/brain`. SSOT; every kaizen module reads via `_paths`. |
| Brain index DB path | `_paths.py::BRAIN_DB` | Always `<BRAIN_DIR>/brain.db`. Move BRAIN_DIR to relocate both. |
| PARA folder names | `assets/templates/remember.md` + `skills/init/SKILL.md` | The 10 default folders (`Notes / Projects / People / Areas / Inbox / Journal / Tasks / Resources / Templates / Archive`) are baked into the init flow; rename here to redefine the structure. |
| Persona file name | `_paths.py::BRAIN_PERSONA` | Currently `<BRAIN_DIR>/Persona.md`. Used by reflection + Top Beliefs surface. |

**Migration**: `kaizen-brain-migrate apply` is the canonical move command (rsync + verify + atomic settings.json edit).

---

## 2. Note structure — what fields a brain note carries

| Want to change | Edit |
|---|---|
| Required/optional frontmatter fields | `assets/schemas/note.schema.json` |
| Note `type` enum (world-fact / belief / observation / experience / ...) | Same — `properties.type.enum` |
| Confidence range | Same — `properties.confidence.minimum/maximum` (currently 0.0–1.0) |
| Freshness values | Same — `properties.freshness.enum` (fresh / stable / hardened / stale / archived) |

Schema is loaded by `_brain.parse_note()` and enforced by the validator (`skills/self-improving/brain/validator.py`) + `application/_brain_tests.py`.

---

## 3. Entity types — how thoughts get classified

`skills/brain/domain/entity-types.yaml` is the SSOT for the four
epistemic categories (`world-fact / belief / observation / experience`)
and their detection rules.

| Want to change | Edit |
|---|---|
| What types exist | `entity-types.yaml::types[]` |
| What triggers a `world-fact` classification | `types[name=world-fact].triggers[]` (substring/regex list) |
| Which folders a type defaults to | `types[*].target_dirs[]` (e.g. add `Projects/<project>` to `belief`) |
| What frontmatter a type requires | `types[*].frontmatter.required / optional` |
| Add a new entity type | Append to `types[]` with name, description, target_dirs, frontmatter, triggers; add to `note.schema.json::type.enum`; verify `_brain.detect_type()` consults the yaml (it does) |

---

## 4. Routing — which tier a thought lands in (brain vs project-memory)

`skills/brain/domain/routing.yaml` is the SSOT for the tier-selection logic.

| Want to change | Edit |
|---|---|
| Brain path lookup env var | `tiers[name=brain].path_env` (default `KAIZEN_BRAIN_DIR`) |
| Project-memory path template | `tiers[name=project-memory].path_template` |
| Which types route where | `tiers[*].types[]` (e.g. force `belief` to always go brain) |
| Subject-match → folder rules | `subject_rules[]` — first match wins |
| Default fallback subdir | `default_target_dir` |

---

## 5. Promotion — project-memory → brain

`skills/workflow/scripts/brain_promote.py::should_promote()` is the gate.

Default criteria:
- `sources_count >= 2` (belief survived re-derivation), OR
- `promote: true` explicitly set in frontmatter

| Want to change | Edit |
|---|---|
| Sources threshold | `brain_promote.py` — search for `sources_count` |
| Add a new promotion criterion | Same file; mutate `should_promote()` to add the predicate |
| Where promoted notes go | `brain_promote.py::pick_destination()` — consults `routing.yaml` |
| Tombstone shape (left at project-memory) | `brain_promote.py` docstring around `promoted_to:` |

CLI: `kaizen-brain-promote` (dry-run) / `--apply`. MCP tools: `brain_promote_preview`, `brain_promote_apply`.

---

## 6. Audit — end-of-session discovery

`skills/workflow/scripts/brain_audit.py` mines the session JSONL transcripts for capture-candidates and drafts them to `<BRAIN_DIR>/Inbox/draft-<today>-<slug>.md`.

| Want to change | Edit |
|---|---|
| Inbox draft naming | `brain_audit.py` — search for `draft-` prefix |
| Commit-window for the scan | `brain_audit.py::limit_commits` arg default |
| What signals trigger a draft | The classifier in `brain_audit.py` (re-uses `_brain.detect_type`) |
| Auto-fire on SessionEnd | `hooks/claude/brain-session-end.sh` (already wired; toggle via `KAIZEN_BRAIN_DISABLE` env) |

CLI: `kaizen-brain-audit` (dry-run) / `--apply`. MCP: `brain_audit`.

---

## 7. Evolve — consolidation + freshness + Persona promotion

`skills/workflow/scripts/brain_evolve.py` is the periodic consolidation
flow. Detects dupes, ages stale notes, and promotes high-confidence
notes into `Persona.md ## Top Beliefs`.

| Want to change | Edit |
|---|---|
| Stale threshold (fresh → stale) | `brain_evolve.py --stale-days` default |
| Hardened threshold (stable → hardened) | `brain_evolve.py` — confidence + age cutoffs |
| Persona Top Beliefs promotion criteria | `brain_evolve.py::reflect()` — what gets surfaced |
| Dupe detection root-stem normalization | `brain_evolve.py::FindDupes` Node |

CLI: `kaizen-brain-evolve`. MCP: `brain_evolve`.

---

## 8. Capture flow — what triggers an auto-save

The capture pipeline is in `skills/workflow/scripts/brain.py`. Triggered
by:
- Explicit: `/kaizen:brain capture <text>` slash command
- MCP: `brain_capture(text, type_hint?, confidence?, tier_hint?, subject?)`
- UserPromptSubmit hook: `hooks/claude/brain-user-prompt.sh` matches
  "remember this" / "save this" / "for the record" / "brain dump"
  and surfaces a hint (advisory, no auto-write)

| Want to change | Edit |
|---|---|
| Hook trigger regex list | `hooks/claude/brain-user-prompt.sh` (the grep patterns) |
| Default confidence when not specified | `brain.py::cmd_capture` default |
| Default tier-hint heuristic | `_brain.select_target()` — consults `routing.yaml` |
| What gets emitted to stderr post-capture | `brain.py::cmd_capture` |

Bypass any brain hook: `KAIZEN_BRAIN_DISABLE=1`.

---

## 9. Search + index

`skills/workflow/scripts/brain_index.py` is the SQLite + sentence-transformers index over Notes / Projects / People / Areas.

| Want to change | Edit |
|---|---|
| Which subdirs get indexed | `brain_index.py` — search for the iter walker |
| Index DB path | `_paths.py::BRAIN_DB` |
| Embedding model | `config.py::EMBED_MODEL` (default `all-MiniLM-L6-v2`) |
| Fallback to LIKE search (skip embeddings) | `KAIZEN_BRAIN_INDEX_SKIP_EMBED=1` env |

CLI: `kaizen-brain-index index|search|stats|get|path|clear`. MCP: `brain_search`, `brain_index_build`, `brain_index_stats`.

---

## 10. Kaizen-rule notes — gate behavior

The pre-commit gate consumes brain notes that carry a `kaizen:` block in their frontmatter (rule notes). Surface: `skills/workflow/scripts/rules.py`.

| Want to change | Edit |
|---|---|
| Which `rule_type` values are valid | `rules.py::VALID_RULE_TYPES` + `assets/schemas/kaizen-rule.schema.json` |
| Add a new rule kind | Append to `VALID_RULE_TYPES`, write the consumer handler in `rules.py`, add a template (`rules.py template <name>`) |
| Which gate check a rule overrides | `kaizen-rule.schema.json::properties.check_id` |
| Custom-pattern rule regex format | `rules.py::cmd_custom_patterns` |

CLI: `kaizen-rules list|show|deletion-allowed|severity|custom-patterns|dependency-allowed|validate|template <type>`.

---

## 11. Hook bypass knobs (per-feature kill switches)

Every brain-related hook honors a `KAIZEN_*_DISABLE` env var per the
hook-bypass-knob iron-law:

| Hook | Bypass env | Behavior |
|---|---|---|
| SessionStart context injection | `KAIZEN_INJECT_CONTEXT_DISABLE=1` | emits `{}` |
| Brain auto-capture hint (UserPromptSubmit) | `KAIZEN_BRAIN_DISABLE=1` | no hint emitted |
| Brain SessionEnd audit | `KAIZEN_BRAIN_DISABLE=1` | skip audit |
| Pre-commit brain rules scan | `KAIZEN_GATE_DISABLE=1` | skip whole gate |

Set in shell, in `~/.claude/settings.json::env`, or per-command.

---

## 12. Quick edits cheat sheet

```bash
# Move brain elsewhere (after a fresh install)
export KAIZEN_BRAIN_DIR=/path/to/your/brain

# Add a new world-fact trigger phrase
$EDITOR plugins/kaizen/skills/brain/domain/entity-types.yaml
# → types[0].triggers: append your phrase

# Tighten promotion (require 3 sources, not 2)
$EDITOR plugins/kaizen/skills/workflow/scripts/brain_promote.py
# → search for `sources_count >= 2`

# Disable the brain SessionEnd audit
$EDITOR ~/.claude/settings.json   # or shell rc
# → env: KAIZEN_BRAIN_DISABLE=1

# Add a new rule type for the gate
$EDITOR plugins/kaizen/skills/workflow/scripts/rules.py
# → VALID_RULE_TYPES + the dispatcher

# Customize Persona Top Beliefs promotion criteria
$EDITOR plugins/kaizen/skills/workflow/scripts/brain_evolve.py
# → reflect() function
```

---

## What's NOT yet customizable (and where to add it)

These hardcode-points might be worth lifting to config in the future:

- **PARA folder names** are split between `assets/templates/remember.md` and `skills/init/SKILL.md`. Should be in `entity-types.yaml` or a new `para.yaml`.
- **Inbox draft template** (`draft-<today>-<slug>.md`) is f-stringed in `brain_audit.py`. Should be in a yaml template file.
- **Confidence buckets** (low/medium/high cutoffs) are scattered across `brain_evolve.py`. Should be in `config.py` or a new `freshness.yaml`.
- **Default capture confidence** (when none given) is a magic number in `brain.py`. Should be in `config.py`.

If any of these matter to your customization plans, file a backlog item via `kaizen-backlog add`.
