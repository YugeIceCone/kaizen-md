"""Shared argparse + dispatch base for SQLite-backed indexers (M7).

Five indexers — knowledge / claude_docs / trace / scrape / onboard — share
the same seven-subcommand CLI shape: `index / reindex / search / stats /
get / path / clear`. Only the per-indexer flags and result-formatting
diverge. This module collapses the duplicated CLI scaffolding while
keeping the per-file knobs (extra args, DB-path resolution, render style)
as overrides.

## Usage shape (per indexer)

    from _indexer_cli import IndexerCLI

    class KnowledgeCLI(IndexerCLI):
        PROG = "kaizen-knowledge-index"
        DESCRIPTION = "Semantic search over brain notes, plans, ..."
        DB_PATH = DB_PATH  # module constant

        def do_stats(self, args):
            return do_stats()        # existing module-level helper

        def do_get(self, args):
            return do_get(args.id)

        def do_search(self, args):
            return do_search(args.query, top_k=args.top_k, source=args.source)

        def do_index(self, args):
            return do_index(embed_body=args.embed_body)

        def do_reindex(self, args):
            if self.db_path_for(args).exists():
                self.db_path_for(args).unlink()
            return self.do_index(args)

        def extra_search_args(self, p):
            p.add_argument("--source", choices=[...])

        def extra_index_args(self, p):
            p.add_argument("--embed-body", action="store_true")

        def print_search(self, results, args):
            for r in results:
                print(f"  {r['score']:.3f}  ...")

    if __name__ == "__main__":
        KnowledgeCLI().run()

## Hook reference

Required overrides:
    do_stats(args)   -> dict
    do_get(args)     -> dict | None
    do_search(args)  -> list[dict]
    do_index(args)   -> dict | None
    do_reindex(args) -> dict | None
    print_search(results, args)   -> None

Optional overrides:
    PROG: str = "kaizen-indexer"
    DESCRIPTION: str = ""
    DB_PATH: Path = ...   # static path; subclass overrides db_path_for(args) if dynamic
    SUBCOMMAND_REQUIRED: bool = True

    db_path_for(args) -> Path            (default: cls.DB_PATH)
    extra_search_args(p) -> None         (default: no extra flags beyond --top-k/--json)
    extra_index_args(p) -> None
    extra_reindex_args(p) -> None
    extra_get_args(p) -> None            (default: no extra flags beyond id)
    extra_clear_args(p) -> None
    extra_path_args(p) -> None
    extra_stats_args(p) -> None
    register_extra_subcommands(sub) -> None   (e.g. claude_docs `bootstrap`,
                                               scrape `scrape`/`batch`/`list`,
                                               onboard `dump`/`filter`/`raw`)
    print_stats(stats) -> None
    print_get(rec) -> None
    print_index(result) -> None
    print_reindex(result) -> None
    on_no_index(args) -> None            (called when search/stats find no db)

Default render: stats/get/reindex/index print JSON (indent=2) when a
boolean attr `args.json` is true; subclasses override `print_*` for
human-readable output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class IndexerCLI:
    """Base class for SQLite-backed indexer CLIs (M7).

    Subclasses define data-returning `do_*` methods that wrap their
    existing module-level helpers, and (optionally) override
    `print_*` for human-readable rendering. The base provides
    `build_parser()` + `run()` so each indexer's `main()` becomes
    a 3-line entry point.
    """

    # ─── Subclass knobs (override as class attrs) ────────────────────

    PROG: str = "kaizen-indexer"
    DESCRIPTION: str = ""
    DB_PATH: Path = Path("")

    # If False, running with no subcommand prints help and exits 0
    # instead of argparse raising. (claude_docs uses this — defaults
    # to `stats` when called bare.)
    SUBCOMMAND_REQUIRED: bool = True

    # Which of the seven standard subcommands to wire up. Subclasses
    # whose CLI shape differs (e.g. scrape — uses `scrape <url>` instead
    # of `index`) can restrict this set and add their own via
    # `register_extra_subcommands`.
    STANDARD_SUBCOMMANDS: tuple[str, ...] = (
        "index", "reindex", "search", "stats", "get", "path", "clear",
    )

    # ─── Path resolution (override for project-scoped indexers) ──────

    def db_path_for(self, args: argparse.Namespace) -> Path:
        """Return the active DB path for this invocation. Static for
        most indexers; onboard overrides to derive from `args.root`."""
        return self.DB_PATH

    # ─── do_* hooks (REQUIRED — subclass must implement) ─────────────

    def do_stats(self, args: argparse.Namespace) -> dict:
        raise NotImplementedError

    def do_get(self, args: argparse.Namespace) -> dict | None:
        raise NotImplementedError

    def do_search(self, args: argparse.Namespace) -> list[dict]:
        raise NotImplementedError

    def do_index(self, args: argparse.Namespace) -> Any:
        raise NotImplementedError

    def do_reindex(self, args: argparse.Namespace) -> Any:
        # Default: drop the db file + re-run index. Subclasses can
        # override to drop tables instead (preserves WAL settings).
        p = self.db_path_for(args)
        if p.exists():
            p.unlink()
        return self.do_index(args)

    def do_clear(self, args: argparse.Namespace) -> dict:
        """Default clear: unlink the DB file. Subclasses can override
        to require --yes confirmation or drop tables instead."""
        p = self.db_path_for(args)
        if p.is_file():
            p.unlink()
            return {"removed": str(p)}
        return {"removed": None, "note": "no index to clear"}

    # ─── Argument-extension hooks (override to add flags) ────────────

    def extra_search_args(self, p: argparse.ArgumentParser) -> None: ...
    def extra_index_args(self, p: argparse.ArgumentParser) -> None: ...
    def extra_reindex_args(self, p: argparse.ArgumentParser) -> None: ...
    def extra_get_args(self, p: argparse.ArgumentParser) -> None: ...
    def extra_clear_args(self, p: argparse.ArgumentParser) -> None: ...
    def extra_path_args(self, p: argparse.ArgumentParser) -> None: ...
    def extra_stats_args(self, p: argparse.ArgumentParser) -> None: ...

    def register_extra_subcommands(
        self, sub: argparse._SubParsersAction
    ) -> None:
        """Hook to register non-standard subcommands (bootstrap/update,
        scrape/batch/list, dump/filter/raw). Default: no extras."""

    # ─── Rendering hooks (override for non-JSON output) ──────────────

    def print_search(
        self, results: list[dict], args: argparse.Namespace
    ) -> None:
        """Default: JSON dump. Subclasses override for human rendering.
        When --json is set, base falls back to JSON regardless."""
        print(json.dumps(results, indent=2, default=str))

    def print_stats(self, stats: dict, args: argparse.Namespace) -> None:
        print(json.dumps(stats, indent=2, default=str))

    def print_get(
        self, rec: dict | None, args: argparse.Namespace
    ) -> None:
        if rec is None:
            print("(not found)")
            return
        print(json.dumps(rec, indent=2, default=str))

    def print_index(self, result: Any, args: argparse.Namespace) -> None:
        if result is None:
            return
        if isinstance(result, dict):
            print(json.dumps(result, indent=2, default=str))

    def print_reindex(
        self, result: Any, args: argparse.Namespace
    ) -> None:
        self.print_index(result, args)

    def print_clear(self, result: dict, args: argparse.Namespace) -> None:
        if result.get("removed"):
            print(f"  ✓ removed {result['removed']}")
        else:
            note = result.get("note") or "no index to clear"
            print(f"  ∘ {note}")

    # ─── Default cmd_* handlers (rarely need overriding) ─────────────

    def cmd_stats(self, args: argparse.Namespace) -> None:
        self.print_stats(self.do_stats(args), args)

    def cmd_get(self, args: argparse.Namespace) -> None:
        self.print_get(self.do_get(args), args)

    def cmd_search(self, args: argparse.Namespace) -> None:
        results = self.do_search(args)
        if getattr(args, "json", False):
            print(json.dumps(results, indent=2, default=str))
            return
        self.print_search(results, args)

    def cmd_index(self, args: argparse.Namespace) -> None:
        self.print_index(self.do_index(args), args)

    def cmd_reindex(self, args: argparse.Namespace) -> None:
        self.print_reindex(self.do_reindex(args), args)

    def cmd_path(self, args: argparse.Namespace) -> None:
        print(self.db_path_for(args))

    def cmd_clear(self, args: argparse.Namespace) -> None:
        self.print_clear(self.do_clear(args), args)

    # ─── Parser construction ─────────────────────────────────────────

    def build_parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(
            prog=self.PROG,
            description=self.DESCRIPTION,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub = p.add_subparsers(dest="cmd", required=self.SUBCOMMAND_REQUIRED)

        std = set(self.STANDARD_SUBCOMMANDS)

        if "index" in std:
            pi = sub.add_parser("index", help="incremental index")
            self.extra_index_args(pi)
            pi.set_defaults(func=self.cmd_index)

        if "reindex" in std:
            pr = sub.add_parser("reindex", help="wipe + full reindex")
            self.extra_reindex_args(pr)
            pr.set_defaults(func=self.cmd_reindex)

        if "search" in std:
            ps = sub.add_parser("search", help="semantic search")
            ps.add_argument("query")
            ps.add_argument("--top-k", type=int, default=10)
            ps.add_argument("--json", action="store_true")
            self.extra_search_args(ps)
            ps.set_defaults(func=self.cmd_search)

        if "stats" in std:
            pt = sub.add_parser("stats", help="index stats")
            self.extra_stats_args(pt)
            pt.set_defaults(func=self.cmd_stats)

        if "get" in std:
            pg = sub.add_parser("get", help="fetch one record by id")
            pg.add_argument("id", type=int)
            self.extra_get_args(pg)
            pg.set_defaults(func=self.cmd_get)

        if "path" in std:
            pp = sub.add_parser("path", help="print db path")
            self.extra_path_args(pp)
            pp.set_defaults(func=self.cmd_path)

        if "clear" in std:
            pc = sub.add_parser("clear", help="drop the index")
            self.extra_clear_args(pc)
            pc.set_defaults(func=self.cmd_clear)

        self.register_extra_subcommands(sub)
        return p

    # ─── Entry point ─────────────────────────────────────────────────

    def run(self, argv: list[str] | None = None) -> None:
        parser = self.build_parser()
        args = parser.parse_args(argv)
        if not hasattr(args, "func"):
            parser.print_help()
            sys.exit(0 if not self.SUBCOMMAND_REQUIRED else 1)
        args.func(args)
