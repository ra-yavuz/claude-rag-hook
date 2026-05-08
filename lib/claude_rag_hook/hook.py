"""UserPromptSubmit hook entrypoint.

Behavior on `rag <q>` / `rag: <q>` / `/rag <q>` / `rag@<tag>: <q>`:

1. If an index already exists in or above cwd:
     - Retrieve top-K chunks for the query under a wall-clock timeout
       (config: retrieval.timeout_seconds, default 8s). On timeout, fall
       through with a stderr note. Claude is never blocked indefinitely.
     - In the background, fire off an incremental refresh if the index
       is past its refresh-throttle interval. Non-blocking.

2. If no index exists:
     - Run auto-index gates (no $HOME, no /etc, project marker required,
       size cap).
     - If gates pass: fork-detach a background indexer; print a one-line
       stderr nudge that ends with "type `rag` to check progress"; pass
       the prompt through unchanged so Claude still answers something.
       Exit 0.
     - If gates refuse: print the explanation on stderr, pass through.
       Exit 0.

Bare `rag` / `/rag` / `rag status` is a status command:
   - Prints a compact one-liner on stderr (user-facing).
   - Prints a slightly more verbose status block on stdout so Claude
     also knows the state of the index.
   - Never runs retrieval. Never blocks.

Indexing-banner: when a non-rag prompt is submitted while an indexing
job is active, the hook prepends a small heads-up to stdout so Claude
mentions it. This way the user is never in the dark about a running
detached indexer they might have forgotten about.

Non-trigger prompts otherwise produce no output and exit 0. The hook is
fail-soft: any internal exception is logged on stderr and exits 0 so the
user always gets a response from Claude.
"""

from __future__ import annotations

