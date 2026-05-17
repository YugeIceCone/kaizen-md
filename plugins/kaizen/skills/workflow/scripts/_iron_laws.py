#!/usr/bin/env python3
"""iron-laws — checker core.

One `check_<name>(ctx)` function per `enforcement: auto` iron law, plus
the `CHECKS` dispatch registry and `run_checks()`. Each check translates
its law's `detect:` predicate (in `skills/iron-laws/domain/iron-laws.yaml`)
into a grep / AST / git-diff / filesystem test and returns `Finding`s.

The registry (`skills/iron-laws/domain/iron-laws.yaml`) is the single
source of truth — this module *references* it via the iron-laws skill's
`_loader`; it does not duplicate law metadata.

Consumed by: `iron_laws.py` (CLI), `iron_laws_mcp.py` (MCP), and the
plugin-development `validate.py` + the pre-commit gate.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Reference the iron-laws skill's loader — the SSOT entry point.
_SKILLS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_SKILLS_DIR / "iron-laws" / "application"))
import _loader  # noqa: E402

# Vendored skill dirs — never plugin-original (mirrors iron-laws.yaml::no-modify-vendored).
# Currently empty: the original coding-skills / superpowers / claude-code-skills /
# remember bundles were retired from active upstream-tracking on 2026-05-17 after
# extensive kaizen-local alterations. They are now plugin-original derivatives;
# original-author attribution preserved in ATTRIBUTIONS.md. Add to this set only
# when wiring a NEW upstream-tracked skill (with active bundle-refresh discipline).
VENDORED: set[str] = set()
ADDITIVE_EVENTS = {"SubagentStop", "SessionEnd", "Notification"}
HEAVY_DEPS = ("torch", "transformers", "tree_sitter", "sentence_transformers")


@dataclass
class Finding:
    law_id: str
    severity: str          # hard | soft
    message: str
    path: str = ""
    detail: str = ""


@dataclass
class CheckContext:
    repo_root: Path
    plugin_root: Path
    scope: str                       # "staged" | "all"
    changed: list[str] = field(default_factory=list)  # added+modified, repo-relative
    added: list[str] = field(default_factory=list)    # added-only, repo-relative

    def in_scope(self, rel_path: str) -> bool:
        return self.scope == "all" or rel_path in self.changed

    def rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.repo_root))
        except ValueError:
            return str(p)

    def plugin_files(self, glob: str) -> list[Path]:
        """Plugin files matching a glob, filtered to scope, that exist."""
        return [
            p for p in sorted(self.plugin_root.glob(glob))
            if p.is_file() and self.in_scope(self.rel(p))
        ]

    def changed_under(self, *prefixes: str) -> list[str]:
        """Changed (added+modified) repo-relative paths under any prefix."""
        return [c for c in self.changed if any(c.startswith(p) for p in prefixes)]

    def added_under(self, *prefixes: str) -> list[str]:
        """Newly-added repo-relative paths under any prefix. Use this for
        'new file' laws — a modified file is not a new file."""
        src = self.added if self.scope == "staged" else self.changed
        return [c for c in src if any(c.startswith(p) for p in prefixes)]


# ─── auto-law checks ─────────────────────────────────────────────────────

def check_no_modify_vendored(ctx: CheckContext) -> list[Finding]:
    out = []
    for c in ctx.changed_under("plugins/kaizen/skills/"):
        parts = c.split("/")
        if len(parts) > 4 and parts[3] in VENDORED:
            out.append(Finding(
                "no-modify-vendored", "hard",
                f"vendored skill modified: {parts[3]}", c,
                "patch upstream first, then bundle-refresh"))
    return out


def check_node_flow_for_multi_step(ctx: CheckContext) -> list[Finding]:
    out = []
    for p in ctx.plugin_files("skills/workflow/scripts/*.py"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        if text.count("asyncio.gather") > 1 and "AsyncParallelBatchNode" not in text:
            out.append(Finding(
                "node-flow-for-multi-step", "soft",
                "multiple asyncio.gather calls without AsyncParallelBatchNode",
                ctx.rel(p)))
    return out


def check_lazy_heavy_deps(ctx: CheckContext) -> list[Finding]:
    pat = re.compile(rf"^(?:import|from) (?:{'|'.join(HEAVY_DEPS)})\b")
    out = []
    for p in ctx.plugin_files("skills/workflow/scripts/*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if pat.match(line):  # column-0 = top-level, not inside try/except
                out.append(Finding(
                    "lazy-heavy-deps", "soft",
                    f"top-level heavy import: {line.strip()}", ctx.rel(p),
                    f"line {i} — wrap in try/except + is_available()"))
    return out


def check_sandbox_tests(ctx: CheckContext) -> list[Finding]:
    out = []
    for p in ctx.plugin_files("tests/test_*.py"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        touches_home = any(
            s in text for s in ("Path.home()", "expanduser(\"~", "expanduser('~", "~/.claude")
        )
        if touches_home and "KAIZEN_" not in text:
            out.append(Finding(
                "sandbox-tests", "hard",
                "test touches ~/.claude / home without a KAIZEN_<X>_PATH override",
                ctx.rel(p)))
    return out


_MAIN_BLOCK = re.compile(r"""if\s+__name__\s*==\s*["']__main__["']""")


def _has_argparse_main(text: str) -> bool:
    """A real argparse-based CLI entry point — a `__main__` block AND
    `ArgumentParser` usage. Deliberately strict: a bare `import argparse`
    or a `__main__` block used only for a smoke test must not trip it."""
    return bool(_MAIN_BLOCK.search(text)) and "ArgumentParser" in text


def _wrapper_name(stem: str) -> str:
    """demo.py -> kaizen-demo ; brain_index.py -> kaizen-brain-index.

    Idempotency: a stem already starting with ``kaizen_`` (e.g.
    ``kaizen_write.py``) maps to ``kaizen-write``, NOT
    ``kaizen-kaizen-write``. Double-prefix would force awkward
    wrappers like ``kaizen-kaizen-write`` alongside the natural
    ``kaizen-write``. The convention "every wrapper starts with
    kaizen-" still holds because the stem already provides it.
    """
    clean = stem.lstrip("_")
    if clean.startswith("kaizen_") or clean == "kaizen":
        return clean.replace("_", "-")
    return "kaizen-" + clean.replace("_", "-")


_CONSOLIDATED_PARENT = re.compile(
    r"^#\s*consolidated-cli-parent:\s*(\S+)\s*$", re.MULTILINE
)


def check_bin_wrapper_per_cli(ctx: CheckContext) -> list[Finding]:
    """Each `scripts/<name>.py` argparse-main script needs a matching
    `bin/kaizen-<name>` wrapper — UNLESS it declares itself a member
    of a consolidated multi-verb CLI via a header directive::

        # consolidated-cli-parent: brain

    Then the bin wrapper requirement transfers to the parent
    (`bin/kaizen-brain`), and the sub-script doesn't need its own.
    Lets brain_audit/evolve/index/promote/migrate live under
    `kaizen-brain <verb>` without 5 separate bin wrappers.
    """
    out = []
    for p in ctx.plugin_files("skills/workflow/scripts/*.py"):
        if p.name.startswith("_"):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if not _has_argparse_main(text):
            continue
        # Consolidated-CLI exemption: header directive transfers the
        # wrapper requirement to a parent script's bin.
        m = _CONSOLIDATED_PARENT.search(text)
        if m:
            parent_wrapper = ctx.plugin_root / "bin" / _wrapper_name(m.group(1))
            if parent_wrapper.exists():
                continue   # parent's wrapper covers this sub-CLI
            out.append(Finding(
                "bin-wrapper-per-cli", "hard",
                f"CLI script {p.name} declares "
                f"`consolidated-cli-parent: {m.group(1)}` but "
                f"bin/{parent_wrapper.name} doesn't exist",
                ctx.rel(p)))
            continue
        wrapper = ctx.plugin_root / "bin" / _wrapper_name(p.stem)
        if not wrapper.exists():
            out.append(Finding(
                "bin-wrapper-per-cli", "hard",
                f"CLI script {p.name} has no bin/{_wrapper_name(p.stem)} wrapper",
                ctx.rel(p)))
    return out


def check_plugin_manifest_permissions(ctx: CheckContext) -> list[Finding]:
    # The law targets NEW invocable surfaces: skills/workflow/scripts/*.py
    # OR hooks/claude/*.sh. NOT scripts/*.sh (infra: pre-commit.sh, lib.sh)
    # and NOT `_`-prefixed modules (imported, never Bash-invoked).
    scripts_py = [
        c for c in ctx.added_under("plugins/kaizen/skills/workflow/scripts/")
        if c.endswith(".py") and not Path(c).name.startswith("_")
    ]
    hook_sh = [
        c for c in ctx.added_under("plugins/kaizen/hooks/claude/")
        if c.endswith(".sh") and not Path(c).name.startswith("_")
    ]
    new = scripts_py + hook_sh
    if not new:
        return []
    pj = ctx.plugin_root / ".claude-plugin" / "plugin.json"
    allow = []
    if pj.exists():
        try:
            allow = json.loads(pj.read_text()).get("permissions", {}).get("allow", [])
        except json.JSONDecodeError:
            allow = []
    blob = "\n".join(allow)
    out = []
    for c in new:
        base = Path(c).name
        if base not in blob:
            out.append(Finding(
                "plugin-manifest-permissions", "hard",
                f"new {base} has no matching plugin.json permission entry", c))
    return out


def check_hook_bypass_knob(ctx: CheckContext) -> list[Finding]:
    out = []
    for p in ctx.plugin_files("hooks/claude/*.sh"):
        if p.name.startswith("_"):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if not ("KAIZEN_" in text and "_DISABLE" in text):
            out.append(Finding(
                "hook-bypass-knob", "hard",
                f"hook {p.name} missing a KAIZEN_<FEATURE>_DISABLE bypass guard",
                ctx.rel(p)))
    return out


_SHA_NEAR_COMMIT = re.compile(
    r"\b(?:commit|sha|landed in|rev)\b[^\n]{0,40}\b[0-9a-f]{7,40}\b", re.I)
_ISO_DATE = re.compile(r"\b20\d\d-[01]\d-[0-3]\d\b")
_LOC_COUNT = re.compile(r"\b\d[\d,]*\s*(?:LOC|lines of code)\b", re.I)


def check_claude_md_no_volatile_data(ctx: CheckContext) -> list[Finding]:
    out = []
    candidates = [
        ctx.repo_root / "CLAUDE.md",
        ctx.repo_root / "README.md",
        ctx.plugin_root / "README.md",
    ]
    for p in candidates:
        if not p.is_file() or not ctx.in_scope(ctx.rel(p)):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        hits = []
        if _SHA_NEAR_COMMIT.search(text):
            hits.append("commit sha")
        if _ISO_DATE.search(text):
            hits.append("date")
        if _LOC_COUNT.search(text):
            hits.append("LOC count")
        if hits:
            out.append(Finding(
                "claude-md-no-volatile-data", "hard",
                f"{p.name} contains volatile data ({', '.join(hits)})", ctx.rel(p),
                "move to CHANGELOG / git log / progress.md"))
    return out


def check_paired_tests(ctx: CheckContext) -> list[Finding]:
    new = [c for c in ctx.added_under("plugins/kaizen/skills/workflow/scripts/")
           if c.endswith(".py")]
    out = []
    for c in new:
        stem = Path(c).stem.lstrip("_")
        has_test = (
            list((ctx.plugin_root / "tests").glob(f"test_{stem}*.py")) or
            any(f"test_{stem}" in ch for ch in ctx.changed)
        )
        if not has_test:
            out.append(Finding(
                "paired-tests", "soft",
                f"new script {Path(c).name} has no paired tests/test_{stem}*.py", c))
    return out


def check_bin_wrapper_per_cli_strict(ctx: CheckContext) -> list[Finding]:
    new = [c for c in ctx.added_under("plugins/kaizen/skills/workflow/scripts/")
           if c.endswith(".py") and not Path(c).name.startswith("_")]
    out = []
    for c in new:
        p = ctx.repo_root / c
        if not p.exists() or not _has_argparse_main(
                p.read_text(encoding="utf-8", errors="ignore")):
            continue
        wname = _wrapper_name(Path(c).stem)
        wrapper = ctx.plugin_root / "bin" / wname
        in_changed = any(ch.endswith(f"bin/{wname}") for ch in ctx.changed)
        if not (wrapper.exists() or in_changed):
            out.append(Finding(
                "bin-wrapper-per-cli-strict", "hard",
                f"new CLI script {Path(c).name} ships without bin/{wname} in the same commit",
                c))
    return out


_ARGS_DEFAULT_SPACE = re.compile(r"\$\{ARGUMENTS:-[^}]* [^}]*\}")


def check_slash_command_args_no_default_spaces(ctx: CheckContext) -> list[Finding]:
    out = []
    for p in ctx.plugin_files("commands/*.md"):
        if _ARGS_DEFAULT_SPACE.search(p.read_text(encoding="utf-8", errors="ignore")):
            out.append(Finding(
                "slash-command-args-no-default-spaces", "hard",
                f"{p.name} uses ${{ARGUMENTS:-<default with spaces>}}", ctx.rel(p),
                "give the script a no-arg default; pass bare $ARGUMENTS"))
    return out


def check_hooks_json_additive_event_multi_command(ctx: CheckContext) -> list[Finding]:
    hj = ctx.plugin_root / "hooks" / "hooks.json"
    if not hj.is_file() or not ctx.in_scope(ctx.rel(hj)):
        return []
    try:
        data = json.loads(hj.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    events = data.get("hooks", data)
    out = []
    for event in ADDITIVE_EVENTS:
        blocks = events.get(event) or []
        star = [b for b in blocks if isinstance(b, dict) and b.get("matcher", "*") == "*"]
        if len(star) > 1:
            out.append(Finding(
                "hooks-json-additive-event-multi-command", "soft",
                f"hooks.json::{event} has {len(star)} matcher='*' blocks — append within one",
                ctx.rel(hj)))
    return out


_EXEC_MARKER = re.compile(r"![`]")


def check_skill_md_no_exec_markers(ctx: CheckContext) -> list[Finding]:
    out = []
    for p in ctx.plugin_files("skills/*/SKILL.md"):
        if _EXEC_MARKER.search(p.read_text(encoding="utf-8", errors="ignore")):
            out.append(Finding(
                "skill-md-no-exec-markers", "soft",
                f"{ctx.rel(p)} contains a !-backtick exec marker", ctx.rel(p),
                "the Skill tool runs these at load time — use prose / indented blocks"))
    return out


def check_skill_md_no_external_script_paths(ctx: CheckContext) -> list[Finding]:
    out = []
    for p in ctx.plugin_files("skills/*/SKILL.md"):
        in_bash = False  # the law targets bash blocks, not prose that mentions a path
        for i, line in enumerate(
                p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("```"):
                lang = stripped[3:].strip().lower()
                in_bash = lang in ("bash", "sh", "shell")
                continue
            if not in_bash or "if [ -f" in line:
                continue
            if "~/.claude/scripts/" in line or ".venv/bin/python" in line:
                out.append(Finding(
                    "skill-md-no-external-script-paths", "soft",
                    f"{ctx.rel(p)} invokes an unshipped external script path",
                    ctx.rel(p), f"line {i}: {line.strip()}"))
    return out


_PY_INVOKE_RE = re.compile(
    r'python3\s+(?:"[^"]*?\$[A-Z_]+[^"]*?/|[^\s"\']*/)?([a-zA-Z_][a-zA-Z0-9_]*\.py)'
)
_TRACE_USAGE_RE = re.compile(
    r'(_trace\.sh|trace\.py event|trace\.append_event|import trace'
    r'|_dxm_emit\.emit_event|import _dxm_emit)'
)


def _hook_traces_via_helper(text: str, ctx: CheckContext) -> bool:
    """A hook may delegate tracing to a python helper it invokes — the
    consolidated hot-path pattern. Follow each `python3 .../X.py`
    invocation and check that helper for trace usage (_trace.sh,
    trace.py event, trace.append_event, import trace).
    """
    for m in _PY_INVOKE_RE.finditer(text):
        py_name = m.group(1)
        # Helper lives under skills/workflow/scripts/ by convention
        candidates = list(ctx.plugin_files(f"skills/workflow/scripts/{py_name}"))
        for cand in candidates:
            try:
                body = cand.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if _TRACE_USAGE_RE.search(body):
                return True
    return False


def check_every_hook_script_traces_its_firing(ctx: CheckContext) -> list[Finding]:
    out = []
    for p in ctx.plugin_files("hooks/claude/*.sh"):
        if p.name.startswith("_"):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        # Direct trace in the .sh
        if _TRACE_USAGE_RE.search(text):
            continue
        # Indirect: hook delegates to a python helper that itself traces
        if _hook_traces_via_helper(text, ctx):
            continue
        out.append(Finding(
            "every-hook-script-traces-its-firing", "soft",
            f"hook {p.name} never fires _trace.sh — its firing is invisible to metrics",
            ctx.rel(p)))
    return out


# ─── dispatch ────────────────────────────────────────────────────────────

# ─── Brain-specific iron-laws (v1.40+) ───────────────────────────────
# All scope to in-repo starter brain content
# (assets/starters/<name>/...). Live brains under ~/.claude/.kaizen/brain/
# are out of scope — the gate only sees repo files.

_BRAIN_TYPE_ENUM = frozenset({
    "world-fact", "belief", "observation", "experience",
    "behaviour", "persona",
})
_BRAIN_RULE_TYPE_ENUM = frozenset({
    "deletion-allow", "check-severity", "custom-pattern",
    "dependency-allowlist",
})
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FLAT_KEY = re.compile(r"^([a-z_]+):\s*(.+?)\s*$", re.MULTILINE)
_KAIZEN_BLOCK = re.compile(
    r"^kaizen:\s*\n((?:  [^\n]+\n?)+)", re.MULTILINE
)
_SANCTIONED_TOPLEVEL_NAMES = frozenset({
    "Persona.md", "REMEMBER.md", "SessionNotes.md", "README.md",
    "brain.db",
    # PARA dirs
    "Notes", "Inbox", "Journal", "Projects", "People", "Areas",
    "Resources", "Tasks", "Templates", "Archive",
})
# Patterns of personal data that must not leak into starter content.
_PERSONAL_PATTERNS = [
    (re.compile(r"\bcherry86\b"), "cherry86"),
    (re.compile(r"@gmail\.com|@anthropic\.com|@hotmail\.com|@outlook\.com|@yahoo\.com"),
     "email address"),
    # Specific project / workspace names that aren't generic placeholders.
    # Whitelist `<placeholder>` patterns so they survive.
    (re.compile(r"\bshodan workspace\b(?!.*placeholder)", re.I),
     "shodan workspace"),
]


def _parse_frontmatter(text: str) -> dict:
    """Flat-scalar YAML frontmatter parser. Returns empty dict if no FM.
    Doesn't handle nested mappings (those use _parse_kaizen_block)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fm = {}
    body = m.group(1)
    # Strip the kaizen: nested block so flat parsing doesn't grab its keys
    no_kaizen = _KAIZEN_BLOCK.sub("", body)
    for line_m in _FLAT_KEY.finditer(no_kaizen):
        k, v = line_m.group(1), line_m.group(2).strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        elif v.startswith("'") and v.endswith("'"):
            v = v[1:-1]
        fm[k] = v
    return fm


def _parse_kaizen_block(text: str) -> dict | None:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    block_m = _KAIZEN_BLOCK.search(m.group(1))
    if not block_m:
        return None
    block = {}
    for line in block_m.group(1).split("\n"):
        kv = re.match(r"^  ([a-z_]+):\s*(.+?)\s*$", line)
        if kv:
            v = kv.group(2).strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            elif v.startswith("'") and v.endswith("'"):
                v = v[1:-1]
            block[kv.group(1)] = v
    return block


def _iter_starter_notes(ctx: CheckContext):
    """Yield (note_path, text) for every `assets/starters/*/Notes/*.md`
    in scope."""
    base = ctx.plugin_root / "assets" / "starters"
    if not base.is_dir():
        return
    for starter_dir in sorted(base.iterdir()):
        if not starter_dir.is_dir():
            continue
        notes_dir = starter_dir / "Notes"
        if not notes_dir.is_dir():
            continue
        for note in sorted(notes_dir.glob("*.md")):
            if not ctx.in_scope(ctx.rel(note)):
                continue
            try:
                text = note.read_text(encoding="utf-8")
            except OSError:
                continue
            yield note, text


def check_brain_note_schema(ctx: CheckContext) -> list[Finding]:
    """BRAIN-LAW-1: every starter Note has frontmatter with `name` +
    `type` (in enum); `type: belief` requires `confidence`."""
    out = []
    for note, text in _iter_starter_notes(ctx):
        fm = _parse_frontmatter(text)
        if not fm:
            out.append(Finding(
                "brain-note-schema", "hard",
                f"{note.name}: missing or unparseable YAML frontmatter",
                ctx.rel(note)))
            continue
        if "name" not in fm:
            out.append(Finding(
                "brain-note-schema", "hard",
                f"{note.name}: frontmatter missing `name:` field",
                ctx.rel(note)))
        if "type" not in fm:
            out.append(Finding(
                "brain-note-schema", "hard",
                f"{note.name}: frontmatter missing `type:` field",
                ctx.rel(note)))
        elif fm["type"] not in _BRAIN_TYPE_ENUM:
            out.append(Finding(
                "brain-note-schema", "hard",
                f"{note.name}: invalid type '{fm['type']}' "
                f"(must be one of {sorted(_BRAIN_TYPE_ENUM)})",
                ctx.rel(note)))
        if fm.get("type") == "belief" and "confidence" not in fm:
            out.append(Finding(
                "brain-note-schema", "hard",
                f"{note.name}: type=belief requires `confidence:` field "
                "(beliefs without confidence can't graduate to Persona "
                "Top Beliefs)",
                ctx.rel(note)))
    return out


def check_brain_rule_schema(ctx: CheckContext) -> list[Finding]:
    """BRAIN-LAW-2: starter Notes with a `kaizen:` block must have
    a valid `rule_type` + type-specific required fields."""
    out = []
    for note, text in _iter_starter_notes(ctx):
        block = _parse_kaizen_block(text)
        if block is None:
            continue   # not a rule note — out of scope for this law
        rt = block.get("rule_type")
        if rt not in _BRAIN_RULE_TYPE_ENUM:
            out.append(Finding(
                "brain-rule-schema", "hard",
                f"{note.name}: invalid `rule_type` '{rt}' "
                f"(must be one of {sorted(_BRAIN_RULE_TYPE_ENUM)})",
                ctx.rel(note)))
            continue
        # Type-specific required fields
        if rt == "deletion-allow" and "path_glob" not in block:
            out.append(Finding(
                "brain-rule-schema", "hard",
                f"{note.name}: rule_type=deletion-allow requires `path_glob:`",
                ctx.rel(note)))
        elif rt == "check-severity":
            for k in ("check_id", "severity"):
                if k not in block:
                    out.append(Finding(
                        "brain-rule-schema", "hard",
                        f"{note.name}: rule_type=check-severity requires `{k}:`",
                        ctx.rel(note)))
        elif rt == "custom-pattern":
            for k in ("pattern_regex", "pattern_action"):
                if k not in block:
                    out.append(Finding(
                        "brain-rule-schema", "hard",
                        f"{note.name}: rule_type=custom-pattern requires `{k}:`",
                        ctx.rel(note)))
        elif rt == "dependency-allowlist" and "allowlist" not in block:
            out.append(Finding(
                "brain-rule-schema", "hard",
                f"{note.name}: rule_type=dependency-allowlist requires `allowlist:`",
                ctx.rel(note)))
    return out


def check_starter_no_personal_data(ctx: CheckContext) -> list[Finding]:
    """BRAIN-LAW-3: `assets/starters/**/*.md` content must not contain
    personal identifiers (real usernames, emails, specific project names).
    Generic `<placeholder>` patterns are allowed."""
    out = []
    base = ctx.plugin_root / "assets" / "starters"
    if not base.is_dir():
        return out
    for md in sorted(base.rglob("*.md")):
        if not ctx.in_scope(ctx.rel(md)):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        for pat, label in _PERSONAL_PATTERNS:
            if pat.search(text):
                out.append(Finding(
                    "starter-no-personal-data", "hard",
                    f"{md.name}: contains personal data ({label}) — "
                    "sanitize before shipping",
                    ctx.rel(md)))
                break   # one finding per file is enough
    return out


def check_brain_no_orphan_toplevel(ctx: CheckContext) -> list[Finding]:
    """BRAIN-LAW-4: starter root dir contains only sanctioned files +
    PARA-pattern subdirs. Stray files signal accumulation drift."""
    out = []
    base = ctx.plugin_root / "assets" / "starters"
    if not base.is_dir():
        return out
    for starter_dir in sorted(base.iterdir()):
        if not starter_dir.is_dir():
            continue
        for entry in sorted(starter_dir.iterdir()):
            if entry.name in _SANCTIONED_TOPLEVEL_NAMES:
                continue
            # Only flag if in scope
            if not ctx.in_scope(ctx.rel(entry)):
                continue
            out.append(Finding(
                "brain-no-orphan-toplevel", "hard",
                f"{starter_dir.name}/{entry.name}: not in the sanctioned "
                f"starter top-level set "
                f"({sorted(_SANCTIONED_TOPLEVEL_NAMES)})",
                ctx.rel(entry)))
    return out


CHECKS = {
    "no_modify_vendored": check_no_modify_vendored,
    "node_flow_for_multi_step": check_node_flow_for_multi_step,
    "lazy_heavy_deps": check_lazy_heavy_deps,
    "sandbox_tests": check_sandbox_tests,
    "bin_wrapper_per_cli": check_bin_wrapper_per_cli,
    "plugin_manifest_permissions": check_plugin_manifest_permissions,
    "hook_bypass_knob": check_hook_bypass_knob,
    "claude_md_no_volatile_data": check_claude_md_no_volatile_data,
    "paired_tests": check_paired_tests,
    "bin_wrapper_per_cli_strict": check_bin_wrapper_per_cli_strict,
    "slash_command_args_no_default_spaces": check_slash_command_args_no_default_spaces,
    "hooks_json_additive_event_multi_command": check_hooks_json_additive_event_multi_command,
    "skill_md_no_exec_markers": check_skill_md_no_exec_markers,
    "skill_md_no_external_script_paths": check_skill_md_no_external_script_paths,
    "every_hook_script_traces_its_firing": check_every_hook_script_traces_its_firing,
    "brain_note_schema": check_brain_note_schema,
    "brain_rule_schema": check_brain_rule_schema,
    "starter_no_personal_data": check_starter_no_personal_data,
    "brain_no_orphan_toplevel": check_brain_no_orphan_toplevel,
}


def _detect_repo_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True)
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def _git_staged(repo_root: Path, diff_filter: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", f"--diff-filter={diff_filter}"],
            capture_output=True, text=True, check=True, cwd=repo_root)
        return [ln for ln in out.stdout.splitlines() if ln.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def build_context(scope: str = "staged", repo_root: Path | None = None) -> CheckContext:
    root = repo_root or _detect_repo_root()
    changed = _git_staged(root, "AM") if scope == "staged" else []
    added = _git_staged(root, "A") if scope == "staged" else []
    return CheckContext(
        repo_root=root,
        plugin_root=root / "plugins" / "kaizen",
        scope=scope,
        changed=changed,
        added=added,
    )


def run_checks(
    scope: str = "staged",
    repo_root: Path | None = None,
    law_id: str | None = None,
) -> list[Finding]:
    """Run the auto-law checks. `law_id` restricts to one law; otherwise all
    auto laws run. Dispatches only `enforcement: auto` laws."""
    ctx = build_context(scope, repo_root)
    laws = _loader.auto_laws()
    if law_id:
        laws = [law for law in laws if law["id"] == law_id]
    findings: list[Finding] = []
    for law in laws:
        fn = CHECKS.get(law["check"])
        if fn is None:
            continue
        findings.extend(fn(ctx))
    return findings


if __name__ == "__main__":
    _scope = "all" if "--all" in sys.argv else "staged"
    _findings = run_checks(scope=_scope)
    for f in _findings:
        print(f"{f.severity:4} {f.law_id}: {f.message} [{f.path}]")
    sys.exit(1 if any(f.severity == "hard" for f in _findings) else 0)
