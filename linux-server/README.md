# Linux Mint receiver

The Linux component receives Android message archives, preserves the original ZIP files, indexes SMS/MMS data in SQLite, and provides a polished local web interface for searching the archive.

## Network isolation and privacy

Mint Message Archive is intentionally a **LAN-only archive system**. The Android phone and Linux archive server are expected to communicate directly over the trusted home network. Internet connectivity is not required for archive transfers, SQLite indexing, searching, or viewing the local web archive.

The archive server should not be exposed to the public Internet. Do not configure port forwarding, public DNS, or another Internet-facing path to the upload or web interface. The Linux receiver also rejects HTTP requests from non-private/non-local client addresses, providing an application-level LAN boundary in addition to the firewall. The project does not use cloud storage, third-party archive services, or external telemetry for the archive data path.

The Linux host may have ordinary Internet access for unrelated operating-system maintenance, but Mint Message Archive itself must not send message content, attachments, or other personal archive data to Internet services.

This isolation is a core project requirement and should be preserved when adding future features.

## Runtime requirement

The Linux archive server requires **Python 3.12**. The server currently uses Python standard-library multipart parsing provided by the `cgi` module, which was removed in Python 3.13. The automated regression suite checks this requirement so the project does not silently drift to an incompatible Python runtime.

## Quick start

    mkdir -p "$HOME/mint-message-archive"
    cp server.py database.py web.py maintenance.py verify_archive.py health_report.py rebuild_database.py "$HOME/mint-message-archive/"
    mkdir -p "$HOME/Archive"

Create a long random token:

    python3 -c 'import secrets; print(secrets.token_urlsafe(32))'

Start the receiver:

    python3 "$HOME/mint-message-archive/server.py" \
      --bind 0.0.0.0 \
      --port 8765 \
      --archive "$HOME/Archive" \
      --token 'PASTE-YOUR-TOKEN-HERE'

Check it locally:

    curl http://127.0.0.1:8765/health

Find the laptop IP:

    hostname -I

Then configure the Android app to upload to:

    http://LAPTOP-IP:8765/upload

## Web archive interface

The same server provides the searchable archive interface at:

    http://LAPTOP-IP:8765/

The web interface supports:

* Keyword and message-text search
* Phone/device selection
* SMS, MMS, and future RCS filtering
* Sender/recipient/contact filtering
* Date-range filtering
* Attachment filtering
* Paginated results
* Individual message details
* MMS participant display
* Attachment viewing from the preserved ZIP archive
* Attachment gallery with inline image, video, and audio previews
* Download controls for archived attachments
* Responsive desktop and mobile layouts
* Automatic light/dark appearance based on the browser preference

The interface is intentionally dependency-free and uses the Python standard library, keeping the Linux server simple to maintain.

### Web authentication

Android uploads continue to use the bearer token. Web browsers use HTTP Basic authentication so the browser can display its normal secure login prompt.

Use:

    Username: archive
    Password: the same token loaded from the protected token file

Do not put the token in a URL or commit it to the repository.

## systemd user service

The included service loads the production token from `~/.config/mint-message-archive/server.token`. The token is intentionally kept outside the repository and outside the systemd unit file.

Install:

    mkdir -p "$HOME/.config/systemd/user"
    cp mint-message-archive.service "$HOME/.config/systemd/user/"
    systemctl --user daemon-reload
    systemctl --user enable --now mint-message-archive.service
    systemctl --user status mint-message-archive.service

If you want it to run without an interactive login, enable lingering:

    loginctl enable-linger "$USER"

## Automated archive health verification

The repository includes a user-level systemd service and timer that run the read-only health report weekly. The scheduled check runs the integrity verifier and duplicate scanner and writes its output to the systemd journal. It does not modify SQLite records or preserved ZIP archives.

Install the health-check service and timer:

    mkdir -p "$HOME/.config/systemd/user"
    cp mint-message-archive-health.service mint-message-archive-health.timer \
      "$HOME/.config/systemd/user/"
    systemctl --user daemon-reload
    systemctl --user enable --now mint-message-archive-health.timer

Check the timer:

    systemctl --user list-timers mint-message-archive-health.timer

Run the health check immediately:

    systemctl --user start mint-message-archive-health.service

View the most recent health-check output:

    journalctl --user -u mint-message-archive-health.service -n 100 --no-pager

The timer runs weekly on Sunday at approximately 3:00 AM local time, with a randomized delay of up to 15 minutes. The timer is persistent, so a missed run can be triggered after the system becomes available again.

## UFW

If UFW is enabled:

    sudo ufw allow from 192.168.1.0/24 to any port 8765 proto tcp

Replace `192.168.1.0/24` with your actual trusted home LAN subnet. Avoid a broad `sudo ufw allow 8765/tcp` rule unless there is a specific local-network reason to permit the port from every reachable network interface.

## Archive and database layout

The server preserves the original uploaded ZIP archives and maintains a SQLite search index alongside them.

A typical archive root looks like:

    Archive/
    ├── archive.db
    └── devices/
        └── <device-id>/
            ├── device.json
            └── archives/
                └── YYYY-MM-DD/
                    ├── message-archive-....zip
                    └── received.jsonl

The ZIP files remain the authoritative preserved message data. SQLite is an index used to make searching fast.

## Preserved archive inventory

`archive_inventory.py` provides a read-only inventory of the preserved ZIP archives directly from the `devices/` archive tree. It does not require `archive.db`, making it useful when inspecting or recovering an archive whose SQLite index is unavailable.

For each device and preserved ZIP, the inventory reports:

