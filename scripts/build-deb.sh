#!/usr/bin/env bash
# Build a .deb without debhelper. Mirrors what the dh-python build would
# produce: ships the Python package under /usr/lib/claude-rag-hook (we
# bootstrap sys.path from bin/ so we do not need to fight dist-packages).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -nE '1 s/^[^(]*\(([^)]+)\).*/\1/p' "$ROOT/debian/changelog")
[ -n "$VERSION" ] || { echo "could not parse version from debian/changelog" >&2; exit 1; }
# Strip the Debian revision (-1, -2, ...) for the package filename.
DEB_VERSION="$VERSION"

PKG_DIR="$ROOT/dist/claude-rag-hook_${DEB_VERSION}_all"
DEB_OUT="$ROOT/dist/claude-rag-hook_${DEB_VERSION}_all.deb"

rm -rf "$PKG_DIR" "$DEB_OUT"
mkdir -p "$PKG_DIR/DEBIAN" \
         "$PKG_DIR/usr/bin" \
         "$PKG_DIR/usr/lib/claude-rag-hook/claude_rag_hook" \
         "$PKG_DIR/usr/lib/claude-rag-hook/claude_rag_hook/embedder" \
         "$PKG_DIR/usr/share/doc/claude-rag-hook"

install -m 0755 "$ROOT/bin/claude-rag-hook"  "$PKG_DIR/usr/bin/claude-rag-hook"
install -m 0755 "$ROOT/bin/claude-rag-hookd" "$PKG_DIR/usr/bin/claude-rag-hookd"

# Copy the Python package tree.
cp -a "$ROOT/lib/claude_rag_hook/." "$PKG_DIR/usr/lib/claude-rag-hook/claude_rag_hook/"

# Hook template, README, license.
mkdir -p "$PKG_DIR/usr/share/claude-rag-hook"
install -m 0644 "$ROOT/hooks/user-prompt-submit.template.json" \
                "$PKG_DIR/usr/share/claude-rag-hook/user-prompt-submit.template.json"
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
Description: keyword-triggered local RAG hook for Claude Code
 Type "rag: <question>" in Claude Code; the hook walks back through
 your cwd, looks for a per-folder LanceDB index, embeds the query,
 retrieves the top-K relevant chunks, and prepends them to the prompt
 as a context block before Claude sees it. Cheap, deterministic,
 local-first.
 .
 Unlike MCP-driven local RAG (where the model decides when to retrieve)
 the hook is keyword-triggered: the user types the trigger, the hook
 retrieves; otherwise it is a no-op. Zero token overhead on prompts
 that do not start with the trigger.
 .
 Ships with a fastembed embedder (lazy import; install via pip extras),
 an OpenAI-compatible /v1/embeddings client, and an optional hydra-llm
 interop layer that reuses an installed embedder catalog and per-folder
 .hydra-index/ stores. A small per-user warm daemon keeps the embedder
 loaded for sub-second retrieval.
 .
 DISCLAIMER: provided AS IS, no warranty. Reads files inside any folder
 you index and stores chunked text plus embeddings of those files at
 <folder>/.claude-rag-index/. Retrieved chunks are sent to Anthropic
 when the trigger fires. The author is not liable for any damage to
 data, hardware, or system, or for the content of model output. Audit
 what you index. See /usr/share/doc/claude-rag-hook/README.md.
EOF

: > "$PKG_DIR/DEBIAN/conffiles"

dpkg-deb --build --root-owner-group "$PKG_DIR" "$DEB_OUT"
echo
echo "Built: $DEB_OUT"
ls -la "$DEB_OUT"
