# claude-rag-hook

> **Type `rag <question>` in Claude Code. Get a retrieval-augmented answer.**
>
> A `UserPromptSubmit` hook for Claude Code that does keyword-triggered local
> RAG. The first `rag` query inside any project folder auto-indexes that
> folder in the background; the next `rag <q>` retrieves relevant chunks and
> prepends them to the prompt before Claude sees it. Local-first,
> deterministic, zero token overhead on prompts that do not start with the
> trigger.
>
> **Two surfaces, both on by default.** Type `rag <q>` for the cheap,
> deterministic, keyword-triggered path (zero overhead unless you ask). Or
> let Claude call the bundled MCP server (`rag_search`) when it judges that
> retrieval would help, your initial keyword search came up thin, or you
> never typed the keyword in the first place. The MCP path saves tokens by
> letting one Claude turn refine its own retrieval instead of asking you to
> start over. Toggle either surface with one command, any time.

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
| `rag` (alone) | Print index status. If no index exists yet, kick off indexing. **Ends the turn without invoking the model**, so it costs zero tokens. Same for `rag status` and `rag:`. |
| `/rag` (alone) | Toggle auto-rag mode (see below). Different from `rag` alone, which is a status report. |
| `rag@<tag>: <text>` | Federate retrieval across every store carrying `<tag>`. |
| `rag@all: <text>` | Federate across every registered store. |

The bare-`rag` status form is a CLI command, not a question for Claude.
The hook returns a `decision: "block"` envelope (Claude Code's documented
short-circuit) so the model is not invoked: zero tokens spent, no Claude
paraphrase, the user just sees the status text and the turn ends.

## Auto-rag mode (no keyword needed)

Once you've decided "this whole conversation is about my project", you
can flip auto-rag on and skip the keyword entirely:

```text
> /rag
auto-rag: ON
```

With auto-rag on, every prompt you submit in Claude Code is treated as
if you'd typed `rag <prompt>`: the hook retrieves relevant chunks and
prepends them before Claude sees the prompt. Slash commands (`/something`)
and very short prompts pass through untouched, so `/help`, `/clear`, and
"thanks" still work the way you expect.

Toggle it back off the same way: `/rag` once more, or `crh rag off` from
a shell. State persists across Claude Code sessions in
`$XDG_STATE_HOME/claude-rag-hook/toggles.json`.

```text
crh rag on        # turn on
crh rag off       # turn off
crh rag toggle    # flip
crh rag status    # show current state
```

## MCP server: model-decided retrieval

In addition to the keyword hook, claude-rag-hook ships a stdio MCP server
(`claude-rag-mcp`). Claude Code can call its `rag_search` tool when it
judges that retrieval would help and you did not type the keyword (or
the keyword retrieval came back thin and Claude wants a follow-up
search with a refined query).

Why both surfaces:

- The hook is best for known-need lookups: cheapest per-turn, zero
  overhead when you don't trigger it, deterministic.
- The MCP server is best for follow-up retrieval inside an ongoing
  Claude turn. If the keyword RAG returned three chunks and Claude
  realises a fourth angle would help, it can ask without you starting
  a new turn from scratch. That saves tokens.

The MCP server is on by default. The hook auto-registers it into your
per-user `~/.claude.json` on first invocation (idempotent, ~1 ms; the
package's apt postinst cannot reach into per-user home directories so
this happens lazily on the next hook run).

Tools exposed:

| Tool | When Claude should call it |
|---|---|
| `rag_search` | The user's question hinges on project-specific code/text and either (a) keyword retrieval came up thin and Claude wants a refined query, or (b) the user did not type `rag` but the answer requires knowing this codebase. |
| `rag_status` | Confirm an index exists for a folder before calling `rag_search` against it. |
| `rag_list_stores` | Inspect what's been indexed. Useful to call `rag_search` against a different project than cwd via the `scope` argument. |

Toggle the MCP server off if you don't want Claude to be able to retrieve
on its own:

```text
crh mcp off       # disabled (entry stays in ~/.claude.json with a kill-switch env var)
crh mcp on        # back on
crh mcp status    # show current state and registration
```

When off, the entry is still present in `~/.claude.json` but the spawned
process exits immediately, so Claude sees no `rag_*` tools. Only the
keyword-triggered hook remains active.

## Operator CLI: `crh`

apt install puts a `crh` binary on `$PATH`. The hook handles everything
inside Claude Code; `crh` is for the operator side: watch indexing
progress, run blocking refreshes for scripts, query the store, manage
the auto-refresh daemon, diagnose the install.

```text
crh status                  # one-liner state of the cwd's index
crh status --watch          # live-redrawing progress display until done
crh status --all            # state of every registered store
crh index [path]            # blocking initial index, with progress bar
crh refresh [path]          # blocking incremental refresh
crh query "retry policy"    # one-shot retrieval to stdout (same chunks the hook injects)
crh ls                      # list registered stores with chunk/file counts
crh tag <path> work         # tag a store for `rag@work: <q>` federation
crh untag <path> work
crh forget <path>           # delete an index, with confirmation
crh doctor                  # diagnose: model cache, embedder, hook wiring, orphan procs

crh refresh --rebuild       # drop the existing index and rebuild from scratch
crh index --rebuild         # same on initial-index command

crh rag on|off|toggle|status     # auto-rag mode (every prompt becomes a `rag` query)
crh mcp on|off|toggle|status     # MCP server (model-decided retrieval)

crh export [path] [-o file]      # bundle the project's index into a portable archive
crh import <bundle> [path]       # install a bundle a colleague shared with you
```

