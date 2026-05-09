#!/usr/bin/env bash
# Build the v0.7.0 transitional .deb for claude-rag-hook.
#
# v0.7 is a metapackage shim: it carries no binaries, no library code,
# and no hook wiring. Its only purpose is to depend on hydra-rag-hooks
# (the renamed successor) so that an existing claude-rag-hook install
# upgraded via `apt update` automatically pulls the new package, and
# then prints a one-line note telling the user about the rename.
#
# Layout shipped:
#   /usr/share/doc/claude-rag-hook/{README.md,copyright,RENAME.md}
#
# Postinst prints the rename note. Postrm is empty (apt remove just
# leaves the dependency satisfied; the user can also `apt remove
# hydra-rag-hooks` separately if they really want to uninstall).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -nE '1 s/^[^(]*\(([^)]+)\).*/\1/p' "$ROOT/debian/changelog")
[ -n "$VERSION" ] || { echo "could not parse version from debian/changelog" >&2; exit 1; }
DEB_VERSION="$VERSION"

PKG_DIR="$ROOT/dist/claude-rag-hook_${DEB_VERSION}_all"
DEB_OUT="$ROOT/dist/claude-rag-hook_${DEB_VERSION}_all.deb"

rm -rf "$PKG_DIR" "$DEB_OUT"
mkdir -p "$PKG_DIR/DEBIAN" \
         "$PKG_DIR/usr/share/doc/claude-rag-hook"

install -m 0644 "$ROOT/README.md" "$PKG_DIR/usr/share/doc/claude-rag-hook/README.md"
install -m 0644 "$ROOT/LICENSE"   "$PKG_DIR/usr/share/doc/claude-rag-hook/copyright"

# RENAME notice shipped alongside the docs. Any user who looks at
# /usr/share/doc/claude-rag-hook/ sees what happened and where to look.
cat > "$PKG_DIR/usr/share/doc/claude-rag-hook/RENAME.md" <<'EOF'
# claude-rag-hook has been renamed to hydra-rag-hooks

The claude-rag-hook v0.6.x feature set has been folded into a new
package, hydra-rag-hooks, which now supports both Anthropic's Claude
Code AND OpenAI's Codex CLI from a single apt install. v0.7.0 of
claude-rag-hook is a transitional metapackage that depends on
hydra-rag-hooks; installing or upgrading it automatically pulls the
new package.

What you should do:

  1. Verify the new package is installed:
       apt list --installed | grep hydra-rag-hooks
  2. Optionally remove this transitional name:
       sudo apt remove claude-rag-hook
     (your hooks, indexes, and config keep working: hydra-rag-hooks
     handles all of that, and your existing .claude-rag-index/
     folders are auto-renamed in place on first run.)
  3. New project page: https://ra-yavuz.github.io/hydra-rag-hooks/
  4. New repo: https://github.com/ra-yavuz/hydra-rag-hooks
EOF

cat > "$PKG_DIR/DEBIAN/control" <<EOF
Package: claude-rag-hook
Version: ${DEB_VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: hydra-rag-hooks (>= 0.1.0)
Maintainer: Ramazan Yavuz <yavuzramazan1994@gmail.com>
Homepage: https://ra-yavuz.github.io/hydra-rag-hooks/
Description: Transitional package - renamed to hydra-rag-hooks
 claude-rag-hook has been renamed to hydra-rag-hooks. The new package
 supports both Claude Code AND OpenAI's Codex CLI from one apt install,
 with the same hooks, retrieval pipeline, and crh operator CLI.
 .
 This v0.7.0 transitional package depends on hydra-rag-hooks so that
 \`apt update\` installs the new package automatically. After
 installation you can run \`apt remove claude-rag-hook\` to drop
 this transitional name; hydra-rag-hooks remains installed and
 handles the same workload, including auto-migration of existing
 .claude-rag-index/ folders to the unified .hydra-index/ name.
 .
 See https://ra-yavuz.github.io/hydra-rag-hooks/ for the new project.
EOF

cat > "$PKG_DIR/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
case "$1" in
    configure)
        cat <<NOTE

claude-rag-hook has been renamed to hydra-rag-hooks (now installed as
a dependency of this transitional package). The new package adds
OpenAI Codex CLI support alongside Claude Code, and migrates your
existing config and indexes in place on next use.

You can drop this transitional name when you are ready:
    sudo apt remove claude-rag-hook

See: https://ra-yavuz.github.io/hydra-rag-hooks/

NOTE
        ;;
    abort-upgrade|abort-remove|abort-deconfigure)
        ;;
esac
exit 0
EOF
chmod 0755 "$PKG_DIR/DEBIAN/postinst"

: > "$PKG_DIR/DEBIAN/conffiles"

dpkg-deb --build --root-owner-group "$PKG_DIR" "$DEB_OUT"
echo
echo "Built: $DEB_OUT"
ls -la "$DEB_OUT"
