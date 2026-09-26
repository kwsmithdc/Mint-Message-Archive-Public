#!/usr/bin/env python3

import pathlib
import sqlite3
import tempfile
import unittest
import zipfile

from database import ArchiveDatabase
from verify_archive import ArchiveVerifier


class ArchiveVerifierTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tempdir.name)
        self.db_path = self.root / "archive.db"
        database = ArchiveDatabase(self.root)
        database.initialize()

        self.zip_path = self.root / "archive.zip"
        with zipfile.ZipFile(self.zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", '{"deviceId":"device-a"}')
            archive.writestr("sms.json", "[]")
            archive.writestr("attachments/photo.jpg", b"test-image")

        connection = sqlite3.connect(self.db_path)
        connection.execute(
            """
            INSERT INTO devices(device_id, device_alias, first_seen, last_seen)
            VALUES ('device-a', 'Test Phone', '2026-01-01', '2026-01-01')
            """
        )
        connection.execute(
            """
            INSERT INTO archives(device_id, filename, archive_path, received_at)
            VALUES ('device-a', 'archive.zip', ?, '2026-01-01T12:00:00')
            """,
            (str(self.zip_path),),
        )
        archive_id = connection.execute(
            "SELECT id FROM archives WHERE filename = 'archive.zip'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO messages(
                device_id, archive_id, message_type, message_id, body, timestamp
            )
            VALUES ('device-a', ?, 'SMS', '1', 'test', 1700000000000)
            """,
            (archive_id,),
        )
        connection.execute(
            """
            INSERT INTO mms_parts(
                device_id, archive_id, message_id, part_id,
                content_type, archive_member, size
            )
            VALUES ('device-a', ?, '1', '1', 'image/jpeg', 'attachments/photo.jpg', 10)
            """,
            (archive_id,),
        )
        connection.execute(
            """
            INSERT INTO attachments(
                device_id, archive_id, message_id, part_id,
                filename, mime_type, size, archive_path
            )
            VALUES (
                'device-a', ?, '1', '1',
                'photo.jpg', 'image/jpeg', 10, 'attachments/photo.jpg'
            )
            """,
            (archive_id,),
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self.tempdir.cleanup()

    def verify(self):
        return ArchiveVerifier(self.root).verify()

    def test_intact_archive_and_references_pass(self):
        result = self.verify()

        self.assertEqual(result["integrity_check"], "ok")
        self.assertEqual(result["archives"], 1)
        self.assertEqual(result["archives_readable"], 1)
        self.assertEqual(result["archives_corrupt"], [])
        self.assertEqual(result["missing_archives"], [])
        self.assertEqual(result["missing_message_archives"], [])
        self.assertEqual(result["mms_parts_verified"], 1)
        self.assertEqual(result["missing_mms_parts"], [])
        self.assertEqual(result["attachments_verified"], 1)
        self.assertEqual(result["missing_attachments"], [])
        self.assertEqual(result["unsafe_attachment_paths"], [])
        self.assertEqual(result["unsafe_mms_part_paths"], [])

    def test_missing_archive_is_detected(self):
        self.zip_path.unlink()

        result = self.verify()

        self.assertEqual(result["archives"], 1)
        self.assertEqual(result["archives_readable"], 0)
        self.assertEqual(len(result["missing_archives"]), 1)
        self.assertEqual(len(result["missing_message_archives"]), 1)
        self.assertEqual(len(result["missing_mms_parts"]), 1)
        self.assertEqual(len(result["missing_attachments"]), 1)

    def test_corrupt_archive_is_detected(self):
        self.zip_path.write_bytes(b"not a zip archive")

        result = self.verify()

        self.assertEqual(result["archives_readable"], 0)
        self.assertEqual(len(result["archives_corrupt"]), 1)
        self.assertEqual(len(result["missing_message_archives"]), 1)
        self.assertEqual(len(result["missing_mms_parts"]), 1)
        self.assertEqual(len(result["missing_attachments"]), 1)

    def test_unsafe_archive_members_are_detected(self):
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            "UPDATE mms_parts SET archive_member = '../outside.txt'"
        )
        connection.execute(
            "UPDATE attachments SET archive_path = '/outside.txt'"
        )
        connection.commit()
        connection.close()

        result = self.verify()

        self.assertEqual(len(result["unsafe_mms_part_paths"]), 1)
        self.assertEqual(len(result["unsafe_attachment_paths"]), 1)


if __name__ == "__main__":
    unittest.main()
