"""UserPromptSubmit hook entrypoint.

Claude Code's hook contract:

  stdin:  {"prompt": "...", "cwd": "...", ...}   (a JSON envelope)
  stdout: a context block that Claude Code appends before sending to Claude
  exit:   0 on success; non-zero falls back to the original prompt unchanged

The hook is fail-soft: any error is logged to stderr and exits 0 so the
user still gets a response. Non-trigger prompts produce no output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import config as config_mod
from . import retrieval, trigger


def run(stdin_text: str, cwd: Path | None = None) -> int:
    try:
        envelope = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        # Some Claude Code versions pass raw text. Treat it as the prompt.
        envelope = {"prompt": stdin_text}

    prompt = envelope.get("prompt") or envelope.get("user_prompt") or envelope.get("message") or ""
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
        return 0

    indexes = retrieval.resolve_indexes(cwd, match.tag)
    if not indexes:
        msg = (
            f"claude-rag-hook: no index found"
            f"{' for tag ' + match.tag if match.tag and match.tag != 'all' else ''}"
            f"{' (any registered store)' if match.tag == 'all' else ''}"
            f". Run `claude-rag-hook index <path>` to create one."
        )
        print(msg, file=sys.stderr, flush=True)
        return 0

    top_k = int(cfg.get("top_k", default=5) or 5)
    try:
        hits = retrieval.retrieve(match.query, indexes, top_k=top_k, cfg=cfg)
    except Exception as e:
        print(f"claude-rag-hook: retrieval error: {e}", file=sys.stderr, flush=True)
        return 0

    if not hits:
        print("claude-rag-hook: no relevant chunks found in index.", file=sys.stderr, flush=True)
        return 0

    block = retrieval.format_context(
        hits,
        header=cfg.get("context", "header", default="<context>") or "<context>",
        footer=cfg.get("context", "footer", default="</context>") or "</context>",
        show_source_lines=bool(cfg.get("context", "show_source_lines", default=True)),
    )
    sys.stdout.write(block)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    text = sys.stdin.read() if not sys.stdin.isatty() else ""
    return run(text)


if __name__ == "__main__":
    raise SystemExit(main())
