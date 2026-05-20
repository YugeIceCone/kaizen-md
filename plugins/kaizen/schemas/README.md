# Kaizen JSON Schemas

Formal JSON Schema (draft 2020-12) definitions for kaizen's main data shapes. Consumed by editors / IDEs / external validators (`ajv`, `jsonschema`, yaml-language-server) AND by the runtime gate (the `kaizen-schema` CLI walks them for validation).

## Layout — the per-domain nesting convention

Every domain owns a folder under `schemas/`. Inside each domain folder, the YAMLs that hold runtime data live at the top level, and the JSON Schemas that validate them live in a child `schemas/` subfolder. The double-`schemas` in the path is deliberate:

```
schemas/                           ← kaizen domain root (the OUTER schemas/)
├── README.md                      ← this file
├── <domain>/                      ← one folder per domain (workflow, handoff, iron-laws, …)
│   ├── <domain>.yaml              ← the runtime YAML (rubrics / configs / rule catalogs)
│   ├── <other>.yaml               ← additional domain-owned YAMLs (e.g. handoff/auto-config.yaml)
│   ├── schema.yaml                ← (workflow-routine schemas only) the routine DAG
│   └── schemas/                   ← JSON Schemas that validate the YAMLs above (the INNER schemas/)
│       ├── <domain>.schema.json
│       └── <other>.schema.json
└── …
```

So `schemas/workflow/schemas/workflow-config.schema.json` reads as:

- outer `schemas/` — kaizen's domain root
- `workflow/` — the workflow domain
- inner `schemas/` — the JSON Schemas folder for that domain
- `workflow-config.schema.json` — validates `~/.claude/.kaizen/workflow-global.json` and `.kaizen/workflow.json`

The naming is awkward at the path-segment level but consistent across all 22 domains. Each domain is self-contained: data + validators co-located, no cross-domain reach into `assets/schemas/` or top-level orphan schemas.

## Domain inventory (selection)

| Domain               | Runtime YAML(s)                         | Validators                                              |
|----------------------|-----------------------------------------|---------------------------------------------------------|
| `workflow/`          | `routines.yaml` + routine `schema.yaml` | `schemas/workflow-config.schema.json`, etc.             |
| `handoff/`           | `auto-config.yaml`, `auto-rubric.yaml`  | `schemas/auto-config.schema.json` + rubric/event schemas |
| `iron-laws/`         | `iron-laws.yaml`                        | `schemas/iron-laws.schema.json`                         |
| `onion-tdd-strict/`  | `schema.yaml`, `audit-rubric.yaml`, …   | `schemas/*.schema.json` (one per yaml)                  |
| `brain/`             | brain Persona + Notes schema            | `schemas/brain-rule.schema.json`                        |
| `backlog/`           | `backlog.schema.json` reference         | (validators only)                                       |

Run `find schemas -maxdepth 2 -name 'schemas' -type d` for the live list (22 domains).

## Wiring into editors

For VSCode + YAML extension, add to project / user settings:

```jsonc
"yaml.schemas": {
  "./schemas/workflow.schema.json": [
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
import workflowSchema from "./schemas/workflow.schema.json" assert { type: "json" };
const ajv = new Ajv({ allErrors: true });
addFormats(ajv);
const validate = ajv.compile(workflowSchema);
const ok = validate(yamlParsedDoc);
```

For Python (`jsonschema` package, optional dep):

```python
import json, jsonschema
with open("schemas/backlog.schema.json") as f: schema = json.load(f)
with open(".workflow/backlog.json") as f: doc = json.load(f)
jsonschema.validate(doc, schema)
```

## Keeping in sync with `schemas.py`

The dataclasses in `skills/workflow/scripts/schemas.py` are the **runtime** SSOT — scripts construct + validate via them. The JSON Schemas here are the **tooling** SSOT — IDE validation + external linters. Keep both up to date when adding fields:

1. Add the field to the dataclass + `_self_test()` round-trip.
2. Add the field to the matching JSON Schema (mind required vs optional).
3. Update the JSON Schema's `description` if behaviour changed.

No auto-generation yet. Keep the two layers small enough to maintain by hand; a future v1.x might add a `schemas-export` script to generate JSON from dataclasses.
