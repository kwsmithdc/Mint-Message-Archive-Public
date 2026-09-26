#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/kwsmithdc/Mint-Message-Archive-Public.git"
INSTALL_DIR="${MINT_MESSAGE_ARCHIVE_DIR:-$HOME/mint-message-archive}"
ARCHIVE_DIR="${MINT_MESSAGE_ARCHIVE_ARCHIVE:-$HOME/mint-message-archive-archive}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/mint-message-archive"
TOKEN_FILE="$CONFIG_DIR/server.token"
PORT="${MINT_MESSAGE_ARCHIVE_PORT:-8765}"

log() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[[ "$EUID" -ne 0 ]] || fail "Run this installer as your normal user, not as root."

install_packages=()
command -v git >/dev/null 2>&1 || install_packages+=(git)
command -v curl >/dev/null 2>&1 || install_packages+=(curl)
command -v python3 >/dev/null 2>&1 || install_packages+=(python3.12)
command -v ip >/dev/null 2>&1 || install_packages+=(iproute2)

if (( ${#install_packages[@]} > 0 )); then
    command -v sudo >/dev/null 2>&1 || fail "Missing required packages (${install_packages[*]}) and sudo is unavailable."
    log "Installing required Linux packages: ${install_packages[*]}"
    sudo apt-get update
    sudo apt-get install -y "${install_packages[@]}"
fi

command -v git >/dev/null 2>&1 || fail "Git is required."
command -v python3 >/dev/null 2>&1 || fail "Python 3 is required."

python3 - <<'PY'
import sys
if sys.version_info[:2] != (3, 12):
    raise SystemExit(
        f"Mint Message Archive requires Python 3.12; found {sys.version.split()[0]}"
    )
PY

if [[ -e "$INSTALL_DIR/.git" ]]; then
    log "Updating existing installation"
    git -C "$INSTALL_DIR" pull --ff-only
elif [[ -e "$INSTALL_DIR" ]]; then
    fail "$INSTALL_DIR already exists and is not a Git checkout. Move it aside or set MINT_MESSAGE_ARCHIVE_DIR."
else
    log "Downloading Mint Message Archive"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

log "Creating archive and configuration directories"
mkdir -p "$ARCHIVE_DIR" "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

if [[ ! -s "$TOKEN_FILE" ]]; then
    log "Generating a new local authentication token"
    umask 077
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$TOKEN_FILE"
fi
chmod 600 "$TOKEN_FILE"

log "Installing user services"
mkdir -p "$HOME/.config/systemd/user"
sed     -e "s#%h/mint-message-archive#$INSTALL_DIR#g"     -e "s#%h/mint-message-archive-archive#$ARCHIVE_DIR#g"     -e "s#%h/.config/mint-message-archive#$CONFIG_DIR#g"     "$INSTALL_DIR/linux-server/mint-message-archive.service"     > "$HOME/.config/systemd/user/mint-message-archive.service"

sed     -e "s#%h/mint-message-archive#$INSTALL_DIR#g"     -e "s#%h/mint-message-archive-archive#$ARCHIVE_DIR#g"     "$INSTALL_DIR/linux-server/mint-message-archive-health.service"     > "$HOME/.config/systemd/user/mint-message-archive-health.service"

cp "$INSTALL_DIR/linux-server/mint-message-archive-health.timer"    "$HOME/.config/systemd/user/mint-message-archive-health.timer"

systemctl --user daemon-reload
systemctl --user enable --now mint-message-archive.service
systemctl --user enable --now mint-message-archive-health.timer

if command -v sudo >/dev/null 2>&1 && command -v loginctl >/dev/null 2>&1; then
    sudo loginctl enable-linger "$USER" >/dev/null 2>&1 || true
fi

if command -v ufw >/dev/null 2>&1 && sudo ufw status 2>/dev/null | grep -q "Status: active"; then
    LAN_CIDR="$(ip -4 route show scope link 2>/dev/null | awk '$1 ~ /^[0-9]+\./ {print $1; exit}')"
    if [[ -n "$LAN_CIDR" ]]; then
        log "Allowing archive traffic from detected local network $LAN_CIDR"
        sudo ufw allow from "$LAN_CIDR" to any port "$PORT" proto tcp >/dev/null
    else
        printf '\nWARNING: Could not automatically determine the local IPv4 subnet for UFW.\n'
        printf 'The application still enforces local-network-only access.\n'
    fi
fi

log "Checking the archive server"
sleep 1
if ! curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    systemctl --user --no-pager --full status mint-message-archive.service || true
    fail "The archive server did not respond to its local health check."
fi

cat <<EOF

Mint Message Archive is installed.

Server code:
  $INSTALL_DIR

Archive storage:
  $ARCHIVE_DIR

Authentication token:
  $TOKEN_FILE

Server:
  http://<LINUX-IP>:$PORT/

Local health check:
  curl http://127.0.0.1:$PORT/health

View the token:
  cat "$TOKEN_FILE"

Service status:
  systemctl --user status mint-message-archive.service

The archive service accepts only local/private-network clients.
Do not expose port $PORT to the Internet.
EOF
