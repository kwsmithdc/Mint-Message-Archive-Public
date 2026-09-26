#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "Mint Message Archive — Regression Test Suite"
echo "============================================"
echo

echo "[1/5] Python runtime and syntax"
python3 - <<'PY'
import sys

if sys.version_info[:2] != (3, 12):
    raise SystemExit(
        f"Python 3.12 is required by the Linux server; found {sys.version.split()[0]}"
    )

import cgi  # noqa: F401
PY
python3 -m compileall -q linux-server
echo "PASS: Python syntax"
echo

echo "[2/5] Linux server unit/regression tests"
python3 -m unittest discover -s linux-server -p 'test_*.py' -v
echo "PASS: Linux server tests"
echo

echo "[3/5] Database initialization smoke test"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
python3 linux-server/database.py "$tmpdir"
test -f "$tmpdir/archive.db"
python3 - "$tmpdir/archive.db" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
required = {
    "devices",
    "archives",
    "messages",
    "mms_parts",
    "message_participants",
    "attachments",
}

with sqlite3.connect(path) as connection:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing = required - tables
    if missing:
        raise SystemExit(
            "Missing required database tables: " + ", ".join(sorted(missing))
        )

    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"SQLite integrity check failed: {result}")
PY
echo "PASS: Database initialization and SQLite integrity"
echo

echo "[4/5] Repository security checks"
if grep -RInE --exclude-dir=.git --exclude='*.pyc' --exclude='test_*.py' \
    -e '/home/[^<[:space:]]+' \
    -e 'Bearer [A-Za-z0-9._-]{40,}' \
    -e 'Samsung Galaxy S21' \
    -e '178.6 MiB' \
    -e '3,032 SMS' \
    -e '3,552 MMS' \
    android linux-server README.md CHANGELOG.md docs >/tmp/mma-security-matches.txt 2>/dev/null; then
    echo "WARNING: Possible installation-specific path, device ID, or credential found:"
    cat /tmp/mma-security-matches.txt
    rm -f /tmp/mma-security-matches.txt
    exit 1
fi
rm -f /tmp/mma-security-matches.txt
echo "PASS: No obvious installation-specific paths, device IDs, or bearer tokens"
echo

echo "============================================"
echo "RESULT: PASS"
