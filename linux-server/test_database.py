#!/usr/bin/env python3

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from database import ArchiveDatabase


class DatabaseTest(unittest.TestCase):
    def test_initialize_creates_required_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = ArchiveDatabase(root)
            database.initialize()

            with database.connect() as connection:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }

                self.assertTrue(
                    {
                        "devices",
                        "archives",
                        "messages",
                        "mms_parts",
                        "message_participants",
                        "attachments",
                    }.issubset(tables)
                )
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )

    def test_database_path_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "archive"
            output = Path(tmp) / "rebuilt.db"

            database = ArchiveDatabase(root, database_path=output)
            database.initialize()

            self.assertTrue(output.is_file())
            self.assertFalse((root / "archive.db").exists())

    def test_sms_and_mms_are_stored_with_expected_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = ArchiveDatabase(root)
            database.initialize()

            database.register_device(
                "device-1",
                "Test Phone",
                "2026-09-25T00:00:00+00:00",
                "2026-09-25T00:00:00+00:00",
            )
            archive_id = database.register_archive(
                "device-1",
                "message-archive-test.zip",
                "devices/device-1/archives/2026-09-25/message-archive-test.zip",
                "2026-09-25T00:00:00+00:00",
            )

            self.assertEqual(
                database.import_sms(
                    "device-1",
                    archive_id,
                    [
                        {
                            "id": 1,
                            "threadId": 10,
                            "address": "5550001",
                            "body": "Hello",
                            "date": 1790294400000,
                            "type": 1,
                            "read": 1,
                        }
                    ],
                ),
                1,
            )

            self.assertEqual(
                database.import_mms(
                    "device-1",
                    archive_id,
                    [
                        {
                            "id": 2,
                            "threadId": 20,
                            "date": 1790294400,
                            "messageBox": 1,
                            "subject": "Photo",
                            "addresses": [
                                {
                                    "address": "5550002",
                                    "role": "FROM",
                                    "type": 137,
                                },
                                {
                                    "address": "5550001",
                                    "role": "TO",
                                    "type": 151,
                                },
                            ],
                            "parts": [
                                {
                                    "id": 3,
                                    "contentType": "text/plain",
                                    "text": "MMS body",
                                },
                                {
                                    "id": 4,
                                    "contentType": "image/jpeg",
                                    "filename": "photo.jpg",
                                    "archiveFile": "attachments/photo.jpg",
                                    "archiveFilename": "photo.jpg",
                                    "archiveMimeType": "image/jpeg",
                                },
                            ],
                        }
                    ],
                    archive_members={"attachments/photo.jpg": 9},
                ),
                {
                    "messages": 1,
                    "parts": 2,
                    "participants": 2,
                    "attachments": 1,
                },
            )

            with sqlite3.connect(database.database_path) as connection:
                connection.row_factory = sqlite3.Row
                sms = connection.execute(
                    """
                    SELECT message_type, message_id, timestamp
                    FROM messages
                    WHERE message_type = 'SMS'
                    """
                ).fetchone()
                mms = connection.execute(
                    """
                    SELECT message_type, message_id, timestamp, subject
                    FROM messages
                    WHERE message_type = 'MMS'
                    """
                ).fetchone()
                participants = connection.execute(
                    """
                    SELECT address, role
                    FROM message_participants
                    ORDER BY role
                    """
                ).fetchall()
                attachment = connection.execute(
                    """
                    SELECT filename, mime_type, archive_path
                    FROM attachments
                    """
                ).fetchone()

            self.assertEqual(
                (sms["message_type"], sms["message_id"], sms["timestamp"]),
                ("SMS", "1", 1790294400000),
            )
            self.assertEqual(
                (mms["message_type"], mms["message_id"], mms["timestamp"], mms["subject"]),
                ("MMS", "2", 1790294400000, "Photo"),
            )
            self.assertEqual(
                [(row["address"], row["role"]) for row in participants],
                [
                    ("5550002", "FROM"),
                    ("5550001", "TO"),
                ],
            )
            self.assertEqual(
                (
                    attachment["filename"],
                    attachment["mime_type"],
                    attachment["archive_path"],
                ),
                ("photo.jpg", "image/jpeg", "attachments/photo.jpg"),
            )

    def test_duplicate_message_ids_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = ArchiveDatabase(root)
            database.initialize()

            database.register_device(
                "device-1",
                "Test Phone",
                "2026-09-25T00:00:00+00:00",
                "2026-09-25T00:00:00+00:00",
            )
            archive_id = database.register_archive(
                "device-1",
                "archive.zip",
                "archive.zip",
                "2026-09-25T00:00:00+00:00",
            )
            message = {
                "id": 123,
                "threadId": 1,
                "address": "5550001",
                "body": "same message",
                "date": 1790294400000,
                "type": 1,
                "read": 1,
            }

            self.assertEqual(
                database.import_sms("device-1", archive_id, [message]),
                1,
            )
            self.assertEqual(
                database.import_sms("device-1", archive_id, [message]),
                0,
            )

            with database.connect() as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM messages"
                ).fetchone()[0]

            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
