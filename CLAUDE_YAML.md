# CLAUDE_YAML.md — kaizen-md project orientation (YAML form)
#
# Sibling of CLAUDE.md. Same content, parseable shape. When prose and
# YAML drift, CLAUDE.md wins for humans; this file wins for tooling.
# Rule bodies still live in `~/.claude/.kaizen/brain/Notes/`; this is
# the project orientation handle, not a rulebook (see
# [[Notes/pref-claude-md-is-rulebook-not-state]]).

project:
  name: kaizen-md
  type: claude-code-plugin-marketplace
  purpose: |
    .claude-plugin/marketplace.json bundles plugins. plugins/kaizen/
    is the only plugin-original tree (everything else is vendored).
    No build step — shell scripts + Python + markdown. "Building"
    means running the test pipeline.
  layout:
    plugin_original: plugins/kaizen/
    vendored: ["plugins/*-lsp/"]            # redistributed verbatim from claude-plugins-official
    canonical_edit_path: ~/workspace/kaizen-md/
    forbidden_edit_path: ~/.claude/local-marketplaces/kaizen-md/   # the symlink — never edit through it

commands:
  full_test_suite:
    invocation: kaizen-tests
    description: "Unified Python suite (unittest / pytest auto-style, parallel)."
  single_test_file:
    invocation: 'kaizen-tests --pattern "test_brain*"'
  bench:
    invocation: "kaizen-tests bench --top-n 10"
    description: "Find slow test files."
  smoke_pipeline:
    invocation: "bash plugins/kaizen/skills/workflow/scripts/test-pipeline.sh"
    description: "TAP-style end-to-end; sandboxes in /tmp/gwtest-*"
  health_diagnostic:
    invocation: "bash plugins/kaizen/skills/workflow/scripts/health.sh"
  install_plugin_into_repo:
    invocation: "bash plugins/kaizen/skills/workflow/scripts/install.sh"
    note: "Dogfooding — sets local core.hooksPath."
  lint:
    invocation: "ruff check plugins/kaizen/skills/workflow/scripts/"

ci:
  workflow_file: .github/workflows/test.yml
  runners: [ubuntu-latest, macos-latest]
  checks:
    - "bash -n on every shell script"
    - "ast.parse on every Python script"
    - "JSON validity on every manifest"
    - "GNU-only-utility ban — see [[Notes/pref-cross-platform-no-gnu-only]]"

editing_rules:
  full_body: "[[Notes/pref-kaizen-plugin-dev]]"
  required_before_any_plugin_original_change:
    - "Load Skill(plugin-development) in full"
    - "Run: python3 plugins/kaizen/skills/plugin-development/scripts/validate.py --staged"
  forbidden:
    - rule: "Edit through ~/.claude/local-marketplaces/kaizen-md/ symlink"
      why: "Canonical edit path is ~/workspace/kaizen-md/"
    - rule: "Edit any vendored skill"
      ssot:  "skills/iron-laws/domain/iron-laws.yaml::no-modify-vendored + ATTRIBUTIONS.md"

subagent_dispatch:
  full_body: "[[Notes/pref-subagent-dispatch-safe-defaults]]"
  recommendations:
    multi_phase_tdd_in_isolated_worktree:
      agent: kaizen:kaizen-implementer
      why: "Bash surface is pattern-restricted to block destructive git ops."
    multi_commit_general:
      agent: general-purpose
      strict_mode_knob: "touch ~/.claude/.kaizen/strict"