* Device ID and alias
* Archive filename and date directory
* Preserved ZIP size
* ZIP member count
* Original server receive timestamp from `received.jsonl`, when available
* Upload source address from `received.jsonl`, when available
* Indexed SMS, MMS, MMS-part, participant, and attachment counts from preserved receive metadata

Each ZIP is opened and CRC-checked while the inventory is built. The tool does not modify or delete any archive data.

Run it with:

    python3 "$HOME/mint-message-archive/archive_inventory.py" \
      --archive "$HOME/Archive"

For machine-readable output:

    python3 "$HOME/mint-message-archive/archive_inventory.py" \
      --archive "$HOME/Archive" \
      --json

Run the regression test with:

    python3 -m unittest "$HOME/mint-message-archive/test_archive_inventory.py"

The inventory remains useful even if `archive.db` must be rebuilt, because its authoritative input is the preserved ZIP archive tree and its accompanying device/receive metadata.

## Archive health report

`health_report.py` provides a single read-only operational summary of the archive. By default it runs the archive integrity verifier and duplicate scanner and reports:

* Device and archive counts
* SMS/MMS/RCS message counts by indexed message type
* MMS parts, participants, and attachments
* Archive storage size
* Oldest and newest indexed messages
* Oldest and newest received archives
* Integrity status and any missing/corrupt references
* Duplicate-maintenance status

Run it with:

    python3 "$HOME/mint-message-archive/health_report.py" \
      --archive "$HOME/Archive"

For machine-readable output:

    python3 "$HOME/mint-message-archive/health_report.py" \
      --archive "$HOME/Archive" \
      --json

For a faster report without the duplicate scan:

    python3 "$HOME/mint-message-archive/health_report.py" \
      --archive "$HOME/Archive" \
      --skip-duplicates

For a full recovery-readiness check, the report can rebuild the SQLite index in a temporary directory and compare it with production:

    python3 "$HOME/mint-message-archive/health_report.py" \
      --archive "$HOME/Archive" \
      --check-recovery

The recovery check is non-destructive. The temporary rebuilt database is removed automatically after comparison, and neither the production database nor preserved ZIP archives are modified.

The health report is read-only. It does not modify SQLite records or preserved ZIP archives.

## Database rebuild and recovery

`rebuild_database.py` reconstructs a fresh SQLite search index from the preserved ZIP archives. The original ZIP files are the authoritative archive source; SQLite is only the searchable index.

The rebuild is deliberately non-destructive:

* The preserved ZIP archives are never modified or deleted.
* The production `archive.db` is never opened for writing.
* A new database is created at the requested output path.
* The rebuilt database is checked with SQLite `PRAGMA integrity_check` before the command reports success.
* Device IDs and aliases are recovered from the archive manifest and device metadata.
* Original receive timestamps are recovered from `received.jsonl` when available, with the ZIP file modification time used as a fallback.

For a safe recovery test, first choose an output database outside the production archive database:

    python3 "$HOME/mint-message-archive/rebuild_database.py" \
      --archive "$HOME/Archive" \
      --output "/tmp/mint-message-archive-rebuilt.db"

A successful rebuild reports the number of devices, archives, SMS messages, MMS messages, MMS parts, participants, and attachments reconstructed from the preserved ZIP files.

The rebuilt database can then be inspected independently before any production database replacement is considered.

Run the included regression test with:

    python3 -m unittest "$HOME/mint-message-archive/test_rebuild_database.py"

Do not replace the production `archive.db` until the rebuilt database has been independently verified.

## Database comparison

`compare_databases.py` performs a read-only record-level comparison between a production database and a database rebuilt from the preserved ZIP archives.

The comparison deliberately ignores SQLite-generated row IDs. Foreign-key archive references are compared through the stable `device_id + filename` archive identity, so a rebuilt database can have different numeric `archive_id` values without being reported as a difference.

It compares:

* Device metadata
* Archive metadata
* SMS and MMS message fields
* MMS parts
* MMS participants
* Attachments

Run it after rebuilding:

    python3 "$HOME/mint-message-archive/compare_databases.py" \
      --production "$HOME/Archive/archive.db" \
      --rebuilt "/tmp/mint-message-archive-rebuilt.db"

A successful comparison reports `RESULT: PASS`. Any missing or extra record content produces `RESULT: DIFFERENCES FOUND` and a non-zero exit status.

The comparison is read-only and does not modify either database or any preserved ZIP archive.


## Archive integrity verification

`verify_archive.py` provides a read-only integrity check for the preserved archive and its SQLite index. It checks:

* SQLite `PRAGMA integrity_check` status
* Every database archive record points to an existing readable ZIP file
* ZIP CRC integrity for every preserved archive
* Message records with an archive reference point to a readable archive
* MMS parts with an archive member point to an existing ZIP member
* Indexed attachment records point to an existing ZIP member
* Attachment and MMS-part archive paths are safe relative paths

Run it with:

    python3 "$HOME/mint-message-archive/verify_archive.py" \
      --archive "$HOME/Archive"

The command is read-only. It does not modify SQLite records or the preserved ZIP archives. It exits with status `0` when all checks pass and a non-zero status when an integrity problem is found.

For machine-readable output:

    python3 "$HOME/mint-message-archive/verify_archive.py" \
      --archive "$HOME/Archive" \
      --json

## Production hardening

The current proof-of-concept uses HTTP on the trusted local network. Production credential handling supports a protected external token file. The intended security boundary is the trusted home LAN plus authentication and filesystem permissions; the receiver should **not** be exposed to the public Internet.

Do not add port forwarding or other Internet-facing access to port 8765. If remote access is ever considered, it should be treated as a separate architectural change and must not become part of the archive's normal data path.

Message archives can contain highly personal information. Restrict filesystem permissions, network access, and server access accordingly.
