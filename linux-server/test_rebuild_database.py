#!/usr/bin/env python3

import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rebuild_database import ArchiveRebuilder


class RebuildDatabaseTest(unittest.TestCase):
    def test_rebuilds_index_from_preserved_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Phone Archive"
            device = root / "devices" / "test-device"
            archive_dir = device / "archives" / "2026-09-25"
            archive_dir.mkdir(parents=True)

            (device / "device.json").write_text(
                json.dumps(
                    {
                        "deviceId": "test-device",
                        "deviceAlias": "Test Phone",
                        "firstSeen": "2026-09-25T00:00:00+00:00",
                        "lastSeen": "2026-09-25T01:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            archive_path = archive_dir / "message-archive-test.zip"
            manifest = {
                "deviceId": "test-device",
                "deviceAlias": "Test Phone",
                "formatVersion": 4,
            }
            sms = [
                {
                    "id": 1,
                    "threadId": 10,
                    "address": "5551234",
                    "body": "Hello",
                    "date": 1790294400000,
                    "type": 1,
                    "read": 1,
                }
            ]
            mms = [
                {
                    "id": 2,
                    "threadId": 20,
                    "date": 1790294400,
                    "messageBox": 1,
                    "subject": "Photo",
                    "addresses": [
                        {"address": "5555678", "role": "FROM", "type": 137},
                        {"address": "5551234", "role": "TO", "type": 151},
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
            ]

            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest),
                )
                archive.writestr("sms.json", json.dumps(sms))
                archive.writestr("mms.json", json.dumps(mms))
                archive.writestr("attachments/photo.jpg", b"test-image")

            (archive_dir / "received.jsonl").write_text(
                json.dumps(
                    {
                        "receivedAt": "2026-09-25T02:00:00+00:00",
                        "filename": archive_path.name,
                        "bytes": archive_path.stat().st_size,
                        "remote": "192.168.1.48",
                        "deviceId": "test-device",
                        "deviceAlias": "Test Phone",
                    }
                ) + "\n",
                encoding="utf-8",
            )

            output = Path(tmp) / "rebuilt.db"
            stats = ArchiveRebuilder(root, output).rebuild()

            self.assertEqual(stats["devices"], 1)
            self.assertEqual(stats["archives"], 1)
            self.assertEqual(stats["sms"], 1)
            self.assertEqual(stats["mms"], 1)
            self.assertEqual(stats["mms_parts"], 2)
            self.assertEqual(stats["participants"], 2)
            self.assertEqual(stats["attachments"], 1)

            with sqlite3.connect(output) as connection:
                counts = {
                    table: connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                    for table in (
                        "devices",
                        "archives",
                        "messages",
                        "mms_parts",
                        "message_participants",
                        "attachments",
                    )
                }

                device_row = connection.execute(
                    """
                    SELECT device_id, device_alias, first_seen, last_seen
                    FROM devices
                    """
                ).fetchone()

                archive_row = connection.execute(
                    """
                    SELECT filename, received_at
                    FROM archives
                    """
                ).fetchone()

            self.assertEqual(
                counts,
                {
                    "devices": 1,
                    "archives": 1,
                    "messages": 2,
                    "mms_parts": 2,
                    "message_participants": 2,
                    "attachments": 1,
                },
            )
            self.assertEqual(
                device_row,
                (
                    "test-device",
                    "Test Phone",
                    "2026-09-25T02:00:00+00:00",
                    "2026-09-25T02:00:00+00:00",
                ),
            )
            self.assertEqual(
                archive_row,
                (
                    archive_path.name,
                    "2026-09-25T02:00:00+00:00",
                ),
            )


if __name__ == "__main__":
    unittest.main()
