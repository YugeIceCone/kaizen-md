#!/usr/bin/env python3
"""kaizen debug — universal error-locator with file:line hints.

Drop-in diagnostician for ANY error stream. Parses stderr from bash,
python, pytest, subprocess outputs, hook fires, npm/cargo/etc. — anything
that emits `<file>:<line>: <error>`-shape lines. Surfaces each error as
a structured record with file path + line number + classification +
surrounding code snippet + actionable fix hint.

## Subcommands

    debug.py scan [--since 10m] [--source X] [--json]
        Scan a log / event stream for errors.
        --source { hooks | tests | bash | python | trace | all }

    debug.py replay <command> [args...] [--timeout N] [--json]
        Run a command, capture stderr, parse for errors.

    debug.py parse [--stdin -] [--file <path>] [--json]
        Parse a stderr stream + emit structured hints.
        Pipe-friendly: `failing 2>&1 | kaizen-debug parse --stdin -`

    debug.py lint [<path> ...] [--json]
        Static-scan for common bugs (heredoc unbound vars, missing bridges).

    debug.py tail
        Live-monitor stderr logs; emit structured hints as errors fire.

## Bypass

KAIZEN_DEBUG_DISABLE=1 — silent no-op.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class DebugError:
    file: str
    line: int | None
    kind: str               # unbound-var | command-not-found | module-not-found
                            # | import-error | file-not-found | syntax-error
                            # | assertion | type-error | value-error | key-error
                            # | attr-error | name-error | runtime-error
                            # | test-failure | other
    source: str             # bash | python | test | hook | trace
    raw: str
    hint: str = ""
    snippet: list[str] = field(default_factory=list)


# ─── Pattern catalog ────────────────────────────────────────────────

_UNBOUND_VAR_RE = re.compile(
    r"^(?P<file>[^:]+\.(sh|bash)):\s*line\s+(?P<line>\d+):\s+(?P<var>\w+):\s+unbound variable"
)
_BASH_LINE_RE = re.compile(
    r"^(?P<file>[^:]+\.(sh|bash)):\s*line\s+(?P<line>\d+):\s+(?P<msg>.+)"
)
_BASH_NOT_FOUND_RE = re.compile(
    r"^(?P<file>[^:]+):\s*line\s+(?P<line>\d+):\s+(?P<cmd>\S+):\s+command not found"
)
_PYTHON_NO_MODULE_RE = re.compile(
    r"ModuleNotFoundError:\s+No module named\s+['\"](?P<mod>[^'\"]+)['\"]"
)
_PYTHON_IMPORT_ERR_RE = re.compile(r"ImportError:\s+(?P<msg>.+)")
_PYTHON_SYNTAX_RE = re.compile(
    r"(?P<err>SyntaxError|IndentationError):\s+(?P<msg>.+)"
)
_FILE_NOT_FOUND_RE = re.compile(
    r"(?:FileNotFoundError|\[Errno 2\][^']*).*?['\"](?P<path>[^'\"]+)['\"]"
)
_PYTEST_FAIL_RE = re.compile(
    r"^(?P<file>tests?/[^:]+\.py):(?P<line>\d+):\s+in\s+(?P<test>\w+)"
)
_PYTEST_ASSERT_RE = re.compile(
    r"^\s*E\s+(?:assert|AssertionError:)\s+(?P<msg>.+)"
)
_ASSERTION_RE = re.compile(r"AssertionError:\s*(?P<msg>.*)")
_PYTHON_TYPED_ERR_RE = re.compile(
    r"(?P<err>TypeError|ValueError|KeyError|AttributeError|NameError|RuntimeError):\s*(?P<msg>.+)"
)


def parse_error(line: str) -> DebugError | None:
    """Classify one stderr line into a structured DebugError."""
    for matcher in (_match_unbound_var, _match_bash_not_found,
                    _match_python_no_module, _match_python_import,
                    _match_python_syntax, _match_pytest_fail,
                    _match_pytest_assert, _match_file_not_found,
                    _match_assertion, _match_python_typed, _match_bash_line):
        result = matcher(line)
        if result:
            return result
    return None


def _match_unbound_var(line: str) -> DebugError | None:
    m = _UNBOUND_VAR_RE.search(line)
    if not m:
        return None
    return DebugError(
        file=m.group("file"), line=int(m.group("line")),
        kind="unbound-var", source="bash", raw=line.strip(),
        hint=_hint_unbound_var(m.group("var"), m.group("file"), int(m.group("line"))),
    )


def _match_bash_not_found(line: str) -> DebugError | None:
    m = _BASH_NOT_FOUND_RE.search(line)
    if not m:
        return None
    return DebugError(
        file=m.group("file"), line=int(m.group("line")),
        kind="command-not-found", source="bash", raw=line.strip(),
        hint=_hint_cmd_missing(m.group("cmd")),
    )


def _match_python_no_module(line: str) -> DebugError | None:
    m = _PYTHON_NO_MODULE_RE.search(line)
    if not m:
        return None
    return DebugError(
        file="", line=None,
        kind="module-not-found", source="python", raw=line.strip(),
        hint=_hint_module_missing(m.group("mod")),
    )


def _match_python_import(line: str) -> DebugError | None:
    m = _PYTHON_IMPORT_ERR_RE.search(line)
    if not m:
        return None
    return DebugError(
        file="", line=None, kind="import-error",
        source="python", raw=line.strip(),
        hint=f"ImportError: {m.group('msg')}. Check sys.path + circular imports.",
    )


def _match_python_syntax(line: str) -> DebugError | None:
    m = _PYTHON_SYNTAX_RE.search(line)
    if not m:
        return None
    return DebugError(
        file="", line=None, kind="syntax-error",
        source="python", raw=line.strip(),
        hint=f"{m.group('err')}: {m.group('msg')}. Run `python3 -c \"import ast; ast.parse(open('<file>').read())\"` to confirm.",
    )


def _match_file_not_found(line: str) -> DebugError | None:
    m = _FILE_NOT_FOUND_RE.search(line)
    if not m:
        return None
    return DebugError(
        file=m.group("path"), line=None,
        kind="file-not-found", source="python", raw=line.strip(),
        hint=_hint_file_missing(m.group("path")),
    )


def _match_pytest_fail(line: str) -> DebugError | None:
    m = _PYTEST_FAIL_RE.search(line)
    if not m:
        return None
    return DebugError(
        file=m.group("file"), line=int(m.group("line")),
        kind="test-failure", source="test", raw=line.strip(),
        hint=f"pytest fail in {m.group('test')} at {m.group('file')}:{m.group('line')}. Run `python3 -m pytest {m.group('file')}::{m.group('test')} -v`.",
    )


def _match_pytest_assert(line: str) -> DebugError | None:
    m = _PYTEST_ASSERT_RE.search(line)
    if not m:
        return None
    return DebugError(
        file="", line=None, kind="assertion",
        source="test", raw=line.strip(),
        hint=f"assertion failed: {m.group('msg')[:120]}",
    )


def _match_assertion(line: str) -> DebugError | None:
    m = _ASSERTION_RE.search(line)
    if not m:
        return None
    return DebugError(
        file="", line=None, kind="assertion",
        source="python", raw=line.strip(),
        hint=f"AssertionError: {m.group('msg')[:120]}",
    )


def _match_python_typed(line: str) -> DebugError | None:
    m = _PYTHON_TYPED_ERR_RE.search(line)
    if not m:
        return None
    kind_map = {
        "TypeError": "type-error", "ValueError": "value-error",
        "KeyError": "key-error", "AttributeError": "attr-error",
        "NameError": "name-error", "RuntimeError": "runtime-error",
    }
    return DebugError(
        file="", line=None,
        kind=kind_map.get(m.group("err"), "other"),
        source="python", raw=line.strip(),
        hint=_hint_typed_err(m.group("err"), m.group("msg")),
    )


def _match_bash_line(line: str) -> DebugError | None:
    m = _BASH_LINE_RE.search(line)
    if not m:
        return None
    return DebugError(
        file=m.group("file"), line=int(m.group("line")),
        kind="other", source="bash", raw=line.strip(),
        hint=f"bash error at {m.group('file')}:{m.group('line')} — {m.group('msg')}",
    )


# ─── Hints ──────────────────────────────────────────────────────────


def _hint_unbound_var(var: str, file: str, lineno: int) -> str:
    common = {
        "PLUGIN_ROOT": "PLUGIN_ROOT not set by Claude Code hook env. Use `_HANDLERS_DIR=\"$_HOOK_DIR/../../scripts/handlers\"`",
        "_HOOK_DIR": "Add at top: `_SCRIPT_REAL=\"$(readlink -f \"${BASH_SOURCE[0]}\")\"; _HOOK_DIR=\"$(cd \"$(dirname \"$_SCRIPT_REAL\")\" && pwd)\"`",
        "CLAUDE_SESSION_ID": 'Quote with default: `"${CLAUDE_SESSION_ID:-}"`',
        "CLAUDE_PLUGIN_ROOT": "Not always set. Fall back: `${CLAUDE_PLUGIN_ROOT:-$_HOOK_DIR/../..}`",
        "REPO": "Set $REPO first: `REPO=\"$(git rev-parse --show-toplevel)\"`",
    }
    detail = common.get(var, "")
    if detail:
        return f"`{var}` unbound at {file}:{lineno} — {detail}"
    return (
        f"`{var}` unbound at {file}:{lineno}. With `set -u`, every var "
        "must be set. Either: (a) set earlier, (b) use `${VAR:-default}`, "
        "or (c) re-check the env contract."
    )


def _hint_cmd_missing(cmd: str) -> str:
    common = {
        "uv": "Install uv: https://github.com/astral-sh/uv",
        "node": "node retired in v1.40+ — use Python ports under scripts/",
        "kaizen": "Run /kaizen:setup install — bin wrappers not on PATH",
        "jq": "Install jq: apt install jq / brew install jq",
    }
    return common.get(cmd, f"`{cmd}` not in PATH. Check install / PATH / typo.")


def _hint_module_missing(mod: str) -> str:
    if mod.startswith("_"):
        subdir = _guess_subdir(mod)
        if subdir:
            return (
                f"`{mod}` is a kaizen private helper that moved to "
                f"scripts/{subdir}/. Add bridge: "
                f"`sys.path.insert(0, str(Path(__file__).resolve().parents[N] / \"scripts\" / \"{subdir}\"))`."
            )
        return (
            f"`{mod}` is a kaizen private helper. Search scripts/{{handlers,brain,daemon,rules,quality,indexers,mcp,lint}}/ "
            "or skills/workflow/scripts/."
        )
    return (
        f"`{mod}` not on sys.path or not installed. Either: "
        "(a) add the right dir to sys.path, (b) pip install / uv run --script."
    )


def _guess_subdir(mod: str) -> str:
    rules = (
        ("indexers", ("_index_kit",)),
        ("brain", ("_brain",)),
        ("handlers", ("_bash_gate", "_brain_redirect", "_observer_capture",
                       "_roundtrip_detect", "_write_atomic",
                       "_bash_discipline_scan")),
        ("daemon", ("_daemon_jobs",)),
    )
    for subdir, prefixes in rules:
        if any(p in mod for p in prefixes):
            return subdir
    return ""


def _hint_file_missing(path: str) -> str:
    parts = Path(path).parts
    if "skills" in parts and "workflow" in parts and "scripts" in parts:
        name = Path(path).name.removesuffix(".py")
        rules = (
            ("indexers", ("build_index", "onboard_index", "knowledge_index",
                           "claude_docs_index", "scrape_index", "trace_index",
                           "loc_index")),
            ("brain", ("brain", "_brain")),
            ("mcp", ("_mcp",)),
            ("handlers", ("posttooluse_", "pretooluse_", "stop_",
                           "userprompt_", "subagentstop_", "context_notifier",
                           "statusline_")),
            ("quality", ("_quality", "_coverage", "md_", "density",
                          "dead_code", "complexity", "silent_fail",
                          "subprocess_rc", "frontmatter", "menu_lint",
                          "slash_collision", "sandbox_check",
                          "todo_inventory", "heavy_imports",
                          "unused_env", "turn_density", "prompt_")),
            ("daemon", ("daemon", "_daemon_jobs", "_index_kit")),
            ("lint", ("lint_fix",)),
            ("rules", ("rules", "rubric", "schema_cli")),
        )
        for subdir, hints in rules:
            if any(h in name for h in hints):
                return (
                    f"`{path}` moved to scripts/{subdir}/{Path(path).name} "
                    "during DOMAIN migration. Update the caller path."
                )
    return (
        f"`{path}` not found. Check: (a) DOMAIN migration?, "
        "(b) parents[N] off by one?, (c) env var not set?"
    )


def _hint_typed_err(err: str, msg: str) -> str:
    hints = {
        "AttributeError": "Check: (a) typo, (b) wrong object type, (c) module doesn't expose this name.",
        "TypeError": "Check: (a) wrong arg count, (b) wrong arg type, (c) None where object expected.",
        "KeyError": "Check: (a) dict missing key, (b) use .get() with default, (c) key normalization.",
        "NameError": "Check: (a) typo, (b) used before assignment, (c) import missing.",
        "ValueError": "Check: (a) parse failed (int/json), (b) value out of range, (c) bad enum.",
    }
    return f"{err}: {msg[:120]}. {hints.get(err, '')}"


# ─── Snippet enrichment ─────────────────────────────────────────────


def _enrich_with_snippet(e: DebugError) -> DebugError:
    if not e.file or not e.line:
        return e
    p = Path(e.file)
    if not p.is_file():
        return e
    try:
        all_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, e.line - 2)
        end = min(len(all_lines), e.line + 1)
        e.snippet = all_lines[start:end]
    except OSError:
        pass
    return e


# ─── Source readers ─────────────────────────────────────────────────


def _read_recent_errors(since: _dt.timedelta, source: str) -> Iterator[str]:
    if source in ("hooks", "trace", "all"):
        try:
            proc = subprocess.run(
                ["kaizen-trace", "search", "--kind", "hook",
                 "--since", _to_kaizen_since(since), "--json"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 and proc.stdout:
                for line in proc.stdout.splitlines():
                    try:
                        ev = json.loads(line)
                        err_text = (
                            ev.get("data", {}).get("stderr")
                            or ev.get("data", {}).get("error") or ""
                        )
                        if err_text:
                            yield from err_text.splitlines()
                    except (json.JSONDecodeError, AttributeError):
                        continue
        except (FileNotFoundError, subprocess.SubprocessError,
                subprocess.TimeoutExpired):
            pass

    cache_dir = Path(os.environ.get("KAIZEN_DEBUG_LOG_DIR",
                                      str(Path.home() / ".cache" / "kaizen")))
    if cache_dir.is_dir():
        for log in cache_dir.glob("*-stderr.log"):
            try:
                yield from log.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue


def _to_kaizen_since(td: _dt.timedelta) -> str:
    secs = int(td.total_seconds())
    if secs >= 86_400:
        return f"{secs // 86_400}d"
    if secs >= 3_600:
        return f"{secs // 3_600}h"
    if secs >= 60:
        return f"{secs // 60}m"
    return f"{secs}s"


def _parse_duration(s: str) -> _dt.timedelta:
    m = re.fullmatch(r"(\d+)([smhd])", s)
    if not m:
        raise ValueError(f"bad duration: {s} (expected 30s/10m/1h/1d)")
    n, unit = int(m.group(1)), m.group(2)
    mult = {"s": 1, "m": 60, "h": 3_600, "d": 86_400}[unit]
    return _dt.timedelta(seconds=n * mult)


# ─── Subcommands ────────────────────────────────────────────────────


def cmd_scan(args) -> int:
    since = _parse_duration(args.since)
    errors = _collect(_read_recent_errors(since, args.source))
    if not errors and not args.json:
        print(f"debug scan: no errors in last {args.since} (source={args.source})")
        return 0
    return _emit_errors(errors, args.json)


def cmd_parse(args) -> int:
    if args.stdin == "-":
        text = sys.stdin.read()
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    else:
        print("debug parse: --stdin - or --file <path> required", file=sys.stderr)
        return 2
    errors = _collect(text.splitlines())
    return _emit_errors(errors, args.json)


def cmd_replay(args) -> int:
    if not args.argv:
        print("debug replay: command required", file=sys.stderr)
        return 2
    # Strip leading -- if present (argparse REMAINDER quirk)
    argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=args.timeout)
    errors = _collect(proc.stderr.splitlines())

    if args.json:
        print(json.dumps({
            "command": argv, "rc": proc.returncode,
            "stdout": proc.stdout, "stderr": proc.stderr,
            "errors": [_to_dict(e) for e in errors],
        }, indent=2))
        return proc.returncode

    print(f"debug replay: {shlex.join(argv)} → rc={proc.returncode}")
    if proc.stdout:
        print("--- stdout ---")
        print(proc.stdout.rstrip())
    if proc.stderr:
        print("--- stderr ---")
        print(proc.stderr.rstrip())
    if errors:
        print("--- hints ---")
        for e in errors:
            print(f"  ✗ {e.kind}: {e.file}{':' + str(e.line) if e.line else ''}")
            print(f"    {e.hint}")
    return proc.returncode


def _collect(lines: Iterator[str]) -> list[DebugError]:
    errors: list[DebugError] = []
    seen: set[tuple[str, int | None, str, str]] = set()
    for line in lines:
        e = parse_error(line)
        if e is None:
            continue
        key = (e.file, e.line, e.kind, e.raw[:80])
        if key in seen:
            continue
        seen.add(key)
        errors.append(_enrich_with_snippet(e))
    return errors


def _to_dict(e: DebugError) -> dict:
    return {
        "file": e.file, "line": e.line, "kind": e.kind,
        "source": e.source, "raw": e.raw, "hint": e.hint,
        "snippet": e.snippet,
    }


def _emit_errors(errors: list[DebugError], as_json: bool) -> int:
    if as_json:
        print(json.dumps([_to_dict(e) for e in errors], indent=2))
        return 0 if not errors else 1
    if not errors:
        print("debug: no errors detected")
        return 0
    for e in errors:
        loc = f":{e.line}" if e.line else ""
        print(f"\n✗ [{e.kind}] {e.source} → {e.file}{loc}")
        print(f"  raw:  {e.raw}")
        print(f"  hint: {e.hint}")
        for i, snip in enumerate(e.snippet):
            marker = "→ " if e.line and (e.line - 2 + i) == (e.line - 1) else "  "
            print(f"  {marker}{snip}")
    return 1


# ─── Lint ────────────────────────────────────────────────────────────


_HEREDOC_VAR_RE = re.compile(r"\$(\w+)")
_KNOWN_SHELL_VARS = frozenset({
    "_SCRIPT_REAL", "_HOOK_DIR", "_HANDLERS_DIR", "BASH_SOURCE",
    "HOME", "PATH", "USER", "PWD", "EVENT", "EVENT_JSON", "INPUT",
    "NOW", "STATE_DIR", "STATE_PATH", "STATE_PY", "SUB", "SID", "AGENT",
    "ARGS", "REST", "DESC", "PROMPT", "TOOL", "MS", "OK",
    "CLAUDE_PLUGIN_ROOT", "CLAUDE_SESSION_ID", "REPO", "BACKLOG_MD",
    "ARCH_LOG", "VERIFY",
})


@dataclass
class LintFinding:
    file: str
    line: int
    kind: str
    detail: str


def lint_one(path: Path) -> list[LintFinding]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if path.suffix == ".sh":
        return _lint_shell(path, text)
    if path.suffix == ".py":
        return _lint_python(path, text)
    return []


def _lint_shell(path: Path, text: str) -> list[LintFinding]:
    findings = []
    lines = text.splitlines()
    in_heredoc = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if 'python3 -c "' in stripped or "python3 -c '" in stripped:
            in_heredoc = True
            continue
        if in_heredoc and stripped in ('"', "'"):
            in_heredoc = False
            continue
        if in_heredoc:
            for m in _HEREDOC_VAR_RE.finditer(line):
                var = m.group(1)
                if (var not in _KNOWN_SHELL_VARS
                        and not var.startswith("_")
                        and var not in {"sys", "os", "stdin_text", "args"}
                        and var.isupper()):
                    findings.append(LintFinding(
                        file=str(path), line=i, kind="heredoc-unset-var",
                        detail=f"$ {var} in heredoc — likely unbound at runtime "
                               f"(use $_HOOK_DIR-relative or set before heredoc)",
                    ))
    return findings


def _lint_python(path: Path, text: str) -> list[LintFinding]:
    findings = []
    for i, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^(?:import|from)\s+(_\w+)(\s|$)", line)
        if m and not line.strip().startswith("#"):
            mod = m.group(1)
            subdir = _guess_subdir(mod)
            if subdir and f"scripts/{subdir}" not in text:
                findings.append(LintFinding(
                    file=str(path), line=i, kind="missing-bridge",
                    detail=f"imports `{mod}` (now at scripts/{subdir}/) but no "
                           f"sys.path bridge to scripts/{subdir}/ in this file",
                ))
    return findings


def cmd_lint(args) -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    if args.paths:
        targets = [Path(p) for p in args.paths]
    else:
        targets = []
        for d in (plugin_root / "hooks" / "claude", plugin_root / "scripts"):
            if d.is_dir():
                targets.extend(d.rglob("*.sh"))
                targets.extend(d.rglob("*.py"))
    all_findings: list[LintFinding] = []
    for t in targets:
        if "__pycache__" in t.parts:
            continue
        all_findings.extend(lint_one(t))

    if args.json:
        print(json.dumps([
            {"file": f.file, "line": f.line, "kind": f.kind, "detail": f.detail}
            for f in all_findings
        ], indent=2))
    else:
        if not all_findings:
            print(f"debug lint: 0 findings across {len(targets)} files")
            return 0
        for f in all_findings:
            print(f"{f.file}:{f.line}  [{f.kind}]  {f.detail}")
    return 0 if not all_findings else 1


# ─── Tail ───────────────────────────────────────────────────────────


def cmd_tail(args) -> int:
    cache_dir = Path(os.environ.get("KAIZEN_DEBUG_LOG_DIR",
                                      str(Path.home() / ".cache" / "kaizen")))
    cache_dir.mkdir(parents=True, exist_ok=True)
    logs = list(cache_dir.glob("*-stderr.log"))
    if not logs:
        print(f"debug tail: no *-stderr.log files in {cache_dir}", file=sys.stderr)
        return 2

    procs = []
    for log in logs:
        p = subprocess.Popen(["tail", "-n", "0", "-F", str(log)],
                              stdout=subprocess.PIPE, text=True, bufsize=1)
        procs.append(p)

    print(f"debug tail: watching {len(logs)} stderr log(s) — Ctrl-C to stop")
    try:
        while True:
            for p in procs:
                if p.stdout is None:
                    continue
                line = p.stdout.readline()
                if line:
                    e = parse_error(line.rstrip())
                    if e:
                        loc = f":{e.line}" if e.line else ""
                        print(f"✗ {e.kind}: {e.file}{loc}")
                        print(f"  {e.hint}")
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
        return 0


# ─── smoke: exercise every kaizen-* bin with --help ─────────────────


# Bins that need user input / run long / mutate state / interactive.
# Excluded from --help smoke (they'd hang or do work).
_SMOKE_BIN_DENY: frozenset = frozenset({
    "kaizen-setup", "kaizen-bootstrap", "kaizen-update", "kaizen-publish",
    "kaizen-uninstall", "kaizen-setup-local-llm", "kaizen-refresh-cache",
    "kaizen-disable-skill", "kaizen-enable-all", "kaizen-browser",
    "kaizen-daemon", "kaizen-watch", "kaizen-trace-proxy", "kaizen-loop",
    "kaizen-fg",
})


def _plugin_bin_dir() -> Path:
    """Resolve plugin/bin from this script's location (scripts/debug.py
    → plugin_root → bin/)."""
    return Path(__file__).resolve().parent.parent / "bin"


def cmd_smoke(args) -> int:
    """Walk bin/kaizen-* and invoke each with --help. Failures surface
    rc + stderr. Skips interactive / long-running bins per _SMOKE_BIN_DENY."""
    bin_dir = _plugin_bin_dir()
    bins = sorted(bin_dir.glob("kaizen-*"))
    results = []
    passed = failed = skipped = 0
    for b in bins:
        name = b.name
        if name in _SMOKE_BIN_DENY:
            skipped += 1
            results.append({"name": name, "ok": True, "skipped": True})
            continue
        try:
            r = subprocess.run(
                [str(b), "--help"],
                capture_output=True, text=True, timeout=10,
                env={**os.environ},
            )
        except subprocess.TimeoutExpired:
            failed += 1
            results.append({"name": name, "ok": False, "rc": -1,
                             "error": "timeout (10s)"})
            continue
        except Exception as e:
            failed += 1
            results.append({"name": name, "ok": False, "rc": -1,
                             "error": f"{type(e).__name__}: {e}"})
            continue
        # Many bins return rc=2 on --help (argparse default for missing
        # required arg). Treat rc 0 / 1 / 2 as PASS unless stderr looks
        # like a Python/bash crash.
        stderr = r.stderr or ""
        bad_signals = ("Traceback (most recent call last)",
                       "ModuleNotFoundError", "ImportError:",
                       "SyntaxError:", "command not found",
                       "No such file or directory")
        crashed = any(s in stderr for s in bad_signals)
        ok = (r.returncode in (0, 1, 2)) and not crashed
        entry = {"name": name, "ok": ok, "rc": r.returncode}
        if not ok:
            entry["error"] = stderr.strip() or r.stdout.strip() or "(no output)"
            failed += 1
        else:
            passed += 1
        results.append(entry)

    envelope = {"passed": passed, "failed": failed, "skipped": skipped,
                "results": results}
    if args.json:
        print(json.dumps(envelope, indent=2))
        return 0 if failed == 0 else 2
    # Human-readable
    print(f"\n[kaizen-debug smoke] passed={passed}  failed={failed}  skipped={skipped}")
    for r in results:
        if r.get("skipped"):
            continue
        marker = "✓" if r["ok"] else "✗"
        print(f"  {marker} {r['name']:42s} rc={r.get('rc', '?')}")
        if not r["ok"]:
            err = r.get("error", "").splitlines()
            if err:
                print(f"      {err[0]}")
    return 0 if failed == 0 else 2


# ─── Check — parse-validity per axis (BK-018) ───────────────────────


@dataclass
class CheckFinding:
    axis: str          # python | yaml | jsonl | schema
    file: str
    line: int | None
    kind: str          # syntax-error | parse-error | invalid-schema
    detail: str


def _walk(root: Path, suffixes: tuple[str, ...]) -> Iterator[Path]:
    """Walk files under `root` matching any of `suffixes`, skipping
    __pycache__ / .git noise."""
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in ("__pycache__", ".git") for part in p.parts):
            continue
        name = p.name
        if any(name.endswith(s) for s in suffixes):
            yield p


def check_python(root: Path) -> list[CheckFinding]:
    import ast
    out: list[CheckFinding] = []
    for p in _walk(root, (".py",)):
        try:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as e:
            out.append(CheckFinding(
                axis="python", file=str(p), line=e.lineno,
                kind="syntax-error", detail=f"{e.msg}",
            ))
        except OSError as e:
            out.append(CheckFinding(
                axis="python", file=str(p), line=None,
                kind="read-error", detail=str(e),
            ))
    return out


def check_yaml(root: Path) -> list[CheckFinding]:
    try:
        import yaml as _yaml
    except ImportError:
        return [CheckFinding(axis="yaml", file="", line=None,
                              kind="pyyaml-missing",
                              detail="pip install pyyaml")]
    out: list[CheckFinding] = []
    for p in _walk(root, (".yaml", ".yml")):
        try:
            # safe_load_all handles both single-doc and frontmatter
            # (handoffs use `---\nfm\n---\nbody`). Draining the generator
            # forces a full parse of every doc.
            list(_yaml.safe_load_all(p.read_text(encoding="utf-8")))
        except _yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            line = mark.line + 1 if mark else None
            out.append(CheckFinding(
                axis="yaml", file=str(p), line=line,
                kind="parse-error", detail=str(e).splitlines()[0],
            ))
        except OSError as e:
            out.append(CheckFinding(
                axis="yaml", file=str(p), line=None,
                kind="read-error", detail=str(e),
            ))
    return out


def check_jsonl(root: Path) -> list[CheckFinding]:
    out: list[CheckFinding] = []
    for p in _walk(root, (".jsonl",)):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            out.append(CheckFinding(
                axis="jsonl", file=str(p), line=None,
                kind="read-error", detail=str(e),
            ))
            continue
        for i, raw in enumerate(text.splitlines(), 1):
            if not raw.strip():
                continue
            try:
                json.loads(raw)
            except json.JSONDecodeError as e:
                out.append(CheckFinding(
                    axis="jsonl", file=str(p), line=i,
                    kind="parse-error", detail=e.msg,
                ))
                break  # one finding per file is enough — repair restores
    return out


def check_schema(root: Path) -> list[CheckFinding]:
    try:
        import jsonschema as _js
    except ImportError:
        return [CheckFinding(axis="schema", file="", line=None,
                              kind="jsonschema-missing",
                              detail="pip install jsonschema")]
    out: list[CheckFinding] = []
    for p in _walk(root, (".schema.json",)):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            out.append(CheckFinding(
                axis="schema", file=str(p), line=e.lineno,
                kind="parse-error", detail=e.msg,
            ))
            continue
        except OSError as e:
            out.append(CheckFinding(
                axis="schema", file=str(p), line=None,
                kind="read-error", detail=str(e),
            ))
            continue
        try:
            _js.Draft202012Validator.check_schema(data)
        except _js.SchemaError as e:
            out.append(CheckFinding(
                axis="schema", file=str(p), line=None,
                kind="invalid-schema", detail=e.message.splitlines()[0],
            ))
    return out


_AXIS_FUNCS = {
    "python": check_python,
    "yaml":   check_yaml,
    "jsonl":  check_jsonl,
    "schema": check_schema,
}


def cmd_check(args) -> int:
    """Parse-validity check across 4 axes. Per-axis breakage is independent;
    --all (default) runs every axis."""
    plugin_root = Path(__file__).resolve().parents[1]
    root = Path(args.path).expanduser().resolve() if args.path else plugin_root

    selected = [a for a in ("python", "yaml", "jsonl", "schema")
                if getattr(args, a, False)]
    if not selected:
        selected = list(_AXIS_FUNCS.keys())

    all_findings: list[CheckFinding] = []
    files_with_findings: set[str] = set()
    files_scanned: set[str] = set()
    for axis in selected:
        for p in _walk(root, _AXIS_SUFFIXES[axis]):
            files_scanned.add(str(p))
        findings = _AXIS_FUNCS[axis](root)
        for f in findings:
            files_with_findings.add(f.file)
        all_findings.extend(findings)

    passed = len(files_scanned - files_with_findings)
    failed = len(files_with_findings)
    envelope = {
        "passed":  passed,
        "failed":  failed,
        "axes":    selected,
        "results": [
            {"axis": f.axis, "file": f.file, "line": f.line,
             "kind": f.kind, "detail": f.detail}
            for f in all_findings
        ],
    }
    if args.json:
        print(json.dumps(envelope, indent=2))
        return 0 if failed == 0 else 2
    print(f"\n[kaizen-debug check] passed={passed}  failed={failed}  "
          f"axes={','.join(selected)}")
    for f in all_findings:
        loc = f"{f.file}:{f.line}" if f.line else f.file
        print(f"  ✗ [{f.axis}/{f.kind}] {loc}")
        print(f"      {f.detail}")
    return 0 if failed == 0 else 2


_AXIS_SUFFIXES = {
    "python": (".py",),
    "yaml":   (".yaml", ".yml"),
    "jsonl":  (".jsonl",),
    "schema": (".schema.json",),
}


# ─── CLI ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("KAIZEN_DEBUG_DISABLE") == "1":
        return 0

    p = argparse.ArgumentParser(
        prog="kaizen-debug",
        description="Universal error-locator with file:line hints.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="scan recent error sources")
    p_scan.add_argument("--since", default="10m")
    p_scan.add_argument("--source", default="all",
                         choices=["all", "hooks", "tests", "bash", "python", "trace"])
    p_scan.add_argument("--json", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_parse = sub.add_parser("parse", help="parse stdin or a log file")
    p_parse.add_argument("--stdin", default="")
    p_parse.add_argument("--file", default="")
    p_parse.add_argument("--json", action="store_true")
    p_parse.set_defaults(func=cmd_parse)

    p_replay = sub.add_parser("replay", help="run a command + parse its stderr")
    p_replay.add_argument("argv", nargs=argparse.REMAINDER)
    p_replay.add_argument("--timeout", type=int, default=60)
    p_replay.add_argument("--json", action="store_true")
    p_replay.set_defaults(func=cmd_replay)

    p_lint = sub.add_parser("lint", help="static-scan for common bug patterns")
    p_lint.add_argument("paths", nargs="*")
    p_lint.add_argument("--json", action="store_true")
    p_lint.set_defaults(func=cmd_lint)

    p_tail = sub.add_parser("tail", help="live-monitor stderr logs")
    p_tail.set_defaults(func=cmd_tail)

    p_smoke = sub.add_parser(
        "smoke",
        help="exercise every kaizen-* bin with --help; surface failures",
    )
    p_smoke.add_argument("--json", action="store_true")
    p_smoke.set_defaults(func=cmd_smoke)

    p_check = sub.add_parser(
        "check",
        help="parse-validity per axis (python / yaml / jsonl / schema)",
    )
    p_check.add_argument("--python", action="store_true",
                          help="ast.parse every .py")
    p_check.add_argument("--yaml", action="store_true",
                          help="yaml.safe_load every .yaml/.yml")
    p_check.add_argument("--jsonl", action="store_true",
                          help="every line of every .jsonl is a JSON object")
    p_check.add_argument("--schema", action="store_true",
                          help="every .schema.json is a valid JSON Schema")
    p_check.add_argument("--path",
                          help="scan root (default: plugin root)")
    p_check.add_argument("--json", action="store_true")
    p_check.set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
