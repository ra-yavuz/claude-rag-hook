#!/usr/bin/env bash
# Build a .deb without debhelper.
#
# Layout shipped:
#   /usr/bin/crh                                     (operator-facing CLI)
#   /usr/lib/claude-rag-hook/claude-rag-hook-hook    (Claude Code invokes)
#   /usr/lib/claude-rag-hook/claude-rag-hook-admin   (postinst/postrm only)
#   /usr/lib/claude-rag-hook/claude-rag-hookd        (auto-spawned daemon)
#   /usr/lib/claude-rag-hook/claude_rag_hook/        (Python package)
#   /usr/lib/systemd/user/claude-rag-hook-refresher.service (auto-refresh daemon, off by default)
#   /usr/share/doc/claude-rag-hook/{README.md,DESIGN.md,copyright}
#
# The hook is wired into Claude Code via /etc/claude-code/managed-settings.json
# by the postinst (zero-touch). The CLI (`crh`) is for operator tasks:
# watch indexing progress, manage tags, run the auto-refresh daemon.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -nE '1 s/^[^(]*\(([^)]+)\).*/\1/p' "$ROOT/debian/changelog")
[ -n "$VERSION" ] || { echo "could not parse version from debian/changelog" >&2; exit 1; }
DEB_VERSION="$VERSION"

PKG_DIR="$ROOT/dist/claude-rag-hook_${DEB_VERSION}_all"
DEB_OUT="$ROOT/dist/claude-rag-hook_${DEB_VERSION}_all.deb"

rm -rf "$PKG_DIR" "$DEB_OUT"
mkdir -p "$PKG_DIR/DEBIAN" \
         "$PKG_DIR/usr/bin" \
         "$PKG_DIR/usr/lib/claude-rag-hook/claude_rag_hook/embedder" \
         "$PKG_DIR/usr/lib/claude-rag-hook/claude_rag_hook/cli" \
         "$PKG_DIR/usr/lib/claude-rag-hook/commands" \
         "$PKG_DIR/usr/lib/systemd/user" \
         "$PKG_DIR/usr/share/doc/claude-rag-hook"

install -m 0755 "$ROOT/bin/claude-rag-hook-hook"  "$PKG_DIR/usr/lib/claude-rag-hook/claude-rag-hook-hook"
install -m 0755 "$ROOT/bin/claude-rag-hook-admin" "$PKG_DIR/usr/lib/claude-rag-hook/claude-rag-hook-admin"
install -m 0755 "$ROOT/bin/claude-rag-hookd"      "$PKG_DIR/usr/lib/claude-rag-hook/claude-rag-hookd"
install -m 0755 "$ROOT/bin/claude-rag-mcp"        "$PKG_DIR/usr/lib/claude-rag-hook/claude-rag-mcp"
install -m 0755 "$ROOT/bin/crh"                   "$PKG_DIR/usr/bin/crh"

# /rag slash command markdown shipped under /usr/lib/claude-rag-hook/commands/.
# The hook self-installs a copy into each user's ~/.claude/commands/ on
# first invocation (idempotent; only writes when content differs).
install -m 0644 "$ROOT/commands/rag-toggle.md" "$PKG_DIR/usr/lib/claude-rag-hook/commands/rag-toggle.md"

# systemd user unit for the auto-refresh daemon. Off by default;
# users opt in with `crh refresher start` (which is `systemctl --user
# enable --now`). Per-project opt-in is a marker file inside the
# project's index dir; see `crh auto on`.
install -m 0644 "$ROOT/debian/claude-rag-hook-refresher.service" \
    "$PKG_DIR/usr/lib/systemd/user/claude-rag-hook-refresher.service"

# Copy the package tree, excluding bytecode caches (which accumulate
# stale .pyc files for renamed/removed modules and would ship them).
( cd "$ROOT/lib" && find claude_rag_hook -type f -name '*.py' -print0 | \
    xargs -0 -I {} install -D -m 0644 "{}" "$PKG_DIR/usr/lib/claude-rag-hook/{}" )

install -m 0644 "$ROOT/README.md"  "$PKG_DIR/usr/share/doc/claude-rag-hook/README.md"
install -m 0644 "$ROOT/DESIGN.md"  "$PKG_DIR/usr/share/doc/claude-rag-hook/DESIGN.md"
install -m 0644 "$ROOT/LICENSE"    "$PKG_DIR/usr/share/doc/claude-rag-hook/copyright"
install -m 0755 "$ROOT/debian/postinst" "$PKG_DIR/DEBIAN/postinst"
install -m 0755 "$ROOT/debian/postrm"   "$PKG_DIR/DEBIAN/postrm"

cat > "$PKG_DIR/DEBIAN/control" <<EOF
Package: claude-rag-hook
Version: ${DEB_VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-yaml, python3-numpy, python3-pathspec
Recommends: python3-pip
Suggests: hydra-llm
Maintainer: Ramazan Yavuz <yavuzramazan1994@gmail.com>
Homepage: https://ra-yavuz.github.io/claude-rag-hook/
Description: keyword-triggered local RAG inside Claude Code
 Type "rag: <question>" inside Claude Code; this hook embeds the query,
 retrieves the top relevant chunks from a local LanceDB index of your
 project folder, and prepends them to the prompt before Claude sees it.
 Local-first; the model never has to "decide" whether to retrieve, so
 there is no MCP round trip and no per-prompt token overhead on prompts
 that do not start with the trigger.
 .
 Auto-indexing on first use: the first "rag:" inside a project folder
 (one with a .git, pyproject.toml, package.json, or similar marker)
 fork-detaches a background indexer; the next "rag:" retrieves
 normally. Hard refusals on \$HOME, /etc, /var, etc., and a 20k-file /
 500MB cap protect against accidental indexing of large or sensitive
 trees.
 .
 Wires itself into Claude Code on apt install by merging an entry into
 /etc/claude-code/managed-settings.json. Every user on the machine
 picks up the hook on their next Claude Code session; no per-user
 setup. Removing the package removes the entry.
 .
 The fastembed embedder (the default) is not packaged for Debian; it
 is fetched on first use via pip if missing. To pre-install:
   pip install --user fastembed lancedb pyarrow
 Or pick a different embedder backend (OpenAI-compatible local server,
 hydra-llm interop) in ~/.config/claude-rag-hook/config.yaml.
 .
 DISCLAIMER: provided AS IS, no warranty. Reads files inside any folder
 it indexes and stores chunked text plus embeddings of those files at
 <folder>/.claude-rag-index/. Retrieved chunks are sent to Anthropic
 when "rag:" fires. The author is not liable for any damage to data,
 hardware, system, or for the content of model output. Audit what you
 index. See /usr/share/doc/claude-rag-hook/README.md.
EOF

: > "$PKG_DIR/DEBIAN/conffiles"

dpkg-deb --build --root-owner-group "$PKG_DIR" "$DEB_OUT"
echo
echo "Built: $DEB_OUT"
ls -la "$DEB_OUT"
