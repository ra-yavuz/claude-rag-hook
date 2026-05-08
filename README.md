# claude-rag-hook

> **Type `rag <question>` in Claude Code. Get a retrieval-augmented answer.**
>
> A `UserPromptSubmit` hook for Claude Code that does keyword-triggered local
> RAG. The first `rag` query inside any project folder auto-indexes that
> folder in the background; the next `rag <q>` retrieves relevant chunks and
> prepends them to the prompt before Claude sees it. Local-first,
> deterministic, zero token overhead on prompts that do not start with the
> trigger.

## What you do

```text
sudo apt install claude-rag-hook
```

That's it. The package wires itself into Claude Code. From your next Claude
Code session, inside any project folder (one with a `.git`,
`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, etc.), type:

```text
> rag where do we handle auth tokens?
```

First time in that folder, the hook fork-detaches a background indexer and
your current prompt passes through unchanged so you still get an answer.
The next `rag <q>` actually retrieves and prepends the relevant code/text
chunks to your prompt. No commands to run, no settings to edit.

To check what the hook is up to at any point, type `rag` alone:

```text
> rag
[claude-rag-hook status]
scope: /home/you/projects/widgets
state: ready
chunks: 4231
files: 312
last_run: indexing (8m ago, took 47s)
```

When indexing is still running, the same command shows live progress
(`indexing, 1240/3500 files, 2m elapsed, log: ~/.cache/claude-rag-hook/indexer.log`).

## How indexing handles changes

- **First `rag <q>` in a folder:** auto-indexes that folder's project root in
  the background (~30s for a small repo, longer for big ones). Your current
  turn is not blocked; subsequent `rag <q>` turns benefit from the index.
- **Subsequent `rag <q>` turns:** if the index is more than 5 minutes old,
  fork-detach an incremental refresh in the background. Only changed files
  re-embed (matched on size + mtime), so a typical refresh of a repo where
  you edited 3 files re-embeds 3 files.
- **Branch switch / mass file changes:** every file's mtime changes when
  git checks it out, so the next refresh re-embeds everything that
  switched. Expected behavior; the current `rag <q>` uses whatever's in the
  index right now while the refresh runs in the background.

The index lives at `<project-root>/.claude-rag-index/`. Copy a project
folder to another machine and the index moves with it. `git rm -rf
.claude-rag-index/` to drop it; the next `rag <q>` will rebuild.

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
with a trigger keyword pass through with zero token overhead.

## Trigger forms

| Trigger | Effect |
|---|---|
| `rag <text>` | Retrieve from the project root's index. Default form. |
| `rag: <text>` | Same. The colon form is equivalent and predates the no-colon form. |
| `/rag <text>` | Same, slash-command flavour. |
| `rag` (alone) | Print index status. If no index exists yet, kick off indexing. **Ends the turn without invoking the model**, so it costs zero tokens. Same for `/rag`, `rag status`, and `rag:`. |
| `rag@<tag>: <text>` | Federate retrieval across every store carrying `<tag>`. |
| `rag@all: <text>` | Federate across every registered store. |

The bare-`rag` status form is a CLI command, not a question for Claude.
The hook returns a `decision: "block"` envelope (Claude Code's documented
short-circuit) so the model is not invoked: zero tokens spent, no Claude
paraphrase, the user just sees the status text and the turn ends.

When you bare-`rag` in a folder that has no index yet, the hook also
fork-detaches the indexer right then, so a single `rag` is enough to
get setup started.

The `@<tag>` forms bypass auto-index; they assume you have already indexed
the stores you care about. Mostly for users running with `hydra-llm`.

`lax_trigger` (the no-colon form) is **on by default**. If you want to
turn it off, set `lax_trigger: false` in `~/.config/claude-rag-hook/config.yaml`
and use `rag: <q>` or `/rag <q>` instead.

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
  Debian). The first time you trigger a `rag <q>`, the hook will tell
  you about a one-time `pip install --user fastembed lancedb pyarrow`.

## Configuration (optional)

`~/.config/claude-rag-hook/config.yaml`. Defaults are inlined; a missing
file is not an error. Override only what you need:

```yaml
triggers: ["rag:", "/rag"]
lax_trigger: true                 # accept "rag <q>" without the colon
top_k: 5
retrieval:
  timeout_seconds: 8              # max time the hook will hold Claude on retrieval
embedder:
  kind: fastembed                 # or: openai-compatible, hydra-llm
  model: nomic-embed-text-v1.5
chunking:
  target_chars: 1500
  overlap_chars: 200
walker:
  max_file_size_mb: 1
  respect_gitignore: true
notifications:
  on_index_complete: true         # desktop notification (notify-send) on first index
```

## How it works under the hood

A few mechanics worth knowing, especially if the tool surprises you.

**The hook runs synchronously on every prompt.** Claude Code calls it,
waits for it to finish, then sends your prompt (plus whatever the hook
printed to stdout) to Claude. So a slow hook is a slow turn. The
retrieval path is wall-clock-capped at `retrieval.timeout_seconds`
(default 8s). Cold-start fastembed model loads can exceed that on the
first call after boot; the hook gives up cleanly and Claude answers
without retrieved context. Try `rag <q>` again and the second call is
typically 1-3s.

**Indexing is fork-detached.** When the hook decides to index a folder,
it forks a child process, calls `setsid` to put it in a new session,
redirects stdio to `~/.cache/claude-rag-hook/indexer.log`, and the
parent returns to Claude Code immediately. The child then walks, embeds,
and writes the LanceDB table. **Cancelling your Claude prompt does not
kill the indexer**: it has already detached. If you want to stop a
running indexing job, find it with `pgrep -af claude_rag_hook` and
`kill` it.

**Progress and discoverability.** While an indexing job runs, the
indexer writes a JSON file at `<scope>/.claude-rag-index/.progress`
that the hook reads on every subsequent invocation. Bare `rag` reports
this state. Non-`rag` prompts also get a small "[claude-rag-hook]
heads-up: still indexing..." banner prepended so Claude (and you) are
not in the dark. When indexing finishes, the hook fires a desktop
notification via `notify-send` if it is on PATH (one-time only, refreshes
stay silent). Disable with `notifications.on_index_complete: false`.

**Where things live.**

| Path | What |
|---|---|
| `<project>/.claude-rag-index/chunks.lance/` | the actual vector index (LanceDB) |
| `<project>/.claude-rag-index/.progress` | live state of any running job |
| `<project>/.claude-rag-index/.last_run.json` | stats from the most recent successful run |
| `<project>/.claude-rag-index/.last_refresh` | timestamp of last refresh attempt |
| `~/.cache/claude-rag-hook/indexer.log` | redirected stdout/stderr of the detached indexer |
| `~/.cache/claude-rag-hook/embedder.log` | embedder daemon log |
| `~/.config/claude-rag-hook/config.yaml` | optional user config |
| `/etc/claude-code/managed-settings.json` | machine-wide hook wiring |

## Pairs with hydra-llm

[hydra-llm](https://ra-yavuz.github.io/hydra-llm/) is the sibling project
for running local LLMs with RAG built in. The two tools are designed to
play together but are fully independent: each one writes to its own
index folder and neither auto-triggers the other.

**Two opt-in integration points.**

- **Embedder reuse:** set `embedder.kind: hydra-llm` and
  `embedder.hydra_id: <id>` in claude-rag-hook's config. The hook then
  resolves the embedder via `hydra-llm rag info <id>` and calls its
  `/v1/embeddings`. You stop pulling fastembed via pip and reuse
  whatever embedder you already run for hydra-llm.
- **Store reuse (read-only):** if a folder has a `.hydra-index/` instead
  of (or alongside) a `.claude-rag-index/`, claude-rag-hook reads it
  transparently when walking up looking for an index. hydra-llm users
  who have already indexed a folder do not need to re-index it for
  Claude Code.

**What does NOT happen automatically.**

- Indexing one folder with hydra-llm does **not** create a
  `.claude-rag-index/` there. claude-rag-hook only writes to its own
  directory.
- Indexing one folder with claude-rag-hook does **not** create a
  `.hydra-index/`. The interop direction is one-way: this hook reads
  hydra's stores, hydra does not (currently) read this hook's stores.
- Running `hydra-llm` against project A while you have a Claude session
  in project B has no effect on B's index. The two indexes are
  per-folder and isolated.

If you only see one tool today and want to know whether the index in
`<project>/.claude-rag-index/` came from hydra-llm: it didn't. That
directory is only ever written by claude-rag-hook itself. The hydra
equivalent is `.hydra-index/`.

Both integrations are optional. Standalone use is the default.

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
