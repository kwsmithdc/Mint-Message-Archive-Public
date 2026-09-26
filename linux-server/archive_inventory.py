#!/usr/bin/env python3

"""Inventory preserved Mint Message Archive ZIP files without modifying them.

This tool reads the preserved archive tree directly. It does not require
archive.db, and it never modifies, deletes, or rewrites ZIP archives.
"""

import argparse
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


class ArchiveInventory:
    def __init__(self, archive_root):
        self.archive_root = Path(archive_root).expanduser().resolve()

    @staticmethod
    def _read_json_member(archive, name):
        with archive.open(name) as stream:
            return json.load(stream)

    @staticmethod
    def _read_received_metadata(archive_dir, filename):
        path = archive_dir / "received.jsonl"
        if not path.is_file():
            return None

        matches = []
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("filename") == filename:
                        matches.append(record)
        except OSError:
            return None

        return matches[-1] if matches else None

    @staticmethod
    def _device_metadata(device_dir):
        path = device_dir / "device.json"
        if not path.is_file():
            return {}

        try:
            with path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to read {path}: {exc}") from exc

        if not isinstance(value, dict):
            raise ValueError(f"{path} does not contain a JSON object")
        return value

    @staticmethod
    def _format_size(value):
        units = ("B", "KiB", "MiB", "GiB", "TiB")
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return f"{value} B"

    def discover(self):
        devices_root = self.archive_root / "devices"
        if not devices_root.is_dir():
            raise FileNotFoundError(
                f"Device archive directory does not exist: {devices_root}"
            )

        inventory = []
        for device_dir in sorted(path for path in devices_root.iterdir() if path.is_dir()):
            device_id = device_dir.name
            metadata = self._device_metadata(device_dir)
            metadata_id = str(metadata.get("deviceId", device_id))
            if metadata_id != device_id:
                raise ValueError(
                    f"{device_dir / 'device.json'} contains a different deviceId"
                )

            archive_root = device_dir / "archives"
            if not archive_root.is_dir():
                inventory.append({
                    "device_id": device_id,
                    "device_alias": str(metadata.get("deviceAlias", "") or ""),
                    "archives": [],
                })
                continue

            archives = []
            for archive_path in sorted(archive_root.rglob("*.zip")):
                try:
                    with zipfile.ZipFile(archive_path, "r") as archive:
                        bad_member = archive.testzip()
                        if bad_member is not None:
                            raise ValueError(
                                f"ZIP CRC check failed at member {bad_member!r}"
                            )
                        if "manifest.json" not in archive.namelist():
                            raise ValueError("archive is missing manifest.json")
                        manifest = self._read_json_member(archive, "manifest.json")
                        manifest_id = str(manifest.get("deviceId") or "").strip()
                        if manifest_id != device_id:
                            raise ValueError(
                                f"manifest deviceId {manifest_id!r} does not match "
                                f"device directory {device_id!r}"
                            )
                        manifest_alias = str(manifest.get("deviceAlias", "") or "")
                        member_count = len(archive.infolist())
                except (OSError, zipfile.BadZipFile, RuntimeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"Unable to inspect {archive_path}: {exc}") from exc

                received = self._read_received_metadata(
                    archive_path.parent,
                    archive_path.name,
                )
                try:
                    stat = archive_path.stat()
                except OSError as exc:
                    raise ValueError(f"Unable to stat {archive_path}: {exc}") from exc

                indexed = received.get("indexed", {}) if received else {}
                archives.append({
                    "filename": archive_path.name,
                    "path": str(archive_path),
                    "date_directory": archive_path.parent.name,
                    "size_bytes": stat.st_size,
                    "size_display": self._format_size(stat.st_size),
                    "zip_members": member_count,
                    "device_id": device_id,
                    "device_alias": (
                        str(metadata.get("deviceAlias", "") or "")
                        or manifest_alias
                    ),
                    "received_at": received.get("receivedAt") if received else None,
                    "received_from": received.get("remote") if received else None,
                    "indexed": {
                        "sms": indexed.get("sms"),
                        "mms": indexed.get("mms"),
                        "mmsParts": indexed.get("mmsParts"),
                        "participants": indexed.get("participants"),
                        "attachments": indexed.get("attachments"),
                    },
                })

            inventory.append({
                "device_id": device_id,
                "device_alias": (
                    str(metadata.get("deviceAlias", "") or "")
                    or (
                        archives[0]["device_alias"]
                        if archives else ""
                    )
                ),
                "archives": archives,
            })

        return inventory

    def report(self):
        inventory = self.discover()
        archive_count = sum(len(device["archives"]) for device in inventory)
        total_bytes = sum(
            archive["size_bytes"]
            for device in inventory
            for archive in device["archives"]
        )

        return {
            "archive_root": str(self.archive_root),
            "devices": len(inventory),
            "archives": archive_count,
            "storage_bytes": total_bytes,
            "storage_display": self._format_size(total_bytes),
            "device_details": inventory,
        }

    @staticmethod
    def print_report(report):
        print("Mint Message Archive — Preserved Archive Inventory")
        print("=" * 52)
        print()
        print(f"Archive root:                {report['archive_root']}")
        print(f"Devices:                     {report['devices']}")
        print(f"Archives:                    {report['archives']}")
        print(f"Preserved ZIP storage:       {report['storage_bytes']:,} bytes ({report['storage_display']})")
        print()

        for device in report["device_details"]:
            alias = device["device_alias"] or "(no alias)"
            print(f"DEVICE: {alias} [{device['device_id']}]")
            print("-" * (8 + len(alias) + len(device["device_id"])))

            if not device["archives"]:
                print("  No ZIP archives found.")
                print()
                continue

            for archive in device["archives"]:
                received = archive["received_at"] or "unknown"
                remote = archive["received_from"] or "unknown"
                indexed = archive["indexed"]
                print(f"  {archive['filename']}")
                print(f"    Received:                {received}")
                print(f"    Source:                  {remote}")
                print(f"    Size:                    {archive['size_bytes']:,} bytes ({archive['size_display']})")
                print(f"    ZIP members:             {archive['zip_members']}")
                print(f"    Indexed:                 SMS={indexed['sms'] if indexed['sms'] is not None else 'n/a'}, "
                      f"MMS={indexed['mms'] if indexed['mms'] is not None else 'n/a'}, "
                      f"MMS parts={indexed['mmsParts'] if indexed['mmsParts'] is not None else 'n/a'}, "
                      f"participants={indexed['participants'] if indexed['participants'] is not None else 'n/a'}, "
                      f"attachments={indexed['attachments'] if indexed['attachments'] is not None else 'n/a'}")
            print()

        print("RESULT: PASS")


def main():
    parser = argparse.ArgumentParser(
        description="Inventory preserved Mint Message Archive ZIP files without modifying them."
    )
    parser.add_argument(
        "--archive",
        default=str(Path.home() / "Phone Archive"),
        help="Archive root containing devices/ (default: ~/Phone Archive)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the inventory as JSON.",
    )
    args = parser.parse_args()

    try:
        report = ArchiveInventory(args.archive).report()
    except (FileNotFoundError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        ArchiveInventory.print_report(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
