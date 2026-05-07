"""Top-level CLI for claude-rag-hook."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import (
    __version__,
    config as config_mod,
    daemon as daemon_mod,
    hook as hook_mod,
    indexer,
    installer,
    paths,
    registry,
    retrieval,
)
from .embedder import resolve as resolve_embedder


DISCLAIMER = (
    "Provided as is, no warranty. By using this tool you accept all risk. "
    "RAG retrieves text from local files and sends it to Anthropic when "
    "retrieval triggers. Audit what you index. Full text in README and on "
    "https://ra-yavuz.github.io/claude-rag-hook/"
)


def _print_disclaimer() -> None:
    print(DISCLAIMER, file=sys.stderr)


def cmd_install(args: argparse.Namespace) -> int:
    path, bak, changed = installer.install(dry_run=args.dry_run)
    if not changed:
        print(f"already installed in {path}")
        return 0
    if args.dry_run:
        print(f"dry-run: would add hook entry to {path}")
        return 0
    print(f"installed hook entry in {path}")
    if bak:
        print(f"backup: {bak}")
    print("Revert with: claude-rag-hook uninstall")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    path, bak, changed = installer.uninstall()
    if not changed:
        print(f"no claude-rag-hook entry found in {path}")
        return 0
    print(f"removed hook entry from {path}")
    if bak:
        print(f"backup: {bak}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    cfg = config_mod.load()
    root = Path(args.path).resolve()
    embedder_cfg = cfg.get("embedder", default={}) or {}
    try:
        emb = resolve_embedder(embedder_cfg)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    opts = indexer.IndexOptions(
        target_chars=int(cfg.get("chunking", "target_chars", default=1500) or 1500),
        overlap_chars=int(cfg.get("chunking", "overlap_chars", default=200) or 200),
        max_file_size_mb=float(cfg.get("walker", "max_file_size_mb", default=1.0) or 1.0),
        respect_gitignore=bool(cfg.get("walker", "respect_gitignore", default=True)),
        extra_excludes=list(args.exclude or []),
        extra_includes=list(args.include or []),
        full_rebuild=bool(args.full),
        tags=list(args.tag or []),
    )
    summary = indexer.index_folder(root, emb, opts, progress=lambda m: print(m))
    print(json.dumps(summary, indent=2))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    cfg = config_mod.load()
    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd()
    if args.tag:
        indexes = retrieval.resolve_indexes(cwd, args.tag)
    elif args.all:
        indexes = retrieval.resolve_indexes(cwd, "all")
    elif args.in_path:
        idx = Path(args.in_path).resolve() / paths.INDEX_DIR_NAME
        if not idx.is_dir():
            idx = Path(args.in_path).resolve() / paths.HYDRA_INDEX_DIR_NAME
        indexes = [idx] if idx.is_dir() else []
    else:
        indexes = retrieval.resolve_indexes(cwd, None)
    if not indexes:
        print("no index found from cwd; pass --in <path> or run `claude-rag-hook index <path>` first.",
              file=sys.stderr)
        return 1
    top_k = int(args.top_k or cfg.get("top_k", default=5) or 5)
    hits = retrieval.retrieve(args.text, indexes, top_k=top_k, cfg=cfg)
    if not hits:
        print("no hits.")
        return 0
    if args.json:
        print(json.dumps([
            {"rel": h.rel, "start_line": h.start_line, "end_line": h.end_line,
             "kind": h.kind, "score": h.score, "text": h.text}
            for h in hits
        ], indent=2))
    else:
        for h in hits:
            print(f"--- {h.rel}:{h.start_line}-{h.end_line} ({h.kind}) score={h.score:.4f} ---")
            print(h.text)
            print()
    return 0


def cmd_ls(_args: argparse.Namespace) -> int:
    entries = registry.load()
    if not entries:
        print("no indexed folders. Run `claude-rag-hook index <path>` to create one.")
        return 0
    width = max((len(e.path) for e in entries), default=10)
    for e in entries:
        tags = "[" + ",".join(e.tags) + "]" if e.tags else "[]"
        print(f"{e.path:<{width}}  {e.embedder}  dim={e.dim}  tags={tags}  last={e.last_indexed}")
    return 0


def cmd_rm(args: argparse.Namespace) -> int:
    p = Path(args.path).resolve()
    removed_reg = registry.remove(p)
    idx = p / paths.INDEX_DIR_NAME
    deleted_idx = False
    if idx.is_dir() and not args.keep_index:
        shutil.rmtree(idx)
        deleted_idx = True
    if not removed_reg and not deleted_idx:
        print(f"no index registered at {p}")
        return 1
    if removed_reg:
        print(f"unregistered {p}")
    if deleted_idx:
        print(f"deleted {idx}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    cfg = config_mod.load()
    if args.value is None:
        # Read.
        if args.key is None:
            json.dump(cfg.data, sys.stdout, indent=2, sort_keys=False)
            sys.stdout.write("\n")
            return 0
        keys = args.key.split(".")
        cur = cfg.data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                print(f"no such key: {args.key}", file=sys.stderr)
                return 1
            cur = cur[k]
        if isinstance(cur, (dict, list)):
            json.dump(cur, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(cur)
        return 0
    # Write.
    val: object = args.value
    if val.lower() in {"true", "false"}:
        val = val.lower() == "true"
    elif val.isdigit():
        val = int(val)
    else:
        try:
            val = float(val)
        except ValueError:
            pass
    cfg.set(args.key, val)
    cfg.save()
    print(f"set {args.key} = {val!r} in {paths.config_file()}")
    return 0


def cmd_hook(_args: argparse.Namespace) -> int:
    return hook_mod.main()


def cmd_daemon_status(_args: argparse.Namespace) -> int:
    if daemon_mod.is_alive():
        try:
            resp = daemon_mod.call("ping", timeout=2.0)
            print(json.dumps(resp, indent=2))
        except OSError as e:
            print(f"alive but ping failed: {e}")
            return 1
        return 0
    print("not running")
    return 1


def cmd_daemon_start(_args: argparse.Namespace) -> int:
    if daemon_mod.is_alive():
        print("already running")
        return 0
    daemon_mod.spawn(detach=True)
    print("started")
    return 0


def cmd_daemon_stop(_args: argparse.Namespace) -> int:
    if not daemon_mod.is_alive():
        print("not running")
        return 0
    if daemon_mod.stop_daemon():
        print("stopped")
        return 0
    print("failed to stop", file=sys.stderr)
    return 1


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"claude-rag-hook {__version__}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    epilog = (
        "DISCLAIMER: " + DISCLAIMER
    )
    p = argparse.ArgumentParser(
        prog="claude-rag-hook",
        description=(
            "Keyword-triggered local RAG hook for Claude Code. "
            "Type 'rag: <question>' in Claude Code; the hook prepends retrieved "
            "chunks from a local index before Claude sees the prompt."
        ),
        epilog=epilog,
    )
    p.add_argument("--version", action="version", version=f"claude-rag-hook {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("install", help="Wire the hook into ~/.claude/settings.json")
    sp.add_argument("--dry-run", action="store_true", help="Print the change without writing")
    sp.set_defaults(func=cmd_install)

    sp = sub.add_parser("uninstall", help="Remove the hook entry from ~/.claude/settings.json")
    sp.set_defaults(func=cmd_uninstall)

    sp = sub.add_parser("index", help="Walk + chunk + embed a folder")
    sp.add_argument("path", nargs="?", default=".", help="Folder to index (default: cwd)")
    sp.add_argument("--full", action="store_true", help="Force a from-scratch rebuild")
    sp.add_argument("--tag", action="append", help="Tag this store (repeatable)")
    sp.add_argument("--exclude", action="append", help="Glob to exclude (repeatable)")
    sp.add_argument("--include", action="append", help="Glob to force-include (repeatable)")
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("query", help="Sanity-check retrieval (no Claude)")
    sp.add_argument("text", help="Query text")
    sp.add_argument("--top-k", type=int, help="Number of hits")
    sp.add_argument("--in", dest="in_path", help="Path of an indexed folder")
    sp.add_argument("--cwd", help="Override cwd for index resolution")
    sp.add_argument("--tag", help="Federate across stores carrying this tag")
    sp.add_argument("--all", action="store_true", help="Federate across every registered store")
    sp.add_argument("--json", action="store_true", help="JSON output")
    sp.set_defaults(func=cmd_query)

    sp = sub.add_parser("ls", help="List indexed folders")
    sp.set_defaults(func=cmd_ls)

    sp = sub.add_parser("rm", help="Drop an index")
    sp.add_argument("path", help="Folder whose index to remove")
    sp.add_argument("--keep-index", action="store_true",
                    help="Only unregister; do not delete the .claude-rag-index directory")
    sp.set_defaults(func=cmd_rm)

    sp = sub.add_parser("config", help="Read or set config keys")
    sp.add_argument("key", nargs="?", help="Dotted key (e.g. embedder.kind)")
    sp.add_argument("value", nargs="?", help="Value to write (omit to read)")
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("hook", help="Run as a Claude Code UserPromptSubmit hook")
    sp.set_defaults(func=cmd_hook)

    sp = sub.add_parser("daemon", help="Inspect / control the warm embedder daemon")
    sub2 = sp.add_subparsers(dest="dcmd", required=True)
    sub2.add_parser("status").set_defaults(func=cmd_daemon_status)
    sub2.add_parser("start").set_defaults(func=cmd_daemon_start)
    sub2.add_parser("stop").set_defaults(func=cmd_daemon_stop)

    sp = sub.add_parser("version", help="Print version")
    sp.set_defaults(func=cmd_version)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not os.environ.get("CLAUDE_RAG_HOOK_NO_DISCLAIMER"):
        # Show the disclaimer on every non-hook user-facing command.
        if args.cmd not in {"hook", "version"}:
            _print_disclaimer()
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
