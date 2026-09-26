#!/usr/bin/env python3

"""Rebuild the SQLite search index entirely from preserved ZIP archives.

The preserved ZIP files are treated as the authoritative message source.
Preserved received.jsonl metadata is authoritative for server receive times
when available. This tool never modifies, deletes, or rewrites source
archives or metadata, and it never replaces the production archive.db.
"""

import argparse
import json
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from database import ArchiveDatabase


class ArchiveRebuilder:
    def __init__(self, archive_root, output_path):
        self.archive_root = Path(archive_root).expanduser().resolve()
        self.output_path = Path(output_path).expanduser().resolve()

        if not self.archive_root.is_dir():
            raise FileNotFoundError(
                f"Archive root does not exist: {self.archive_root}"
            )

        if self.output_path.exists():
            raise FileExistsError(
                f"Output database already exists: {self.output_path} "
                "(remove it or choose a different --output path)"
            )

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.database = ArchiveDatabase(
            self.archive_root,
            database_path=self.output_path,
        )

    @staticmethod
    def _read_json_member(archive, name):
        with archive.open(name) as stream:
            return json.load(stream)

    @staticmethod
    def _archive_received_at(archive_dir, filename, archive_path):
        """Recover the original server receive time from preserved metadata."""
        received_log = archive_dir / "received.jsonl"
        if received_log.is_file():
            try:
                matches = []
                with received_log.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if record.get("filename") == filename:
                            value = record.get("receivedAt")
                            if value:
                                matches.append(str(value))
                if matches:
                    return matches[-1]
            except OSError:
                pass

        timestamp = datetime.fromtimestamp(
            archive_path.stat().st_mtime,
            timezone.utc,
        )
        return timestamp.isoformat()

    @staticmethod
    def _device_alias(device_dir, device_id, manifest_alias):
        """Recover the device alias without trusting device timestamp metadata."""
        device_file = device_dir / "device.json"
        if device_file.is_file():
            try:
                with device_file.open("r", encoding="utf-8") as stream:
                    device = json.load(stream)
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Unable to read {device_file}: {exc}"
                ) from exc

            if str(device.get("deviceId", device_id)) != device_id:
                raise ValueError(
                    f"{device_file} contains a different deviceId"
                )

            return str(device.get("deviceAlias", "") or "")

        return manifest_alias

    def discover_archives(self):
        devices_root = self.archive_root / "devices"
        if not devices_root.is_dir():
            raise FileNotFoundError(
                f"Device archive directory does not exist: {devices_root}"
            )

        discovered = []
        for device_dir in sorted(path for path in devices_root.iterdir() if path.is_dir()):
            archive_root = device_dir / "archives"
            if not archive_root.is_dir():
                continue

            for archive_path in sorted(archive_root.rglob("*.zip")):
                discovered.append((device_dir, archive_path))

        if not discovered:
            raise RuntimeError(
                f"No preserved ZIP archives were found below {devices_root}"
            )

        return discovered

    def rebuild(self):
        discovered = self.discover_archives()
        stats = {
            "devices": 0,
            "archives": 0,
            "sms": 0,
            "mms": 0,
            "mms_parts": 0,
            "participants": 0,
            "attachments": 0,
        }

        device_archives = {}
        for device_dir, archive_path in discovered:
            device_archives.setdefault(device_dir, []).append(archive_path)

        self.database.initialize()

        seen_archives = set()

        try:
            for device_dir in sorted(device_archives):
                archive_paths = device_archives[device_dir]
                expected_device_id = device_dir.name

                device_id = None
                device_alias = ""
                receive_times = []

                for archive_path in archive_paths:
                    try:
                        with zipfile.ZipFile(archive_path, "r") as archive:
                            if archive.testzip() is not None:
                                raise ValueError(
                                    "ZIP CRC check failed"
                                )
                            if "manifest.json" not in archive.namelist():
                                raise ValueError(
                                    "archive is missing manifest.json"
                                )
                            manifest = self._read_json_member(
                                archive, "manifest.json"
                            )
                    except (OSError, zipfile.BadZipFile, RuntimeError, json.JSONDecodeError) as exc:
                        raise ValueError(
                            f"Unable to read {archive_path}: {exc}"
                        ) from exc

                    manifest_device_id = str(manifest.get("deviceId") or "").strip()
                    if not manifest_device_id:
                        raise ValueError(
                            f"{archive_path}: manifest is missing deviceId"
                        )
                    if manifest_device_id != expected_device_id:
                        raise ValueError(
                            f"{archive_path}: manifest deviceId "
                            f"{manifest_device_id!r} does not match device directory "
                            f"{expected_device_id!r}"
                        )

                    if device_id is None:
                        device_id = manifest_device_id
                    elif manifest_device_id != device_id:
                        raise ValueError(
                            f"{archive_path}: deviceId does not match other archives "
                            f"for {device_dir}"
                        )

                    if not device_alias:
                        device_alias = str(manifest.get("deviceAlias", "") or "")

                    receive_times.append(
                        self._archive_received_at(
                            archive_path.parent,
                            archive_path.name,
                            archive_path,
                        )
                    )

                metadata_alias = self._device_alias(
                    device_dir,
                    device_id,
                    device_alias,
                )
                device_alias = metadata_alias or device_alias
                first_seen = min(receive_times)
                last_seen = max(receive_times)

                self.database.register_device(
                    device_id,
                    device_alias,
                    first_seen,
                    last_seen,
                )
                stats["devices"] += 1

                for archive_path in sorted(archive_paths):
                    key = (device_id, archive_path.name)
                    if key in seen_archives:
                        raise ValueError(
                            f"Duplicate archive filename for device {device_id}: "
                            f"{archive_path.name}"
                        )
                    seen_archives.add(key)

                    received_at = self._archive_received_at(
                        archive_path.parent,
                        archive_path.name,
                        archive_path,
                    )
                    archive_id = self.database.register_archive(
                        device_id,
                        archive_path.name,
                        str(archive_path),
                        received_at,
                    )
                    if archive_id is None:
                        raise RuntimeError(
                            f"Could not register archive: {archive_path}"
                        )

                    stats["archives"] += 1
                    stats["sms"] += self.database.import_sms_from_archive(
                        device_id,
                        archive_id,
                        str(archive_path),
                    )
                    mms_result = self.database.import_mms_from_archive(
                        device_id,
                        archive_id,
                        str(archive_path),
                    )
                    stats["mms"] += mms_result["messages"]
                    stats["mms_parts"] += mms_result["parts"]
                    stats["participants"] += mms_result["participants"]
                    stats["attachments"] += mms_result["attachments"]

            self._verify_output()
            return stats
        except Exception:
            try:
                self.output_path.unlink()
            except OSError:
                pass
            raise

    def _verify_output(self):
        with sqlite3.connect(self.output_path) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(
                    f"rebuilt database failed SQLite integrity check: {result}"
                )


