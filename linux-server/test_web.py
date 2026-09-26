#!/usr/bin/env python3

import io
import json
import pathlib
import sqlite3
import tempfile
import unittest
import zipfile

from database import ArchiveDatabase
from web import handle_get


class FakeHandler:
    def __init__(self, database, path):
        self.server = type("Server", (), {"database": database})()
        self.path = path
        self.headers = {}
        self.client_address = ("127.0.0.1", 12345)
        self.response_status = None
        self.response_headers = []
        self.wfile = io.BytesIO()

    def authorized(self):
        return True

    def send_response(self, status):
        self.response_status = status

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        pass


class WebInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tempdir.name)
        self.database = ArchiveDatabase(self.root)
        self.database.initialize()

        self.zip_path = self.root / "archive.zip"
        with zipfile.ZipFile(self.zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps({
                "deviceId": "device-a",
                "deviceAlias": "Test Phone",
            }))
            archive.writestr("sms.json", "[]")
            archive.writestr("mms.json", "[]")
            archive.writestr("attachments/photo.jpg", b"image-data")

        connection = sqlite3.connect(self.database.database_path)
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
                device_id, archive_id, message_type, message_id,
                thread_id, address, body, timestamp
            )
            VALUES ('device-a', ?, 'MMS', '1', 'thread-1', NULL, 'Hello <world>', 1700000000000)
            """,
            (archive_id,),
        )
        connection.execute(
            """
            INSERT INTO messages(
                device_id, archive_id, message_type, message_id,
                thread_id, address, body, timestamp
            )
            VALUES ('device-a', ?, 'SMS', '2', 'thread-1', '5550100', 'SMS search text', 1700000001000)
            """,
            (archive_id,),
        )
        connection.execute(
            """
            INSERT INTO message_participants(
                device_id, message_type, message_id, address, role
            )
            VALUES
                ('device-a', 'MMS', '1', '5550200', 'FROM'),
                ('device-a', 'MMS', '1', '5550300', 'TO')
            """
        )
        connection.execute(
            """
            INSERT INTO attachments(
                device_id, archive_id, message_id, part_id,
                filename, mime_type, size, archive_path
            )
            VALUES ('device-a', ?, '1', '1', 'photo.jpg', 'image/jpeg', 10, 'attachments/photo.jpg')
            """,
            (archive_id,),
        )
        connection.commit()
        connection.close()

        self.archive_id = archive_id

    def tearDown(self):
        self.tempdir.cleanup()

    def test_search_page_filters_by_keyword_and_escapes_html(self):
        handler = FakeHandler(
            self.database,
            "/?q=Hello+%3Cworld%3E&type=MMS",
        )

        self.assertTrue(handle_get(handler))
        body = handler.wfile.getvalue().decode("utf-8")

        self.assertEqual(handler.response_status, 200)
        self.assertIn("Hello &lt;world&gt;", body)
        self.assertIn("1 matching message", body)
        self.assertNotIn("SMS search text", body)

    def test_message_page_shows_mms_participants_and_attachment(self):
        handler = FakeHandler(
            self.database,
            "/message?device=device-a&type=MMS&id=1",
        )

        self.assertTrue(handle_get(handler))
        body = handler.wfile.getvalue().decode("utf-8")

        self.assertEqual(handler.response_status, 200)
        self.assertIn("5550200", body)
        self.assertIn("FROM", body)
        self.assertIn("5550300", body)
        self.assertIn("photo.jpg", body)
        self.assertIn("image/jpeg", body)

    def test_thread_page_uses_mms_sender_without_repeating_participant_list(self):
        handler = FakeHandler(
            self.database,
            "/thread?device=device-a&thread=thread-1",
        )

        self.assertTrue(handle_get(handler))
        body = handler.wfile.getvalue().decode("utf-8")

        self.assertEqual(handler.response_status, 200)
        self.assertIn("5550200", body)
        self.assertIn("Hello &lt;world&gt;", body)
        self.assertIn("SMS search text", body)
        self.assertNotIn("<b>FROM</b> 5550200", body)

    def test_attachment_is_served_from_preserved_archive(self):
        handler = FakeHandler(
            self.database,
            f"/attachment?device=device-a&archive={self.archive_id}&path=attachments/photo.jpg",
        )

        self.assertTrue(handle_get(handler))

        self.assertEqual(handler.response_status, 200)
        self.assertEqual(handler.wfile.getvalue(), b"image-data")
        self.assertIn(("Content-Type", "image/jpeg"), handler.response_headers)
        self.assertIn(
            ("Content-Disposition", 'inline; filename="photo.jpg"'),
            handler.response_headers,
        )


if __name__ == "__main__":
    unittest.main()
