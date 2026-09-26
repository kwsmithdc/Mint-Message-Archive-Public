#!/usr/bin/env python3

import json
import sqlite3
import zipfile
from pathlib import Path, PurePosixPath


class ArchiveDatabase:
    def __init__(self, archive_root, database_path=None):
        self.archive_root = Path(archive_root).expanduser().resolve()
        self.database_path = (
            Path(database_path).expanduser().resolve()
            if database_path is not None
            else self.archive_root / "archive.db"
        )

    def connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self):
        self.archive_root.mkdir(parents=True, exist_ok=True)

        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    device_alias TEXT NOT NULL DEFAULT '',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS archives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    archive_path TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    FOREIGN KEY (device_id)
                        REFERENCES devices(device_id)
                        ON DELETE CASCADE,
                    UNIQUE(device_id, filename)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    archive_id INTEGER,
                    message_type TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    thread_id TEXT,
                    address TEXT,
                    body TEXT,
                    subject TEXT,
                    message_box INTEGER,
                    sms_type INTEGER,
                    sms_read INTEGER,
                    timestamp INTEGER,
                    FOREIGN KEY (device_id)
                        REFERENCES devices(device_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (archive_id)
                        REFERENCES archives(id)
                        ON DELETE SET NULL,
                    UNIQUE(device_id, message_type, message_id)
                );

                CREATE TABLE IF NOT EXISTS mms_parts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    archive_id INTEGER,
                    message_id TEXT NOT NULL,
                    part_id TEXT NOT NULL,
                    content_type TEXT,
                    name TEXT,
                    filename TEXT,
                    text TEXT,
                    archive_member TEXT,
                    size INTEGER,
                    FOREIGN KEY (device_id)
                        REFERENCES devices(device_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (archive_id)
                        REFERENCES archives(id)
                        ON DELETE SET NULL,
                    UNIQUE(device_id, message_id, part_id)
                );

                CREATE TABLE IF NOT EXISTS message_participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    address TEXT NOT NULL,
                    role TEXT NOT NULL,
                    FOREIGN KEY (device_id)
                        REFERENCES devices(device_id)
                        ON DELETE CASCADE,
                    UNIQUE(device_id, message_type, message_id, address, role)
                );

                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    archive_id INTEGER,
                    message_id TEXT,
                    part_id TEXT,
                    filename TEXT NOT NULL,
                    mime_type TEXT,
                    size INTEGER,
                    archive_path TEXT,
                    FOREIGN KEY (device_id)
                        REFERENCES devices(device_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (archive_id)
                        REFERENCES archives(id)
                        ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_device
                    ON messages(device_id);
                CREATE INDEX IF NOT EXISTS idx_messages_timestamp
                    ON messages(timestamp);
                CREATE INDEX IF NOT EXISTS idx_messages_address
                    ON messages(address);
                CREATE INDEX IF NOT EXISTS idx_messages_thread
                    ON messages(thread_id);
                CREATE INDEX IF NOT EXISTS idx_mms_parts_device
                    ON mms_parts(device_id);
                CREATE INDEX IF NOT EXISTS idx_mms_parts_message
                    ON mms_parts(message_id);
                CREATE INDEX IF NOT EXISTS idx_mms_parts_content_type
                    ON mms_parts(content_type);
                CREATE INDEX IF NOT EXISTS idx_participants_device
                    ON message_participants(device_id);
                CREATE INDEX IF NOT EXISTS idx_participants_message
                    ON message_participants(message_id);
                CREATE INDEX IF NOT EXISTS idx_participants_address
                    ON message_participants(address);
                CREATE INDEX IF NOT EXISTS idx_participants_role
                    ON message_participants(role);
                CREATE INDEX IF NOT EXISTS idx_attachments_device
                    ON attachments(device_id);
                CREATE INDEX IF NOT EXISTS idx_attachments_message
                    ON attachments(message_id);
                """
            )

            # The original attachment table predates part_id. Migrate an
            # existing database before creating the part_id index.
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(attachments)"
                )
            }
            if "part_id" not in columns:
                connection.execute(
                    "ALTER TABLE attachments ADD COLUMN part_id TEXT"
                )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_attachments_part
                    ON attachments(part_id)
                """
            )
            connection.commit()

    def register_device(self, device_id, device_alias, first_seen, last_seen):
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO devices (
                    device_id, device_alias, first_seen, last_seen
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    device_alias = excluded.device_alias,
                    last_seen = excluded.last_seen
                """,
                (device_id, device_alias, first_seen, last_seen),
            )
            connection.commit()

    def register_archive(self, device_id, filename, archive_path, received_at):
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO archives (
                    device_id, filename, archive_path, received_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (device_id, filename, archive_path, received_at),
            )
            connection.commit()

            row = connection.execute(
                """
                SELECT id FROM archives
                WHERE device_id = ? AND filename = ?
                """,
                (device_id, filename),
            ).fetchone()
            return None if row is None else row["id"]

    def import_sms(self, device_id, archive_id, sms_messages):
        imported = 0
        with self.connect() as connection:
            for message in sms_messages:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO messages (
                        device_id, archive_id, message_type, message_id,
                        thread_id, address, body, timestamp, subject,
                        message_box, sms_type, sms_read
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device_id,
                        archive_id,
                        "SMS",
                        str(message.get("id")),
                        message.get("threadId"),
                        message.get("address"),
                        message.get("body"),
                        message.get("date"),
                        None,
                        None,
                        message.get("type"),
                        message.get("read"),
                    ),
                )
                imported += cursor.rowcount
            connection.commit()
        return imported

    def import_mms(self, device_id, archive_id, mms_messages, archive_members=None):
        """Import MMS messages, parts, participants, and attachments."""
        archive_members = archive_members or {}
        imported_messages = 0
        imported_parts = 0
        imported_attachments = 0
        imported_participants = 0

        with self.connect() as connection:
            for message in mms_messages:
                message_id = str(message.get("id"))
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO messages (
                        device_id, archive_id, message_type, message_id,
                        thread_id, body, subject, message_box, timestamp
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device_id,
                        archive_id,
                        "MMS",
                        message_id,
                        message.get("threadId"),
                        None,
                        message.get("subject"),
                        message.get("messageBox"),
                        self._normalize_mms_timestamp(message.get("date")),
                    ),
                )
                imported_messages += cursor.rowcount

                for participant in message.get("addresses") or []:
                    if not isinstance(participant, dict):
                        continue
                    address = str(participant.get("address") or "").strip()
                    role = str(
                        participant.get("role")
                        or participant.get("type")
                        or "UNKNOWN"
                    ).upper()
                    if not address:
                        continue
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO message_participants (
                            device_id, message_type, message_id, address, role
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (device_id, "MMS", message_id, address, role),
                    )
                    imported_participants += cursor.rowcount

                for part in message.get("parts") or []:
                    if not isinstance(part, dict):
                        continue

                    part_id = str(part.get("id"))
                    content_type = part.get("contentType")
                    text = part.get("text")
                    archive_member = part.get("archiveFile")
                    if archive_member is not None:
                        archive_member = str(archive_member)

                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO mms_parts (
                            device_id, archive_id, message_id, part_id,
                            content_type, name, filename, text,
                            archive_member, size
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            device_id,
                            archive_id,
                            message_id,
                            part_id,
                            content_type,
                            part.get("name"),
                            part.get("filename"),
                            text,
                            archive_member,
                            None,
                        ),
                    )
                    imported_parts += cursor.rowcount

                    if archive_member:
                        safe_member = self._safe_archive_member(archive_member)
                        if safe_member and safe_member in archive_members:
                            size = archive_members[safe_member]
                            cursor = connection.execute(
                                """
                                INSERT OR IGNORE INTO attachments (
                                    device_id, archive_id, message_id, part_id,
                                    filename, mime_type, size, archive_path
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    device_id,
                                    archive_id,
                                    message_id,
                                    part_id,
                                    part.get("archiveFilename")
                                    or part.get("filename")
                                    or safe_member.rsplit("/", 1)[-1],
                                    part.get("archiveMimeType") or content_type,
                                    size,
                                    safe_member,
                                ),
                            )
                            imported_attachments += cursor.rowcount
                            connection.execute(
                                """
                                UPDATE mms_parts
                                SET size = ?
                                WHERE device_id = ?
                                  AND message_id = ?
                                  AND part_id = ?
                                """,
                                (size, device_id, message_id, part_id),
                            )

                # Text parts become the searchable MMS body. Rebuilding it
                # from the normalized parts keeps repeated imports idempotent.
                body_rows = connection.execute(
                    """
                    SELECT text FROM mms_parts
                    WHERE device_id = ? AND message_id = ?
                      AND text IS NOT NULL AND text <> ''
                    ORDER BY id
                    """,
                    (device_id, message_id),
                ).fetchall()
                body = "\n".join(row["text"] for row in body_rows)
                connection.execute(
                    """
                    UPDATE messages
                    SET body = ?
                    WHERE device_id = ?
                      AND message_type = 'MMS'
                      AND message_id = ?
                    """,
                    (body or None, device_id, message_id),
                )

            connection.commit()

        return {
            "messages": imported_messages,
            "parts": imported_parts,
            "participants": imported_participants,
            "attachments": imported_attachments,
        }

    @staticmethod
    def _normalize_mms_timestamp(value):
        """Store MMS provider timestamps in milliseconds, like SMS timestamps."""
        if value is None:
            return None
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return value
        # Android Telephony.Mms.DATE is expressed in seconds since the Unix epoch.
        # The web UI stores and formats message timestamps in milliseconds.
        return timestamp * 1000 if abs(timestamp) < 100_000_000_000 else timestamp

    @staticmethod
    def _safe_archive_member(member):
        """Return a normalized ZIP member name or None for unsafe paths."""
        try:
            path = PurePosixPath(str(member))
        except Exception:
            return None
        if path.is_absolute() or ".." in path.parts:
            return None
        normalized = path.as_posix()
        if not normalized.startswith("attachments/"):
            return None
        return normalized

    def get_archive_id(self, device_id, filename):
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM archives
                WHERE device_id = ? AND filename = ?
                """,
                (device_id, filename),
            ).fetchone()
            return None if row is None else row["id"]

    def import_sms_from_archive(self, device_id, archive_id, archive_path):
        with zipfile.ZipFile(archive_path, "r") as archive:
            if "sms.json" not in archive.namelist():
                return 0
            with archive.open("sms.json") as f:
                sms_messages = json.load(f)
        return self.import_sms(device_id, archive_id, sms_messages)

    def import_mms_from_archive(self, device_id, archive_id, archive_path):
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = archive.namelist()
            if "mms.json" not in names:
                return {
                    "messages": 0,
                    "parts": 0,
                    "participants": 0,
                    "attachments": 0,
                }

            archive_members = {
                info.filename: info.file_size
                for info in archive.infolist()
                if self._safe_archive_member(info.filename) == info.filename
            }

            with archive.open("mms.json") as f:
                mms_messages = json.load(f)

        return self.import_mms(
            device_id,
            archive_id,
            mms_messages,
            archive_members,
        )


if __name__ == "__main__":
    import sys

    archive_root = (
        sys.argv[1]
        if len(sys.argv) > 1
        else str(Path.home() / "Phone Archive")
    )

    database = ArchiveDatabase(archive_root)
    database.initialize()
    print(f"Database initialized: {database.database_path}")