def print_report(stats, output_path):
    print("Mint Message Archive — Database Rebuild")
    print("=" * 45)
    print()
    print(f"Output database:             {output_path}")
    print()
    print("SOURCE ARCHIVES")
    print("---------------")
    print(f"Devices discovered:          {stats['devices']}")
    print(f"Archives processed:          {stats['archives']}")
    print()
    print("INDEXED DATA")
    print("------------")
    print(f"SMS messages:                {stats['sms']:,}")
    print(f"MMS messages:                {stats['mms']:,}")
    print(f"MMS parts:                   {stats['mms_parts']:,}")
    print(f"Participants:                {stats['participants']:,}")
    print(f"Attachments:                 {stats['attachments']:,}")
    print()
    print("SQLite integrity:            PASS")
    print("Original ZIP archives:       NOT MODIFIED")
    print()
    print("RESULT: PASS")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild a Mint Message Archive SQLite database from preserved ZIP "
            "archives without modifying the source archives."
        )
    )
    parser.add_argument(
        "--archive",
        default=str(Path.home() / "Phone Archive"),
        help="Archive root containing devices/.",
    )
    parser.add_argument(
        "--output",
        help=(
            "Output SQLite database path. Defaults to a sibling database named "
            "<archive>.rebuilt.db."
        ),
    )
    args = parser.parse_args()

    archive_root = Path(args.archive).expanduser().resolve()
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = archive_root.parent / f"{archive_root.name}.rebuilt.db"

    try:
        stats = ArchiveRebuilder(archive_root, output_path).rebuild()
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print_report(stats, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
