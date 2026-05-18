# docs/superpowers/ — session-bundle layout

Each session's artifacts (specs / plans / brainstorms / notes) live
together in ONE date+project+sid folder. Templates and durable kits
sit outside session folders.

## Layout

```
docs/superpowers/
├── README.md                                ← this file
├── <YYYY-MM-DD>-<project>-<sid8>/           ← one session bundle
│   ├── README.md                             ← per-bundle scope note
│   ├── spec-<topic>.md
│   ├── plan-<topic>.md
│   ├── brainstorm-<topic>.md
│   └── notes-<topic>.md
├── <YYYY-MM-DD>-<project>/                  ← no-sid form (pre-convention)
└── templates/                                ← durable, cross-session
    ├── chunk-plan-template.md
    ├── parallel-branches/                    ← kit (11 docs + 8 schemas)
    └── observer/                             ← kit (event/rule schemas)
```

## Folder name grammar

`<YYYY-MM-DD>-<project-kebab>-<sid8>`

- **date** — UTC `YYYY-MM-DD`
- **project** — kebab-cased repo / arc name (e.g. `kaizen-md`,
  `clever-lama-mcp`)
- **sid8** — first 8 hex of the Claude Code session UUID; OMIT for
  legacy / undated work

Multi-project sessions create one folder per project (e.g. session
`6ebbb7cb` touched both repos → `2026-05-18-kaizen-md-6ebbb7cb/` +
`2026-05-18-clever-lama-mcp-6ebbb7cb/`).

## CLI — `kaizen-bundle`

```bash
kaizen-bundle init   --date 2026-05-18 --project kaizen-md --sid <uuid>
kaizen-bundle list   [--project <name>] [--json]
kaizen-bundle path   --date 2026-05-18 --project kaizen-md --sid <uuid>
kaizen-bundle add    --file <src> --date ... --project ... --sid ...
```

`init` is idempotent (re-run safe). `path` is pure compute (no I/O).
`add` moves a file via filesystem-rename (preserves content; git mv
done by caller when version control is desired).

Sink root: `<repo>/docs/superpowers/` by default; override with
`KAIZEN_SUPERPOWERS_DIR=...` for tests / relocation.

## Design contract

Matches the rest of the kaizen sinks (kaizen-progress / kaizen-learn /
kaizen-observer-events):

- **Programmable** — `bundle_folder_name`, `bundle_path` are pure
  callables; CLI is a thin shell
- **Reproducible** — folder name is a pure function of (date, project, sid)
- **Consistent** — env-overridable root; --json everywhere; exit 0 on success
- **Deterministic** — no randomness; no wall-clock peek
- **Reusable** — works for any multi-project bundle layout

## Migration history

The pre-convention `specs/` and `plans/` flat directories were
collapsed into session bundles 2026-05-18 (`<session-id>`):

- `specs/2026-05-15-kaizen-mcp-gateway-design.md` →
  `2026-05-15-kaizen-md/spec-mcp-gateway-design.md`
- `specs/2026-05-18-*.md` →
  `2026-05-18-kaizen-md-6ebbb7cb/spec-*.md`
- `plans/2026-05-18-*.md` →
  `2026-05-18-kaizen-md-6ebbb7cb/plan-*.md`

`templates/parallel-branches/` and `templates/observer/` stay outside
bundles — they're long-lived reference, not session-specific.

The root-level `plans/` directory (`<repo>/plans/`, not under
`docs/superpowers/`) holds working notes that haven't been bundled
yet. Migration of those into session-bundles is future work.
