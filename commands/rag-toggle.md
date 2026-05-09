---
description: Toggle claude-rag-hook auto-rag mode (every prompt becomes a `rag` query, no keyword needed). With no arguments, flips the current state. Pass `on`, `off`, or `status` for explicit control.
argument-hint: "[on|off|status]"
allowed-tools: Bash(crh rag *)
disable-model-invocation: true
---

# Toggle auto-rag

The user wants to flip claude-rag-hook's auto-rag toggle. Auto-rag, when on, treats every prompt the user submits as if they had typed `rag <prompt>`: claude-rag-hook retrieves chunks from the project's local index and prepends them before you see the prompt. Slash commands and very short prompts are not touched.

Run the toggle and report the result.

!`crh rag $ARGUMENTS`

After the command output above, briefly tell the user the new state in one sentence. Remind them they can re-run `/rag-toggle` any time to flip it back. They can also type `rag <q>` or `/rag <q>` (no toggle) for a one-shot retrieval at any time, regardless of toggle state.
