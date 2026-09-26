import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from archive_inventory import ArchiveInventory


class ArchiveInventoryTest(unittest.TestCase):
    def test_inventory_reads_preserved_archive_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            device_dir = root / "devices" / "device-123"
            archive_dir = device_dir / "archives" / "2026-09-25"
            archive_dir.mkdir(parents=True)

            (device_dir / "device.json").write_text(
                json.dumps({
                    "deviceId": "device-123",
                    "deviceAlias": "Test Phone",
                }),
                encoding="utf-8",
            )

            filename = "message-archive-test.zip"
            archive_path = archive_dir / filename
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps({
                        "deviceId": "device-123",
                        "deviceAlias": "Test Phone",
                    }),
                )
                archive.writestr(
                    "sms.json",
                    json.dumps([{"_id": "1", "body": "hello"}]),
                )

            (archive_dir / "received.jsonl").write_text(
                json.dumps({
                    "receivedAt": "2026-09-25T17:44:15.481719+00:00",
                    "filename": filename,
                    "remote": "192.168.1.48",
                    "deviceId": "device-123",
                    "deviceAlias": "Test Phone",
                    "indexed": {
                        "sms": 1,
                        "mms": 0,
                        "mmsParts": 0,
                        "participants": 0,
                        "attachments": 0,
                    },
                }) + "\n",
                encoding="utf-8",
            )

            report = ArchiveInventory(root).report()

            self.assertEqual(report["devices"], 1)
            self.assertEqual(report["archives"], 1)
            self.assertEqual(report["device_details"][0]["device_alias"], "Test Phone")

            archive = report["device_details"][0]["archives"][0]
            self.assertEqual(archive["filename"], filename)
            self.assertEqual(
                archive["received_at"],
                "2026-09-25T17:44:15.481719+00:00",
            )
            self.assertEqual(archive["received_from"], "192.168.1.48")
            self.assertEqual(archive["indexed"]["sms"], 1)
            self.assertEqual(archive["zip_members"], 2)


if __name__ == "__main__":
    unittest.main()