architecture:
  dogfood:
    description: |
      The plugin eats its own dogfood. Committing in this repo fires
      the plugin's own pre-commit + commit-msg gate (installed via
      local core.hooksPath = .kaizen/hooks).
    consequences_per_commit:
      - "Conventional Commits subject required (feat / fix / refactor / docs / chore / ...)"
      - "Structural change ships a row in .kaizen/workflow/progress.md in the same commit"
      - "git rm blocked unless KAIZEN_ALLOW_DELETE=1"
      - "CLAUDE.md / README.md must not contain commit SHAs, dates, or LOC counts"
      - "Micro work tracked in .kaizen/workflow/backlog.json via backlog.py"
      - "Work spanning ≥16 files → plans/<date>-<slug>.md plan file"

  canonical_feature_shape:
    ssot: skills/plugin-development/domain/feature-shape.yaml
    note: "yaml wins; SKILL.md prose explains."
    full_body: "[[Notes/pref-kaizen-plugin-dev]]"
    slot_categories:
      - skill_body
      - skill_domain_yaml
      - skill_domain_schemas
      - skill_scripts
      - private_core              # _<feature>.py
      - public_cli                # <feature>.py
      - indexer
      - specialized_flows         # <feature>_<op>.py
      - mcp_server                # <feature>_mcp.py
      - hooks                     # hooks/claude/<feature>-*.sh
      - slash_command             # commands/<feature>.md
      - bin_wrapper               # bin/kaizen-<feature>*
      - tests                     # tests/test_<feature>*.py

  onion_ddd:
    full_body: "[[Notes/pref-onion-architecture-strict]]"
    layer_to_path:
      domain:      "skills/<feature>/domain/      (pure yaml + JSON Schemas)"
      application: "skills/<feature>/application/ (loaders + codegen)"
      adapters:    "skills/<feature>/scripts/     (shell + MCP wrappers)"
      references:  "skills/<feature>/references/  (generated; regen via application/codegen.py)"
    rule: "inward-only deps"

  iron_laws:
    ssot: skills/iron-laws/domain/iron-laws.yaml
    full_body: "[[Notes/pref-coding-skills-strict]]"
    inspect: kaizen-iron-laws list
    check_staged: kaizen-iron-laws check --staged
    hard_laws_sample:
      - bin-wrapper-per-cli
      - plugin-manifest-permissions
      - hook-bypass-knob
      - sandbox-tests

  cross_platform:
    full_body: "[[Notes/pref-cross-platform-no-gnu-only]]"
    targets: [linux-gnu, macos-bsd]

  workflow_namespace:
    description: "Per-file ownership inside .kaizen/workflow/"
    ownership:
      "backlog.{json,md}": plugin
      "state.json":        workflow_routing_engine
      "snapshot.md":       workflow_routing_engine
      "progress.md":       architecture_log

  centralized_trio:
    description: |
      Configuration + paths SSOT. When prose and these files disagree,
      code wins.
    files:
      defaults:
        path: skills/workflow/scripts/config.py
        owns: "PLUGIN ▸ DEFAULTS constants + .kaizen.toml reader"
      paths_python:
        path: skills/workflow/scripts/_paths.py
        owns: "every KAIZEN_*_DIR resolver"
      paths_shell:
        path: skills/workflow/scripts/_paths.sh
        owns: "bash-source-able mirror of _paths.py"
    resolution_order_low_to_high:
      - "config.py::PLUGIN_DEFAULTS"
      - "_paths.{py,sh} env-overridable paths"
      - "<repo>/.kaizen.toml"
    inspect:
      defaults: "kaizen-config --defaults"
      one_value: "kaizen-config <key>"
      shell_env: "source plugins/kaizen/skills/workflow/scripts/_paths.sh && env | grep KAIZEN_"
    common_env_knobs:
      - KAIZEN_DIR
      - KAIZEN_HANDOFF_DIR
      - KAIZEN_BACKUP_DIR
      - KAIZEN_DXM_DIR
      - KAIZEN_INBOX_DIR
      - "KAIZEN_<FEATURE>_DISABLE"

  consolidation_patterns:
    full_body: "[[Notes/pref-kaizen-consolidation-patterns]]"
    current_snapshot: .kaizen/superpowers/architecture-snapshot.md
    canonical_shapes:
      - lens-manifest
      - decision-rubric
      - plain-config
      - rule-catalog
    audit: kaizen-schema-coverage

  coverage_axes:
    full_body: "[[Notes/pref-coverage-axis-naming]]"
    naming_convention: "<thing>-coverage"
    integration: "register as own SUB_GATES key in kaizen-gatekeeper"

  jsonl_indexed_deliverables:
    full_body: "[[Notes/pref-jsonl-indexed-deliverables]]"
    threshold: "≥30 structured entries"
    rule: "Ship paired .md + .jsonl so consumers can jq the slice without whole-file Read"

audit_surface:
  one_command_sanity:
    - "kaizen-gatekeeper check --all"
    - "kaizen-token-bloat scan"
    - "kaizen-coverage gaps"
    - "kaizen-schema-coverage gaps"
    - "kaizen-name-quality gaps"
  automation:
    SessionEnd: refreshes_token_bloat_cache
    pre_commit_gate: runs_kaizen_gatekeeper
    via_gatekeeper: kaizen_schema_coverage_surfaced

what_does_not_live_here:
  full_body: "[[Notes/pref-claude-md-is-rulebook-not-state]]"
  do_not_write_here:
    - "Long-form rule bodies — write a brain Note + link from here"
    - "Cluster snapshots / counts that drift — use .kaizen/superpowers/architecture-snapshot.md"
    - "Volatile data (SHAs, dates, LOC counts) — use git notes / progress.md / CHANGELOG.md / self-checking commands"
