# Kaizen JSON Schemas

Formal JSON Schema (draft 2020-12) definitions for kaizen's main data shapes. Mirrors of the dataclasses in `skills/kaizen/scripts/schemas.py` (the runtime SSOT). Consumed by editors / IDEs / external validators (`ajv`, `jsonschema`, yaml-language-server).

## Inventory

| Schema                          | Mirrors dataclass             | On-disk location                                   |
|---------------------------------|-------------------------------|----------------------------------------------------|
| `workflow.schema.json`          | `WorkflowSchema` + nested     | `schemas/<name>/schema.yaml`                       |
| `workflow-state.schema.json`    | `WorkflowState`               | `<repo>/.workflow/state.json`                      |
| `backlog.schema.json`           | `BacklogStore` + `BacklogItem` | `<repo>/.workflow/backlog.json`                    |
| `knowledge-item.schema.json`    | `KnowledgeItem`               | `~/.claude/.kaizen-knowledge/index.db` rows        |
| `brain-rule.schema.json`        | `KaizenBrainRule`             | `~/.claude/brain/Notes/*.md` frontmatter           |
| `agent-formatting.schema.json`  | `AgentFormattingSchema`       | `skills/agent-formatting/SKILL.md` embedded block  |

## Wiring into editors

For VSCode + YAML extension, add to project / user settings:

```jsonc
"yaml.schemas": {
  "./assets/schemas/workflow.schema.json": [
    "schemas/*/schema.yaml",
    ".workflow/schemas/*/schema.yaml"
  ]
}
```

For inline-per-file declarations, the YAML files already carry a `# yaml-language-server: $schema=...` directive at the top — most YAML extensions pick that up automatically.

For ajv (Node):

```javascript
import Ajv from "ajv";
import addFormats from "ajv-formats";
import workflowSchema from "./assets/schemas/workflow.schema.json" assert { type: "json" };
const ajv = new Ajv({ allErrors: true });
addFormats(ajv);
const validate = ajv.compile(workflowSchema);
const ok = validate(yamlParsedDoc);
```

For Python (`jsonschema` package, optional dep):

```python
import json, jsonschema
with open("assets/schemas/backlog.schema.json") as f: schema = json.load(f)
with open(".workflow/backlog.json") as f: doc = json.load(f)
jsonschema.validate(doc, schema)
```

## Keeping in sync with `schemas.py`

The dataclasses in `skills/kaizen/scripts/schemas.py` are the **runtime** SSOT — scripts construct + validate via them. The JSON Schemas here are the **tooling** SSOT — IDE validation + external linters. Keep both up to date when adding fields:

1. Add the field to the dataclass + `_self_test()` round-trip.
2. Add the field to the matching JSON Schema (mind required vs optional).
3. Update the JSON Schema's `description` if behaviour changed.

No auto-generation yet. Keep the two layers small enough to maintain by hand; a future v1.x might add a `schemas-export` script to generate JSON from dataclasses.
