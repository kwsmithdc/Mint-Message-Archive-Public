#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$HOME/mint-message-archive"
cp linux-server/server.py "$HOME/mint-message-archive/server.py"
chmod +x "$HOME/mint-message-archive/server.py"
echo "Installed server.py to $HOME/mint-message-archive/"
echo "Generate a token with:"
echo "  python3 -c 'import secrets; print(secrets.token_urlsafe(32))'"