## Sharing an index (`crh export` / `crh import`)

Indexing a large monorepo can take minutes to hours. Embedding 50,000
files burns CPU (or GPU) on whoever runs it first. `crh export` and
`crh import` let one person pay that cost and everyone else benefit.

The flow:

```text
# Sender. From inside the indexed project:
cd ~/regurio-monorepo
crh export
# -> exported /home/alice/regurio-monorepo to
#    ./regurio-monorepo.BAAI-bge-small-en-v1.5.v1.20260509-093850.crh.tar.zst (71.4 MB)

# Or pick where the file lands:
crh export --output ~/share/   # writes the auto-named bundle into ~/share/
crh export -o ./my-bundle.crh.tar.zst   # exact filename

# Receiver. They install claude-rag-hook (apt or curl), check out the
# same project somewhere, cd into it, and run import:
cd ~/regurio-monorepo
crh import ~/Downloads/regurio-monorepo.BAAI-bge-small-en-v1.5.v1.20260509-093850.crh.tar.zst
# -> imported into /home/bob/regurio-monorepo/.claude-rag-index
#    registered in stores.json; type `rag <question>` to use it.
```

That's the whole loop. The receiver does not need to type the keyword
once to "kick off indexing"; the imported index is ready immediately.
`rag <q>` retrieves from it on the first try.

**How `crh import` decides where the index goes.** The receiver's
**current working directory** is the destination. The bundle records
the sender's project name for display, but cwd is authoritative; the
receiver's checkout can be at a different path or even renamed. Pass
an explicit second argument to override: `crh import <bundle> <path>`.

**Bundle contents.** A `tar.zst` (or `tar.gz` if `zstd` is missing)
containing `claude-rag-index/` plus a small `bundle.json` with the
source project name, embedder model, and timestamp. The receiver's
`crh import`:

- refuses to overwrite an existing populated `.claude-rag-index/`
  without `--force`;
- registers the store in `~/.local/state/claude-rag-hook/stores.json`
  so `crh ls` and tag-federated retrieval see it;
- prints a one-line heads-up if the bundle's embedder differs from
  the receiver's configured default. Mixed indexes coexist: each
  index records its own embedder in `meta.yaml`, and the retrieval
  path picks the right one per-index.

**What's not in the bundle.** Source code is not packed. The bundle
holds embeddings, chunked text, the file manifest, and the embedder
metadata. That is still derived from your source: if the project
contains secrets or private content, those leak through chunks and
the bundle inherits the same trust boundary as the source. Treat it
like the repo.

`--rebuild` is the migration knob when the embedder model changes
(eg. you switched the configured embedder, or upgraded across a
release that changed the default). It re-embeds every file rather
than skipping unchanged ones.

Auto-refresh daemon (off by default, opt-in):

```text
crh refresher start         # systemctl --user enable --now claude-rag-hook-refresher
crh refresher stop
crh refresher status        # systemd state + watched-projects summary
crh auto on [path]          # opt this project into the daemon (drops a marker file)
crh auto off [path]         # opt out
```

The refresher is a per-user systemd unit running at `Nice=19` /
`CPUSchedulingPolicy=idle` / `IOSchedulingClass=idle`, with a 60s
post-change quiet period and a hard 5-minute floor between refreshes
per project. It only watches projects you explicitly opted in. See
`/usr/lib/systemd/user/claude-rag-hook-refresher.service` for the
full sandbox profile.

Resilience: indexer runs persist their file manifest on a throttled
checkpoint cadence (every 16 files / 2s), atomically. If the indexer
is killed mid-flight (kill, OOM, system crash, power off), `crh
refresh` resumes from the last checkpoint instead of re-indexing
already-completed files. `crh status` reports the `[interrupted]`
state when this happens.

When you bare-`rag` in a folder that has no index yet, the hook also
fork-detaches the indexer right then, so a single `rag` is enough to
get setup started.

The `@<tag>` forms bypass auto-index; they assume you have already indexed
the stores you care about. Mostly for users running with `hydra-llm`.

`lax_trigger` (the no-colon form) is **on by default**. If you want to
turn it off, set `lax_trigger: false` in `~/.config/claude-rag-hook/config.yaml`
and use `rag: <q>` or `/rag <q>` instead.

## Does Claude Code self-update break the hook?

No. The hook lives at `/usr/lib/claude-rag-hook/claude-rag-hook-hook`
and is wired into `/etc/claude-code/managed-settings.json`. The MCP
server is referenced by absolute path from `~/.claude.json`. Claude
Code's own self-update mechanism replaces its binary in
`~/.local/share/claude-code/` (or wherever the user installed it)
and rewrites its session caches. It **does not touch**
`/etc/claude-code/managed-settings.json`, the user's
`~/.claude/settings.json`, or `~/.claude.json`. So:

