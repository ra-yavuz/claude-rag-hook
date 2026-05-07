#!/usr/bin/env bash
# claude-rag-hook one-line installer.
#
# Sets up the signed ra-yavuz apt repo if not already added, refreshes
# the package index, and installs claude-rag-hook. Idempotent.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ra-yavuz/claude-rag-hook/main/scripts/get.sh | sudo bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "This installer needs root (it writes to /etc/apt/). Re-run with sudo." >&2
    exit 1
fi

if ! command -v apt >/dev/null 2>&1; then
    echo "This installer is for Debian/Ubuntu derivatives (apt-based)." >&2
    echo "Other platforms: pip install --user 'claude-rag-hook[fastembed]'" >&2
    exit 1
fi

KEYRING=/etc/apt/keyrings/ra-yavuz.gpg
SOURCES=/etc/apt/sources.list.d/ra-yavuz.list

install -m 0755 -d /etc/apt/keyrings
if [ ! -s "$KEYRING" ]; then
    curl -fsSL https://ra-yavuz.github.io/apt/pubkey.gpg -o "$KEYRING"
fi
echo "deb [signed-by=$KEYRING] https://ra-yavuz.github.io/apt stable main" > "$SOURCES"
apt update
apt install -y claude-rag-hook

cat <<'EOF'

claude-rag-hook installed. Next steps:

  1. Wire the hook into Claude Code:
       claude-rag-hook install

  2. Index a folder you want Claude to retrieve from:
       cd ~/projects/your-app
       claude-rag-hook index .

  3. In Claude Code, opened anywhere under that folder, type:
       rag: <your question>

DISCLAIMER: provided as is, no warranty. RAG retrieves text from local
files and sends it to Anthropic when retrieval triggers. Audit what you
index. Full text on https://ra-yavuz.github.io/claude-rag-hook/.

EOF
