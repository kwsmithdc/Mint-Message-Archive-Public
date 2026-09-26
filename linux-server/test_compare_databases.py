#!/usr/bin/env python3

import pathlib
import sqlite3
import tempfile
import unittest

from compare_databases import TABLE_SPECS, compare_table, connect
from database import ArchiveDatabase


class CompareDatabasesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tempdir.name)
        self.production_path = root / "production.db"
        self.rebuilt_path = root / "rebuilt.db"

        for path in (self.production_path, self.rebuilt_path):
            database = ArchiveDatabase(root / path.stem, database_path=path)
            database.initialize()

    def tearDown(self):
        self.tempdir.cleanup()

    def seed_database(self, path, archive_id_order=()):
        connection = sqlite3.connect(path)
        connection.execute(
            """
            INSERT INTO devices(device_id, device_alias, first_seen, last_seen)
            VALUES ('device-a', 'Test Phone', '2026-01-01T00:00:00', '2026-01-02T00:00:00')
            """
        )

        filenames = list(archive_id_order) or [
            "archive-a.zip",
            "archive-b.zip",
        ]
        for filename in filenames:
            connection.execute(
                """
                INSERT INTO archives(device_id, filename, archive_path, received_at)
                VALUES ('device-a', ?, ?, ?)
                """,
                (
                    filename,
                    f"devices/device-a/archives/2026-01-01/{filename}",
                    "2026-01-01T12:00:00",
                ),
            )

        archive_a = connection.execute(
            "SELECT id FROM archives WHERE filename = 'archive-a.zip'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO messages(
                device_id, archive_id, message_type, message_id,
                thread_id, address, body, subject, message_box,
                sms_type, sms_read, timestamp
            )
            VALUES (
                'device-a', ?, 'SMS', '1', '10', '5550100',
                'Regression message', NULL, NULL, 1, 1, 1700000000000
            )
            """,
            (archive_a,),
        )
        connection.execute(
            """
            INSERT INTO message_participants(
                device_id, message_type, message_id, address, role
            )
            VALUES ('device-a', 'MMS', '2', '5550101', 'FROM')
            """
        )
        connection.commit()
        connection.close()

    def compare(self, table):
        production = connect(self.production_path)
        rebuilt = connect(self.rebuilt_path)
        try:
            return compare_table(production, rebuilt, table)
        finally:
            production.close()
            rebuilt.close()

    def test_identical_databases_compare_equal(self):
        self.seed_database(self.production_path)
        self.seed_database(self.rebuilt_path)

        for table in TABLE_SPECS:
            result = self.compare(table)
            self.assertTrue(result["pass"], table)
            self.assertEqual(result["missing"], {})
            self.assertEqual(result["extra"], {})

    def test_archive_id_differences_are_ignored(self):
        self.seed_database(
            self.production_path,
            ["archive-a.zip", "archive-b.zip"],
        )
        self.seed_database(
            self.rebuilt_path,
            ["archive-b.zip", "archive-a.zip"],
        )

        result = self.compare("messages")
        self.assertTrue(result["pass"])
        self.assertEqual(result["missing"], {})
        self.assertEqual(result["extra"], {})

    def test_content_difference_is_reported(self):
        self.seed_database(self.production_path)
        self.seed_database(self.rebuilt_path)

        connection = sqlite3.connect(self.rebuilt_path)
        connection.execute(
            "UPDATE messages SET body = 'Changed message' WHERE message_id = '1'"
        )
        connection.commit()
        connection.close()

        result = self.compare("messages")
        self.assertFalse(result["pass"])
        self.assertEqual(len(result["missing"]), 1)
        self.assertEqual(len(result["extra"]), 1)

    def test_connect_is_read_only(self):
        self.seed_database(self.production_path)
        connection = connect(self.production_path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute(
                    "UPDATE devices SET device_alias = 'Changed' WHERE device_id = 'device-a'"
                )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
