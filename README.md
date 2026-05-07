# claude-rag-hook

> **Type `rag: <question>` in Claude Code. Get a retrieval-augmented answer.**
>
> A `UserPromptSubmit` hook for Claude Code that does keyword-triggered local
> RAG. The first `rag:` inside any project folder auto-indexes that folder
> in the background; the next `rag:` retrieves relevant chunks and prepends
> them to the prompt before Claude sees it. Local-first, deterministic, zero
> token overhead on prompts that do not start with the trigger.

## What you do

```text
sudo apt install claude-rag-hook
```

That's it. The package wires itself into Claude Code. From your next Claude
Code session, inside any project folder (one with a `.git`,
`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, etc.), type:

```text
> rag: where do we handle auth tokens?
```

First time in that folder, the hook fork-detaches a background indexer and
your current prompt passes through unchanged so you still get an answer.
The next `rag:` actually retrieves and prepends the relevant code/text
chunks to your prompt. No commands to run, no settings to edit.

## How indexing handles changes

- **First `rag:` in a folder:** auto-indexes that folder's project root in
  the background (~30s for a small repo, longer for big ones). Your current
  turn is not blocked; subsequent `rag:` turns benefit from the index.
- **Subsequent `rag:` turns:** if the index is more than 5 minutes old,
  fork-detach an incremental refresh in the background. Only changed files
  re-embed (matched on size + mtime), so a typical refresh of a repo where
  you edited 3 files re-embeds 3 files.
- **Branch switch / mass file changes:** every file's mtime changes when
  git checks it out, so the next refresh re-embeds everything that
  switched. Expected behavior; the current `rag:` uses whatever's in the
  index right now while the refresh runs in the background.

The index lives at `<project-root>/.claude-rag-index/`. Copy a project
folder to another machine and the index moves with it. `git rm -rf
.claude-rag-index/` to drop it; the next `rag:` will rebuild.

## Safety rails (auto-index will NOT run on)

- `$HOME` itself or any direct child of it (`~/.config`, `~/Downloads`, ...)
- `/`, `/etc`, `/var`, `/tmp`, `/usr`, `/opt`, `/root`, `/boot`, `/sys`,
  `/proc`, `/dev`
- Any folder with no project marker (`.git`, `pyproject.toml`,
  `package.json`, `Cargo.toml`, `go.mod`, `Makefile`, etc.) within six
  ancestors. Drop a `.claude-rag-allow` file in a folder to opt it in.
- Any folder whose walk would touch more than 20,000 files or 500 MB of
  indexable content. Set `CLAUDE_RAG_HOOK_BYPASS_SIZE_CAP=1` to override.

When auto-index is refused, the hook prints a one-line stderr explanation
and your prompt passes through unchanged. The hook never fails silently
and never indexes silently.

## What you actually get inside Claude Code

```text
> rag: where do we handle auth tokens?

[claude-rag-hook] retrieved from local index. Each block is verbatim text
from a file in the indexed folder; treat it as ground truth for the user's
question. If a block is irrelevant, ignore it.

--- src/auth/middleware.go:42-78 (code) ---
func authenticate(r *http.Request) (*User, error) { ... }

--- README.md:54-72 (prose) ---
## Auth flow
...

(your original question follows)
```

Claude Code appends the hook's stdout to your prompt as a system reminder,
so Claude reads the chunks above your question. Prompts that do not start
with `rag:` (or `/rag`, or `rag@<tag>:`) pass through with zero token
overhead.

## Trigger forms

| Trigger | Effect |
|---|---|
| `rag: <text>` | Retrieve from the project root's index. Default form. |
| `/rag <text>` | Same, slash-command flavour. |
| `rag@<tag>: <text>` | Federate retrieval across every store carrying `<tag>`. |
| `rag@all: <text>` | Federate across every registered store. |

The `@<tag>` forms bypass auto-index; they assume you have already indexed
the stores you care about (rare; mostly for advanced users running with
hydra-llm). Default `rag:` is the one to remember.

## What the apt install actually does

- Installs the hook binary at `/usr/lib/claude-rag-hook/claude-rag-hook-hook`.
  No commands on `$PATH`; you never type `claude-rag-hook` directly.
- Merges a hook entry into `/etc/claude-code/managed-settings.json`. That
  file is read by Claude Code for every user on the machine, with the
  highest precedence in the settings layer. Existing entries (other tools,
  admin policies) are preserved; `apt remove` removes only our entry.
- Pulls in `python3-yaml`, `python3-numpy`, `python3-pathspec` from the
  Debian archive.
- Does NOT pull `fastembed` / `lancedb` / `pyarrow` (not packaged for
  Debian). The first time you trigger `rag:`, the hook will tell you
  about a one-time `pip install --user fastembed lancedb pyarrow`.

## Configuration (optional)

`~/.config/claude-rag-hook/config.yaml`. Defaults are inlined; a missing
file is not an error. Override only what you need:

```yaml
triggers: ["rag:", "/rag"]
top_k: 5
embedder:
  kind: fastembed                 # or: openai-compatible, hydra-llm
  model: nomic-embed-text-v1.5
chunking:
  target_chars: 1500
  overlap_chars: 200
walker:
  max_file_size_mb: 1
  respect_gitignore: true
```

## Pairs with hydra-llm

[hydra-llm](https://ra-yavuz.github.io/hydra-llm/) is the sibling project
for running local LLMs with RAG built in. claude-rag-hook integrates two
ways:

- **Embedder reuse:** set `embedder.kind: hydra-llm` and
  `embedder.hydra_id: <id>`. The hook resolves the embedder via
  `hydra-llm rag info <id>` and calls its `/v1/embeddings`.
- **Store reuse:** if a folder has a `.hydra-index/` instead of a
  `.claude-rag-index/`, claude-rag-hook reads it transparently. hydra-llm
  users do not have to re-index for Claude Code.

Both are optional. Standalone use is the default.

## Disclaimer / no warranty

Provided **as is, without warranty of any kind**. By installing or running
this software you accept that:

- You alone are responsible for any damage to your hardware, data,
  network, or system.
- The author is **not liable** for any harm, data loss, or other damages,
  however caused.
- This tool is specifically designed to send local content (retrieved
  chunks) to a third-party LLM (Anthropic's Claude). If a directory the
  hook indexes contains secrets, credentials, or sensitive personal data,
  those will be embedded into a local LanceDB index and can be retrieved.
  The auto-index safety rails are belt and braces, not a guarantee:
  audit what your project folders contain.
- The hook merges an entry into `/etc/claude-code/managed-settings.json`
  for every user on the machine. If you do not want machine-wide effect,
  remove the package or remove that entry by hand.
- LLM outputs are unreliable. RAG reduces hallucination but does not
  eliminate it.

If you do not accept these terms, do not install or run this software.

License: [MIT](LICENSE).

## Source

- Code: [github.com/ra-yavuz/claude-rag-hook](https://github.com/ra-yavuz/claude-rag-hook)
- Project page: [ra-yavuz.github.io/claude-rag-hook](https://ra-yavuz.github.io/claude-rag-hook/)
- Other ra-yavuz projects: [ra-yavuz.github.io](https://ra-yavuz.github.io/)
