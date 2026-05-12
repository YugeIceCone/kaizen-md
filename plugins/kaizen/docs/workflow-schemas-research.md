# Declarative workflow schemas — design discussion + migration path

> Status: design only (2026-05-12). v1.13.0 ships the scaffold (`schemas/` dir + 2 examples + this doc). Wiring into the existing `workflow-routing` skill is **deferred** to v1.14.0+ and tracked as a follow-up.

## Source

[intent-driven.dev — OpenSpec Custom Schemas](https://intent-driven.dev/blog/2026/02/12/openspec-custom-schemas/) — Feb 2026. The core insight: instead of hardcoding workflow routines (research → explore → analyze → …) into the tool, declare them as **yaml schemas with markdown templates**. Each project can author its own; users can author user-wide ones; the tool falls back to built-in defaults.

## Why this matters for kaizen

Today, kaizen's `workflow-routing` skill has six hardcoded routines: `audit`, `build-feature`, `fix-bug`, `refactor`, `migrate`, `harden`. Each is implemented as bash logic in `workflow.sh` + per-stage prompts in `references/routines.md`. Adding a new routine requires editing the plugin source.

A declarative schema system makes this:

- **User-extensible**: drop a `~/.claude/kaizen-schemas/my-routine/schema.yaml` and it's available without modifying the plugin.
- **Project-extensible**: a `.workflow/schemas/<name>/schema.yaml` lives in the repo, version-controlled with the code.
- **Composable**: schemas declare dependencies between artifacts (a DAG), so adding `research` between two stages is one yaml edit.
- **Inspectable**: agents (and humans) can read the yaml to understand what a routine WILL DO before running it.

## Resolution order (per OpenSpec convention)

When kaizen loads a schema by name, it checks in this order:

1. **Project-level**: `<repo>/.workflow/schemas/<name>/schema.yaml`
2. **User-level**: `~/.claude/kaizen-schemas/<name>/schema.yaml`
3. **Built-in**: `<plugin>/schemas/<name>/schema.yaml`

First hit wins. A project can fully override a built-in routine. A user can have personal variants.

## Schema format (kaizen-flavored)

```yaml
name: <schema-name>            # matches dir name
version: 1
description: |
  Free-form description.

artifacts:
  - id: <unique-id>            # referenced by `requires`
    generates: <output-path>   # may use **/*.md globs
    template: <template-path>  # relative to templates/ dir; null = no template
    requires: [<id>, ...]      # DAG: must complete before this artifact
    description: |
      What this artifact captures + how to fill it in.

apply:
  gate: <artifact-id>          # which artifact gates implementation
  progress: <file-path>        # which file tracks progress (checkboxes)
  description: |
    Free-form description of the gating contract.
```

The two scaffold examples shipped in v1.13.0:

- `schemas/minimalist/` — 2-artifact (specs + tasks), low-ceremony, suitable for solo / hobby / spike work
- `schemas/kaizen-default/` — 8-artifact full kaizen workflow as declarative yaml (mirrors the existing `workflow-routing` routines)

## How agents would consume schemas

A schema-aware workflow runner:

1. **Load**: read `schema.yaml`, parse `artifacts[]` + `apply` block.
2. **Order**: topological sort artifacts by `requires` to determine execution order.
3. **For each artifact in order**:
   a. Check if its output (per `generates`) already exists + is complete.
   b. If not: read its template (if any), prompt the agent to fill it.
   c. After completion: mark the artifact as done; recurse to next.
4. **Apply gate**: check `apply.gate` artifact is complete before allowing implementation.
5. **Progress tracking**: the file at `apply.progress` is the single source of truth for done/not-done.

`kaizen:agent-brief` would document this contract so fresh agents understand it without re-deriving from source.

## What v1.13.0 ships (the scaffold)

- `schemas/minimalist/{schema.yaml,templates/specs/spec.md,templates/tasks/tasks.md}` — minimal example.
- `schemas/kaizen-default/schema.yaml` — re-statement of the existing 8-stage routine as a declarative artifact list. NOT YET wired into the runtime.
- This doc, explaining the migration plan.

## What v1.14.0+ would add (the runtime)

The actual loader + executor. Sketch:

```python
# scripts/workflow_runner.py — proposed for v1.14.0
import yaml
from pathlib import Path

def resolve_schema(name: str) -> Path:
    for base in [
        Path.cwd() / ".workflow" / "schemas",
        Path.home() / ".claude" / "kaizen-schemas",
        plugin_schemas_dir(),
    ]:
        candidate = base / name / "schema.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"schema {name!r} not found")

def load(name: str) -> dict:
    return yaml.safe_load(resolve_schema(name).read_text())

def topo_order(artifacts: list[dict]) -> list[dict]:
    """Return artifacts in execution order respecting `requires`."""
    # Kahn's algorithm, ~30 LOC
    ...

def run(schema_name: str, agent_loop: Callable):
    schema = load(schema_name)
    for artifact in topo_order(schema["artifacts"]):
        if not output_complete(artifact):
            template = (resolve_schema(schema_name).parent / artifact["template"]).read_text() if artifact.get("template") else ""
            agent_loop(prompt=artifact["description"], template=template)
        mark_done(artifact)
    enforce_apply_gate(schema["apply"])
```

## Migration risk

The existing `workflow-routing` skill is heavily integrated:

- `.workflow/state.json` tracks routine state — must be backward-compatible.
- 6 hardcoded routines have stage-specific prompts in `routines.md` — must be transcribed into per-artifact `description` blocks.
- `/workflow` slash command surface must keep working through the transition.

Approach: **strangler-fig migration**. Ship the loader as opt-in (`/workflow --schema <name>`), with the existing hardcoded path as default. Migrate routines one-by-one. Once all 6 hardcoded routines have schema equivalents, flip the default. Drop the bash routines.

Multi-commit plan, conservatively:

1. v1.13.0 — ship scaffold + research doc (THIS).
2. v1.14.0 — ship loader, wire `--schema` flag, migrate `minimalist`.
3. v1.15.0 — migrate `kaizen-default` (mirror of current `harden` etc.).
4. v1.16.0 — migrate remaining 5 hardcoded routines to schema form.
5. v1.17.0 — make schema-loader the default; deprecate the bash routine path.
6. v2.0.0 — remove the legacy bash path.

Each step is independently shippable + reversible.

## Why NOT just port everything in v1.13.0

- Workflow-routing is the most-used kaizen feature for multi-step work. A breaking change there bricks active users.
- The yaml schema format will probably evolve once it sees real use; locking it in pre-migration is premature commitment.
- OpenSpec itself is recent (Feb 2026); we benefit from watching the ecosystem first.

## Open questions for v1.14.0 design

- Should `requires:` permit OR-groups (`requires: [[a, b], c]` = "either a or b, plus c")?
- Should artifacts have `optional: true` to skip without blocking the DAG?
- How do we handle parallel artifacts (no dependency between them)? Top-of-mind: `asyncio.gather` over independent artifacts after topo sort identifies levels.
- Should `apply.gate` support multiple gates (`gate: [validate, security-review]`)?

To be resolved with empirical use of the v1.13.0 scaffold before v1.14.0 lands.

---

## Cross-references

- `kaizen:workflow-routing` — current hardcoded routine system; target of the migration.
- `kaizen:writing-plans` — plan-file authoring discipline (input to the `plan` artifact).
- `kaizen:agent-brief` — fresh-agent orientation; will be updated in v1.14.0 to describe schema-driven workflows.
- `docs/sdd-ssot-research.md` — broader schema-driven design research; this doc is one application of that thinking.
