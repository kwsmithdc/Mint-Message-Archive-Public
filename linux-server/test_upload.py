#!/usr/bin/env python3

import io
from email.message import Message
import json
import pathlib
import tempfile
import unittest
import zipfile

from database import ArchiveDatabase
from server import Handler, is_safe_device_id, require_local_client


class UploadHandlerTests(unittest.TestCase):
    TOKEN = "test-token"

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.archive_root = pathlib.Path(self.tempdir.name)
        self.database = ArchiveDatabase(self.archive_root)
        self.database.initialize()

    def tearDown(self):
        self.tempdir.cleanup()

    def make_archive(
        self,
        filename="message-archive-test.zip",
        device_id="test-device",
        alias="Test Phone",
    ):
        path = self.archive_root / filename
        manifest = {
            "manifestVersion": 4,
            "deviceId": device_id,
            "deviceAlias": alias,
        }
        sms = [{
            "id": "1",
            "threadId": "10",
            "address": "5550100",
            "body": "Regression test message",
            "date": 1700000000000,
            "type": 1,
            "read": 1,
        }]
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("sms.json", json.dumps(sms))
            archive.writestr("mms.json", json.dumps([]))
        return path

    def make_handler(
        self,
        body,
        boundary=None,
        client_ip="127.0.0.1",
        content_type=None,
        content_length=None,
        authorization=None,
    ):
        archive_root = self.archive_root
        database = self.database
        token = self.TOKEN
        received = []

        class FakeHandler(Handler):
            def __init__(self):
                self.server = type("Server", (), {
                    "archive": archive_root,
                    "database": database,
                    "token": token,
                })()
                self.client_address = (client_ip, 12345)
                self.path = "/upload"
                self.headers = Message()
                self.headers["Authorization"] = (
                    authorization if authorization is not None else "Bearer " + token
                )
                if content_type is not None:
                    self.headers["Content-Type"] = content_type
                elif boundary is not None:
                    self.headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
                self.headers["Content-Length"] = str(
                    len(body) if content_length is None else content_length
                )
                self.rfile = io.BytesIO(body)
                self.wfile = io.BytesIO()

            def send_json(self, status, payload):
                received.append((status, payload))

        return FakeHandler(), received

    def multipart_body(self, data):
        boundary = "----mint-test"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="message-archive-test.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        return boundary, body

    def test_local_authorized_upload_persists_archive_and_indexes_sms(self):
        archive = self.make_archive()
        data = archive.read_bytes()
        boundary, body = self.multipart_body(data)

        handler, received = self.make_handler(body, boundary)
        handler.do_POST()

        self.assertEqual(received[-1][0], 201)
        payload = received[-1][1]
        self.assertEqual(payload["deviceId"], "test-device")
        self.assertEqual(payload["indexed"]["sms"], 1)

        stored = list(
            (self.archive_root / "devices" / "test-device" / "archives").rglob("*.zip")
        )
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].read_bytes(), data)

        with self.database.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM devices").fetchone()[0], 1
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM archives").fetchone()[0], 1
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1
            )

    def test_public_client_is_rejected_before_authentication(self):
        received = []
        token = self.TOKEN

        class FakeHandler(Handler):
            def __init__(self):
                self.client_address = ("203.0.113.1", 12345)
                self.path = "/upload"
                self.headers = Message()
                self.headers["Authorization"] = "Bearer " + token
                self._responses = received

            def send_json(self, status, payload):
                self._responses.append((status, payload))

        handler = FakeHandler()
        self.assertFalse(require_local_client(handler))
        self.assertEqual(received[0][0], 403)

    def test_missing_or_invalid_authentication_is_rejected(self):
        received = []
        token = self.TOKEN

        class FakeHandler(Handler):
            def __init__(self):
                self.client_address = ("127.0.0.1", 12345)
                self.path = "/upload"
                self.headers = Message()
                self._responses = received
                self.server = type("Server", (), {"token": token})()

            def send_json(self, status, payload):
                self._responses.append((status, payload))

        handler = FakeHandler()
        self.assertFalse(handler.authorized())
        self.assertEqual(received, [])

    def test_malformed_basic_authentication_is_rejected(self):
        handler, received = self.make_handler(
            b"",
            content_type="application/zip",
            authorization="Basic !!!not-base64!!!",
        )
        self.assertFalse(handler.authorized())
        self.assertEqual(received, [])

    def test_valid_basic_authentication_is_accepted(self):
        authorization = "Basic " + __import__("base64").b64encode(
            b"archive:" + self.TOKEN.encode()
        ).decode()
        handler, received = self.make_handler(
            b"",
            content_type="application/zip",
            authorization=authorization,
        )
        self.assertTrue(handler.authorized())
        self.assertEqual(received, [])

    def test_zero_length_upload_is_rejected(self):
        handler, received = self.make_handler(b"", content_type="application/zip")
        handler.do_POST()

        self.assertEqual(received[-1][0], 413)
        self.assertEqual(received[-1][1]["error"], "invalid upload size")

    def test_oversized_upload_is_rejected(self):
        handler, received = self.make_handler(
            b"",
            content_type="application/zip",
            content_length=2 * 1024 * 1024 * 1024 + 1,
        )
        handler.do_POST()

        self.assertEqual(received[-1][0], 413)
        self.assertEqual(received[-1][1]["error"], "invalid upload size")

    def test_non_multipart_upload_is_rejected(self):
        handler, received = self.make_handler(
            b"archive-data",
            content_type="application/zip",
        )
        handler.do_POST()

        self.assertEqual(received[-1][0], 400)
        self.assertEqual(received[-1][1]["error"], "expected multipart/form-data")

    def test_multipart_upload_without_file_field_is_rejected(self):
        boundary = "----mint-test-missing-file"
        body = (
            f"--{boundary}\\r\\n"
            'Content-Disposition: form-data; name="other"\\r\\n\\r\\n'
            "not-an-archive\\r\\n"
            f"--{boundary}--\\r\\n"
        ).encode()
        handler, received = self.make_handler(body, boundary)
        handler.do_POST()

        self.assertEqual(received[-1][0], 400)
        self.assertEqual(received[-1][1]["error"], "missing file field")

    def test_invalid_archive_is_removed_after_rejection(self):
        boundary, body = self.multipart_body(b"not-a-zip")
        handler, received = self.make_handler(body, boundary)
        handler.do_POST()

        self.assertEqual(received[-1][0], 400)
        self.assertEqual(received[-1][1]["error"], "File is not a zip file")
        self.assertEqual(list(self.archive_root.rglob(".upload-*.part")), [])

    def test_invalid_archive_filename_is_rejected(self):
        boundary = "----mint-test-invalid-filename"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="' + ("x" * 256) + '"\r\n'
            "Content-Type: application/zip\r\n\r\n"
            "not-an-archive\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        handler, received = self.make_handler(body, boundary)
        handler.do_POST()

        self.assertEqual(received[-1][0], 400)
        self.assertEqual(received[-1][1]["error"], "archive filename is invalid")
        self.assertEqual(list(self.archive_root.rglob(".upload-*.part")), [])

    def test_control_character_in_archive_filename_is_rejected(self):
        archive = self.make_archive()
        data = archive.read_bytes()
        boundary = "----mint-test-control-name"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="bad\x01name.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()

        handler, received = self.make_handler(body, boundary)
        handler.do_POST()

        self.assertEqual(received[-1][0], 400)
        self.assertEqual(received[-1][1]["error"], "archive filename is invalid")
        self.assertEqual(list(self.archive_root.rglob(".upload-*.part")), [])

    def test_device_id_validation_rejects_path_traversal(self):
        self.assertTrue(is_safe_device_id("test-device.01_abc"))
        self.assertFalse(is_safe_device_id("../outside"))
        self.assertFalse(is_safe_device_id("device/child"))
        self.assertFalse(is_safe_device_id("device\\\\child"))
        self.assertFalse(is_safe_device_id(""))
        self.assertFalse(is_safe_device_id("a" * 129))

    def test_upload_with_non_object_manifest_is_rejected(self):
        path = self.archive_root / "invalid-manifest.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(["not", "an", "object"]))
        boundary, body = self.multipart_body(path.read_bytes())
        handler, received = self.make_handler(body, boundary)
        handler.do_POST()

        self.assertEqual(received[-1][0], 400)
        self.assertEqual(
            received[-1][1]["error"],
            "manifest must be a JSON object",
        )
        self.assertEqual(list(self.archive_root.rglob(".upload-*.part")), [])

    def test_upload_with_invalid_device_id_is_rejected(self):
        archive = self.make_archive(device_id="../outside")
        data = archive.read_bytes()
        boundary, body = self.multipart_body(data)
        handler, received = self.make_handler(body, boundary)
        handler.do_POST()

        self.assertEqual(received[-1][0], 400)
        self.assertEqual(received[-1][1]["error"], "manifest contains an invalid deviceId")
        self.assertEqual(
            list(self.archive_root.rglob("outside")),
            [],
        )
        self.assertEqual(list(self.archive_root.rglob(".upload-*.part")), [])

    def test_duplicate_filename_does_not_overwrite_preserved_archive(self):
        first_archive = self.make_archive(alias="Original Phone")
        first_data = first_archive.read_bytes()
        boundary, body = self.multipart_body(first_data)
        handler, received = self.make_handler(body, boundary)
        handler.do_POST()
        self.assertEqual(received[-1][0], 201)

        second_archive = self.make_archive(alias="Different Phone")
        second_data = second_archive.read_bytes()
        self.assertNotEqual(first_data, second_data)
        boundary, body = self.multipart_body(second_data)
        handler, received = self.make_handler(body, boundary)
        handler.do_POST()
        self.assertEqual(received[-1][0], 201)

        stored = list(
            (self.archive_root / "devices" / "test-device" / "archives").rglob("*.zip")
        )
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].read_bytes(), first_data)
        self.assertEqual(list(self.archive_root.rglob(".upload-*.part")), [])

    def test_duplicate_filename_is_not_reindexed(self):
        archive = self.make_archive()
        data = archive.read_bytes()
        boundary, body = self.multipart_body(data)

        def upload_once():
            handler, received = self.make_handler(body, boundary)
            handler.do_POST()
            return received[-1]

        first = upload_once()
        second = upload_once()
        self.assertEqual(first[0], 201)
        self.assertEqual(second[0], 201)

        with self.database.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM archives").fetchone()[0], 1
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1
            )

        stored = list(
            (self.archive_root / "devices" / "test-device" / "archives").rglob("*.zip")
        )
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