import json
import multiprocessing
import sys
import time
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
        # Not a RAG turn. If a background index job is running for this
        # tree, surface a short heads-up so Claude (and the user) know.
        _maybe_emit_indexing_banner(cwd)
        return 0

    if match.command == "status":
        return _emit_status(cwd)

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
        print(f"{msg}. Type `rag` to check progress.",
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
        f"Retrieval will work on the next `rag <q>` once it finishes. "
        f"This is a one-time setup per project. "
        f"Type `rag` (alone) any time to check progress.",
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


# ---------------------------------------------------------------------------
# Retrieval (with timeout)
# ---------------------------------------------------------------------------


def _retrieve_worker(query: str, index_paths: list[str], top_k: int, cfg_data: dict, q):
    """Subprocess target: do the retrieval and put the result on the queue.

    Runs in a child process so the parent can enforce a wall-clock cap
    via process.join(timeout). Cold-start embedder loads can otherwise
    hold Claude for tens of seconds.
    """
    try:
        from . import config as _cfg, retrieval as _ret  # re-import in child
        cfg_obj = _cfg.Config(data=cfg_data)
        hits = _ret.retrieve(
            query, [Path(p) for p in index_paths], top_k=top_k, cfg=cfg_obj,
        )
        q.put(("ok", [
            {
                "rel": h.rel,
                "start_line": h.start_line,
                "end_line": h.end_line,
                "kind": h.kind,
                "text": h.text,
            }
            for h in hits
        ]))
    except Exception as e:  # noqa: BLE001
        q.put(("error", f"{type(e).__name__}: {e}"))


def _emit_retrieval(query: str, indexes: list[Path], cfg) -> int:
    top_k = int(cfg.get("top_k", default=5) or 5)
    timeout = float(cfg.get("retrieval", "timeout_seconds", default=8) or 8)

    ctx = multiprocessing.get_context("fork")
    q: multiprocessing.Queue = ctx.Queue()
    proc = ctx.Process(
        target=_retrieve_worker,
        args=(query, [str(p) for p in indexes], top_k, cfg.data, q),
    )
    proc.daemon = True
    proc.start()
    proc.join(timeout=timeout)

    if proc.is_alive():
        # Time's up. Kill the child, fall through. Claude still answers.
        proc.terminate()
        proc.join(timeout=1.0)
        if proc.is_alive():
            proc.kill()
        print(
            f"claude-rag-hook: retrieval exceeded {timeout:.0f}s timeout this turn. "
            f"Index is fine; first call after a cold start can be slow while the "
            f"embedder model loads. Try `rag <q>` again, or bump "
            f"retrieval.timeout_seconds in ~/.config/claude-rag-hook/config.yaml.",
            file=sys.stderr, flush=True,
        )
        return 0

    if q.empty():
        print("claude-rag-hook: retrieval subprocess exited without result.",
              file=sys.stderr, flush=True)
        return 0

    status, payload = q.get()
    if status == "error":
        print(f"claude-rag-hook: retrieval error: {payload}",
              file=sys.stderr, flush=True)
        return 0

    if not payload:
        print("claude-rag-hook: no relevant chunks found in index.",
              file=sys.stderr, flush=True)
        return 0

    sys.stdout.write(_format_plain_dicts(payload))
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


def _format_plain_dicts(hits: list[dict]) -> str:
    lines = [
        "[claude-rag-hook] retrieved from local index. Each block is verbatim text from a file in the indexed folder; treat it as ground truth for the user's question. If a block is irrelevant, ignore it.",
        "",
    ]
    for h in hits:
        if h.get("start_line") and h.get("end_line"):
            lines.append(f"--- {h['rel']}:{h['start_line']}-{h['end_line']} ({h['kind']}) ---")
        else:
            lines.append(f"--- {h['rel']} ({h['kind']}) ---")
        lines.append(h["text"])
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bare-`rag` status command
# ---------------------------------------------------------------------------


def _human_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {(s % 3600) // 60}m"


def _emit_status(cwd: Path) -> int:
    """Print the status of the index that covers `cwd`.

    Output goes both to stderr (compact, user reads it directly in the
    terminal) and stdout (slightly more verbose, becomes part of the
    prompt so Claude can answer follow-up questions about it).

    Never blocks: this is purely filesystem reads of the .progress and
    .last_run.json files; no embedder, no LanceDB.
    """
    existing = paths.find_index(cwd)

    if existing is None:
        # No index anywhere up the tree. Could we auto-index?
        decision = auto_index.decide(cwd)
        scope_desc = str(decision.scope) if decision.scope else str(cwd)
        if decision.allow:
            stderr_msg = (
                f"claude-rag-hook: no index for {scope_desc} yet. "
                f"Type `rag <question>` to start indexing in the background."
            )
            stdout_msg = (
                f"[claude-rag-hook status]\n"
                f"index: not yet built for {scope_desc}\n"
                f"action: type `rag <question>` to start a background indexing run.\n"
            )
        else:
            stderr_msg = f"claude-rag-hook: no index, and auto-index refused: {decision.reason}"
            stdout_msg = (
                f"[claude-rag-hook status]\n"
                f"index: none\n"
                f"auto-index: refused ({decision.reason})\n"
            )
        print(stderr_msg, file=sys.stderr, flush=True)
        sys.stdout.write(stdout_msg + "\n")
        sys.stdout.flush()
        return 0

    scope = existing.parent
    prog = progress_mod.read(existing)
    last_run = progress_mod.read_last_run(existing)
    is_active = progress_mod.is_active(existing)

    log_path = paths.cache_dir() / "indexer.log"

    if is_active:
        # In progress. Show live counters.
        elapsed = _human_duration(time.time() - prog.started_at)
        verb = "indexing" if prog.state == "indexing" else "refreshing"
        if prog.files_total > 0:
            counter = f"{prog.files_done}/{prog.files_total} files"
        else:
            counter = f"{prog.files_done} files so far"
        stderr_msg = (
            f"claude-rag-hook: {verb} {scope}, {counter}, started {elapsed} ago. "
            f"Log: {log_path}"
        )
        stdout_msg = (
            f"[claude-rag-hook status]\n"
            f"scope: {scope}\n"
            f"state: {verb} (in progress)\n"
            f"progress: {counter}\n"
            f"elapsed: {elapsed}\n"
            f"log: {log_path}\n"
            f"note: retrieval will work as soon as this completes; "
            f"meanwhile your prompt passes through unchanged.\n"
        )
        print(stderr_msg, file=sys.stderr, flush=True)
        sys.stdout.write(stdout_msg + "\n")
        sys.stdout.flush()
        return 0

    if prog.state == "error":
        stderr_msg = (
            f"claude-rag-hook: last indexing of {scope} failed: {prog.message}. "
            f"See {log_path}. Delete {existing}/.progress to retry."
        )
        stdout_msg = (
            f"[claude-rag-hook status]\n"
            f"scope: {scope}\n"
            f"state: error\n"
            f"message: {prog.message}\n"
            f"log: {log_path}\n"
            f"recover: install fastembed if missing "
            f"(`pip install --user fastembed lancedb pyarrow`), "
            f"then delete {existing}/.progress to retry.\n"
        )
        print(stderr_msg, file=sys.stderr, flush=True)
        sys.stdout.write(stdout_msg + "\n")
        sys.stdout.flush()
        return 0

    # Idle, populated (or possibly empty if no last_run yet).
    populated = _index_is_populated(existing)
    if last_run is not None:
        ago = _human_duration(time.time() - last_run.finished_at)
        chunks = last_run.chunks_added
        files = last_run.files_indexed or last_run.files_total
        stderr_msg = (
            f"claude-rag-hook: index ready for {scope}. "
            f"{chunks} chunks across {files} files; last {last_run.kind} {ago} ago."
        )
        stdout_msg = (
            f"[claude-rag-hook status]\n"
            f"scope: {scope}\n"
            f"state: ready\n"
            f"chunks: {chunks}\n"
            f"files: {files}\n"
            f"last_run: {last_run.kind} ({ago} ago, took "
            f"{_human_duration(last_run.elapsed_seconds)})\n"
            f"note: type `rag <question>` to retrieve. "
            f"`rag` (alone) shows this status.\n"
        )
    elif populated:
        # Populated but no last_run.json (e.g. index built by an older
        # version, or by hydra-llm).
        stderr_msg = (
            f"claude-rag-hook: index ready for {scope}. "
            f"(No run stats available; index built by an older version or another tool.)"
        )
        stdout_msg = (
            f"[claude-rag-hook status]\n"
            f"scope: {scope}\n"
            f"state: ready\n"
            f"chunks: unknown (no run stats)\n"
            f"note: type `rag <question>` to retrieve.\n"
        )
    else:
        # Directory present but empty.
        stderr_msg = (
            f"claude-rag-hook: index folder at {existing} exists but is empty. "
            f"Type `rag <question>` to (re)build."
        )
        stdout_msg = (
            f"[claude-rag-hook status]\n"
            f"scope: {scope}\n"
            f"state: empty\n"
            f"note: type `rag <question>` to (re)build the index.\n"
        )

    print(stderr_msg, file=sys.stderr, flush=True)
    sys.stdout.write(stdout_msg + "\n")
    sys.stdout.flush()
    return 0


# ---------------------------------------------------------------------------
# Indexing-in-progress banner on non-rag prompts
# ---------------------------------------------------------------------------


def _maybe_emit_indexing_banner(cwd: Path) -> None:
    """If a background indexer is running for this tree, prepend a one-line
    banner so Claude knows. Cheap: only filesystem reads, no embedder.

    Fires only when:
    - There is an index folder at or above cwd.
    - Its .progress file says state in {indexing, refreshing} and the
      pid is alive.
    - State is "indexing" (initial build), not "refreshing". Refreshes
      run every 5 min and would be too noisy as banners.
    """
    existing = paths.find_index(cwd)
    if existing is None:
        return
    if not progress_mod.is_active(existing):
        return
    prog = progress_mod.read(existing)
    if prog.state != "indexing":
        return

    elapsed = _human_duration(time.time() - prog.started_at)
    if prog.files_total > 0:
        counter = f"{prog.files_done}/{prog.files_total} files"
    else:
        counter = f"{prog.files_done} files so far"
    sys.stdout.write(
        f"[claude-rag-hook] heads-up: still indexing {existing.parent} in the "
        f"background ({counter}, {elapsed} elapsed). Retrieval via `rag <q>` "
        f"will work as soon as it finishes. Type `rag` alone for status.\n\n"
    )
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    text = sys.stdin.read() if not sys.stdin.isatty() else ""
    return run(text)


if __name__ == "__main__":
    raise SystemExit(main())