- A Claude Code update does not delete the hook entry from
  `managed-settings.json`. The hook keeps firing.
- A Claude Code update does not delete the `claude-rag` MCP entry
  from `~/.claude.json`. Even if it did, the hook re-registers it
  on the next prompt-submit (idempotent self-install).
- The `/rag` slash command at `~/.claude/commands/rag.md` is also
  re-installed on the next prompt-submit if it disappears.

The reverse is also true: an `apt upgrade claude-rag-hook` does not
touch any of Claude Code's own state. The two tools update on their
own schedules and don't fight over each other's files.

## What the apt install actually does

- Installs the hook binary at `/usr/lib/claude-rag-hook/claude-rag-hook-hook`.
  Installs the MCP server binary at `/usr/lib/claude-rag-hook/claude-rag-mcp`.
  Installs the operator CLI at `/usr/bin/crh`. The hook and MCP binaries
  are not on `$PATH`; Claude Code invokes them directly.
- Merges a hook entry into `/etc/claude-code/managed-settings.json`. That
  file is read by Claude Code for every user on the machine, with the
  highest precedence in the settings layer. Existing entries (other tools,
  admin policies) are preserved; `apt remove` removes only our entry.
- Ships `/usr/lib/claude-rag-hook/commands/rag.md`, the `/rag` slash
  command source. The hook self-installs a copy into each user's
  `~/.claude/commands/rag.md` on first run (idempotent; only writes when
  the shipped content differs from what's there).
- The MCP server is wired in per-user via `~/.claude.json`. The hook
  auto-registers it on first run because apt postinst runs as root and
  cannot reliably write to every user's home directory. Idempotent;
  you can also drive it explicitly with `crh mcp on|off`.
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
  model: BAAI/bge-small-en-v1.5   # default since v0.5.0; ~33M params, 384 dim
  query_prefix: "Represent this sentence for searching relevant passages: "
  document_prefix: ""             # BGE: no prefix on documents
  fastembed_batch_size: 4         # ONNX workspace cap; raise on big-RAM hosts
chunking:
  target_chars: 1500
  overlap_chars: 200
walker:
  max_file_size_mb: 1
  respect_gitignore: true
notifications:
  on_index_complete: true         # desktop notification (notify-send) on first index
```

To use the previous default (`nomic-embed-text-v1.5`, 137M params,
768-dim, 8192-token context, ~1-point higher MTEB retrieval score):

```yaml
embedder:
  kind: fastembed
  model: nomic-ai/nomic-embed-text-v1.5
  query_prefix: "search_query: "
  document_prefix: "search_document: "
```

When you switch the configured embedder against an existing index,
`crh status` will surface a one-line hint that the index was built
with the previous embedder and tell you to run `crh refresh --rebuild`
to migrate. Old indexes keep working until you migrate; the retrieval
path picks the right embedder per-index from the recorded `meta.yaml`.

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

## Standalone, with optional hydra-llm hooks

claude-rag-hook is fully standalone. You install it with `apt install
claude-rag-hook` (or the curl-pipe-bash one-liner from the project
page), have Docker available so the embedder can run if you want a
heavier model, and you're done. There is no required dependency on
[hydra-llm](https://ra-yavuz.github.io/hydra-llm/).

If you happen to also run hydra-llm for local LLMs, two small bridges
let the two tools stop duplicating work, but neither is needed:

- **Embedder reuse:** set `embedder.kind: hydra-llm` and
  `embedder.hydra_id: <id>` in claude-rag-hook's config. The hook then
  calls hydra-llm's `/v1/embeddings` instead of pulling its own
  fastembed copy. Saves ~80 MB of duplicated ONNX cache and one extra
  process.
- **Read existing hydra indexes:** if a folder already has a
  `.hydra-index/` from prior hydra-llm use, the hook will read it
  rather than asking you to re-index into a `.claude-rag-index/`.
  Read-only; the hook still writes to its own directory when it
  indexes.

That's the whole "integration": shared embedders if you want, and the
hook can read hydra's existing stores. Each tool keeps its own
indexes; running one does not trigger the other; running them on
separate projects has no cross-effect. If both are installed and you
do nothing, they coexist quietly. If you opt into the bridges above,
you save a bit of disk and one process. That's it.

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
- The bundled MCP server (`claude-rag-mcp`) lets Claude trigger
  retrieval on its own. With the MCP server on (default), Claude can
  decide to read indexed content even on prompts where you did not type
  `rag`. Turn it off with `crh mcp off` if you only want retrieval to
  fire when you explicitly ask for it.
- Auto-rag mode (off by default; toggle with `/rag` or `crh rag on`)
  treats every prompt you submit as if you'd typed `rag <prompt>`.
  Every turn injects retrieved chunks. Good for project-focused
  sessions; turn off when you switch contexts so unrelated questions
  don't pull project content into your prompt.
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
