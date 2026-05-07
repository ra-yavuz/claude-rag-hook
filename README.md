# claude-rag-hook

> **Type `rag: <question>` in Claude Code. Get a retrieval-augmented answer.**
>
> A `UserPromptSubmit` hook for Claude Code that does keyword-triggered local
> RAG against an indexed folder before Claude ever sees the prompt. Cheap,
> deterministic, local-first.

`claude-rag-hook` is a small, opinionated, **non-MCP** alternative to the
existing local-RAG-for-Claude-Code projects. Instead of letting the model
decide when to retrieve (with all the "why didn't it use the tool that
time" debugging that brings), the user types a keyword prefix and the
hook does the rest. Zero token overhead on prompts that don't start with
the keyword. No tool-call round trip. Composable with model-decides RAG
via MCP servers if you want both.

## Status

Beta. The architecture is settled (see `DESIGN.md`); the implementation
is in this repository. The hook works end to end with the bundled
fastembed embedder and a per-folder LanceDB index. Distribution as a
`.deb` via `ra-yavuz.github.io/apt` is in progress.

## How it feels

```text
> rag: where do we handle auth tokens?
[hook retrieves top-5 chunks from .claude-rag-index/ and prepends them]
[Claude reads context block + your question, answers]
```

A prompt that does not start with the trigger keyword passes through
untouched. Zero overhead on non-RAG turns.

## Install (planned)

apt (Debian / Ubuntu):

```bash
sudo bash -c 'set -e; install -m 0755 -d /etc/apt/keyrings && \
  curl -fsSL https://ra-yavuz.github.io/apt/pubkey.gpg \
    -o /etc/apt/keyrings/ra-yavuz.gpg && \
  echo "deb [signed-by=/etc/apt/keyrings/ra-yavuz.gpg] https://ra-yavuz.github.io/apt stable main" \
    > /etc/apt/sources.list.d/ra-yavuz.list && \
  apt update && apt install -y claude-rag-hook'
```

pip (any platform):

```bash
pip install --user 'claude-rag-hook[fastembed]'
```

Then wire the hook into Claude Code:

```bash
claude-rag-hook install        # adds a UserPromptSubmit entry to ~/.claude/settings.json
```

Index a folder:

```bash
cd ~/projects/cool-app
claude-rag-hook index .
```

Now, in Claude Code, opened anywhere under `~/projects/cool-app`:

```text
> rag: where do we handle auth tokens?
```

## CLI

```text
claude-rag-hook install              one-time: write the hook entry to ~/.claude/settings.json
claude-rag-hook uninstall            remove that entry
claude-rag-hook index [path]         walk + chunk + embed + store in <path>/.claude-rag-index/
claude-rag-hook query "<text>"       sanity-check retrieval (no Claude)
claude-rag-hook ls                   list indexed folders
claude-rag-hook rm <path>            drop an index
claude-rag-hook config <key> [val]   read or set config keys
claude-rag-hook hook                 read hook envelope on stdin, emit context on stdout
```

## Trigger forms

The hook recognises these prompt prefixes (case-insensitive, leading
whitespace tolerated):

- `rag: <text>` retrieve chunks for `<text>`, prepend, pass `<text>` through.
- `/rag <text>` slash-command flavour.
- `rag <text>` lax form, off by default. Toggle in config.

Cross-folder federation:

- `rag@<tag>: <text>` retrieve from every store tagged with `<tag>`.
- `rag@all: <text>` retrieve from every registered store.

A non-matching prompt falls through unchanged.

## Configuration

`~/.config/claude-rag-hook/config.yaml`:

```yaml
triggers:
  - "rag:"
  - "/rag"
top_k: 5
embedder:
  kind: fastembed
  model: nomic-embed-text-v1.5
chunking:
  target_chars: 1500
  overlap_chars: 200
walker:
  max_file_size_mb: 1
  respect_gitignore: true
daemon:
  idle_ttl_seconds: 1800
```

## Privacy

- The hook reads files inside any folder you index and stores chunked text
  plus embeddings of those files at `<folder>/.claude-rag-index/`.
- The hook injects retrieved chunks into the prompt that is sent to
  Anthropic. **Indexed material is shipped to Claude when retrieval
  triggers.** Audit what you index before triggering retrieval. Indexes
  never leave your machine on their own, but retrieval results do, because
  that is the entire point.
- The warm embedder daemon runs as your user. Its socket lives under
  `~/.cache/claude-rag-hook/` with mode 0700.

## Pairs with hydra-llm

[hydra-llm](https://ra-yavuz.github.io/hydra-llm/) is the sibling project
for running local LLMs with RAG built in. If you have it installed,
`claude-rag-hook` can reuse its embedder catalog and per-folder
`.hydra-index/` stores; see `DESIGN.md` for the interop notes.

## Disclaimer / no warranty

Provided **as is, without warranty of any kind**. By installing or running
this software you accept that:

- You alone are responsible for any damage to your hardware, data, network,
  or system.
- The author is **not liable** for any harm, data loss, or other damages,
  however caused.
- This tool is specifically designed to send local content (retrieved
  chunks) to a third-party LLM (Anthropic's Claude). If a directory you
  index contains secrets, credentials, or sensitive personal data, those
  can be retrieved and sent. Audit what you index. The README, project
  page, and CLI `--help` carry this notice.
- The warm embedder daemon runs as the user; a misconfigured config file
  or a malicious process able to write to it could be used to exfiltrate
  retrieval results.

If you do not accept these terms, do not install or run this software.

License: [MIT](LICENSE).

## Source

- Code: [github.com/ra-yavuz/claude-rag-hook](https://github.com/ra-yavuz/claude-rag-hook)
- Project page: [ra-yavuz.github.io/claude-rag-hook](https://ra-yavuz.github.io/claude-rag-hook/)
- Other ra-yavuz projects: [ra-yavuz.github.io](https://ra-yavuz.github.io/)
