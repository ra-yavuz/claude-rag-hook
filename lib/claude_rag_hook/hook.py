"""UserPromptSubmit hook entrypoint.

Behavior on `rag: <q>` (or any configured trigger):

1. If an index already exists in or above cwd:
     - Retrieve top-K chunks for the query.
     - Print them on stdout (Claude Code appends to system prompt).
     - In the background, fire off an incremental refresh if the index is
       past its refresh-throttle interval. Non-blocking.

2. If no index exists:
     - Run auto-index gates (no $HOME, no /etc, project marker required,
       size cap).
     - If gates pass: fork-detach a background indexer; print a one-line
       stderr nudge ("indexing this folder, retrieval will work on the
       next rag:"); pass the prompt through unchanged so Claude still
       answers something. Exit 0.
     - If gates refuse: print the explanation on stderr, pass through.
       Exit 0.

Non-trigger prompts produce no output and exit 0. The hook is fail-soft:
any internal exception is logged on stderr and exits 0 so the user always
gets a response from Claude.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import (
    auto_index,
    config as config_mod,
    paths,
    progress as progress_mod,
    retrieval,
    runner,
    trigger,
)


def run(stdin_text: str, cwd: Path | None = None) -> int:
    try:
        envelope = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        # Some Claude Code versions / wrappers may pass raw text. Treat as prompt.
        envelope = {"prompt": stdin_text}

    prompt = envelope.get("prompt") or ""
    if not isinstance(prompt, str):
        return 0

    env_cwd = envelope.get("cwd") or envelope.get("working_directory")
    if cwd is None:
        cwd = Path(env_cwd) if env_cwd else Path.cwd()

    cfg = config_mod.load()
    triggers = config_mod.triggers(cfg)
    lax = bool(cfg.get("lax_trigger", default=False))
    match = trigger.parse(prompt, triggers, lax=lax)
    if match is None:
        # Not a RAG turn. Hook is silent.
        return 0

    # Tagged retrieval (rag@all:, rag@<tag>:) bypasses auto-index entirely:
    # the user has explicitly named the scope, so it's already on them to
    # have indexed it.
    if match.tag is not None:
        indexes = retrieval.resolve_indexes(cwd, match.tag)
        if not indexes:
            scope_desc = "any registered store" if match.tag == "all" else f"tag '{match.tag}'"
            print(f"claude-rag-hook: no index found for {scope_desc}.",
                  file=sys.stderr, flush=True)
            return 0
        return _emit_retrieval(match.query, indexes, cfg)

    # Untagged: prefer the existing index in or above cwd, else auto-index.
    existing = paths.find_index(cwd)
    if existing is not None and _index_is_populated(existing):
        # Index is there and has data. Retrieve, then maybe refresh in
        # the background.
        scope = existing.parent
        try:
            runner.maybe_refresh(scope)
        except Exception as e:
            # Background refresh failures must not break retrieval.
            print(f"claude-rag-hook: background refresh skipped ({e}).",
                  file=sys.stderr, flush=True)
        return _emit_retrieval(match.query, [existing], cfg)

    if existing is not None:
        # Directory exists but is empty (e.g. last indexing attempt
        # failed before writing any rows). Treat the same as "no index"
        # below, so the error-surfacing branch can speak up.
        scope_for_error = existing.parent
        last = progress_mod.read(existing)
        if last.state == "error":
            print(
                f"claude-rag-hook: previous indexing of {scope_for_error} "
                f"failed: {last.message}\n"
                f"  See {paths.cache_dir() / 'indexer.log'} for the traceback.\n"
                f"  Common fix: pip install --user fastembed lancedb pyarrow\n"
                f"  Then delete {existing}/.progress to retry.",
                file=sys.stderr, flush=True,
            )
            return 0

    # No index. Decide whether we can auto-index.
    decision = auto_index.decide(cwd)
    if not decision.allow:
        print(f"claude-rag-hook: {decision.reason}", file=sys.stderr, flush=True)
        return 0

    # Auto-index allowed. Is there already a job in progress for this scope?
    scope = decision.scope
    assert scope is not None
    index_dir = scope / paths.INDEX_DIR_NAME
    if progress_mod.is_active(index_dir):
        prog = progress_mod.read(index_dir)
        msg = prog.as_human() or f"claude-rag-hook: indexing {scope} in progress."
        print(f"{msg} Retrieval will work as soon as it finishes.",
              file=sys.stderr, flush=True)
        return 0

    # Did a previous attempt fail? Surface the error so the user can act on
    # it (typically: install fastembed, check config). Do not re-trigger
    # indexing automatically; the same error will just repeat.
    last = progress_mod.read(index_dir)
    if last.state == "error":
        print(
            f"claude-rag-hook: previous indexing attempt of {scope} failed: "
            f"{last.message}\n"
            f"  See {paths.cache_dir() / 'indexer.log'} for the traceback.\n"
            f"  Common fix: pip install --user fastembed lancedb pyarrow\n"
            f"  Then delete {index_dir}/.progress to retry.",
            file=sys.stderr, flush=True,
        )
        return 0

    # Kick off a fresh indexing job and tell the user.
    runner.fork_detach_index(scope, kind="indexing")
    print(
        f"claude-rag-hook: indexing {scope} in the background. "
        f"Retrieval will work on the next `rag:` once it finishes. "
        f"This is a one-time setup per project.",
        file=sys.stderr, flush=True,
    )
    return 0


def _index_is_populated(index_dir: Path) -> bool:
    """Cheap check: does the index actually contain a LanceDB table?

    Just having a `.claude-rag-index/` directory is not enough; an
    aborted indexing attempt leaves the directory but no `chunks.lance/`
    inside it. Treating that as "index ready" leads to empty retrievals
    and confused users.
    """
    if not index_dir.is_dir():
        return False
    try:
        for entry in index_dir.iterdir():
            # LanceDB writes one .lance subdirectory per table.
            if entry.is_dir() and entry.name.endswith(".lance"):
                return True
    except OSError:
        return False
    return False


def _emit_retrieval(query: str, indexes: list[Path], cfg) -> int:
    top_k = int(cfg.get("top_k", default=5) or 5)
    try:
        hits = retrieval.retrieve(query, indexes, top_k=top_k, cfg=cfg)
    except Exception as e:
        print(f"claude-rag-hook: retrieval error: {e}", file=sys.stderr, flush=True)
        return 0
    if not hits:
        print("claude-rag-hook: no relevant chunks found in index.",
              file=sys.stderr, flush=True)
        return 0

    sys.stdout.write(_format_plain(hits))
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


def _format_plain(hits) -> str:
    """Plain-text output. Claude Code appends stdout to the prompt as a
    system reminder; no tag wrapping is needed (or recommended)."""
    lines = [
        "[claude-rag-hook] retrieved from local index. Each block is verbatim text from a file in the indexed folder; treat it as ground truth for the user's question. If a block is irrelevant, ignore it.",
        "",
    ]
    for h in hits:
        if h.start_line and h.end_line:
            lines.append(f"--- {h.rel}:{h.start_line}-{h.end_line} ({h.kind}) ---")
        else:
            lines.append(f"--- {h.rel} ({h.kind}) ---")
        lines.append(h.text)
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    text = sys.stdin.read() if not sys.stdin.isatty() else ""
    return run(text)


if __name__ == "__main__":
    raise SystemExit(main())
