#!/usr/bin/env python3

import argparse
import sqlite3
import sys
import zipfile
from pathlib import Path, PurePosixPath


class ArchiveVerifier:
    def __init__(self, archive_root):
        self.archive_root = Path(archive_root).expanduser().resolve()
        self.database_path = self.archive_root / "archive.db"

    def connect(self):
        if not self.database_path.is_file():
            raise FileNotFoundError(f"SQLite database not found: {self.database_path}")
        uri = f"file:{self.database_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _safe_member(member):
        try:
            path = PurePosixPath(str(member))
        except Exception:
            return None
        if path.is_absolute() or ".." in path.parts:
            return None
        return path.as_posix()

    def verify(self):
        result = {
            "devices": 0,
            "archives": 0,
            "archives_readable": 0,
            "archives_corrupt": [],
            "missing_archives": [],
            "database_archive_records": 0,
            "attachment_records": 0,
            "attachments_verified": 0,
            "missing_attachments": [],
            "unsafe_attachment_paths": [],
            "mms_part_records": 0,
            "mms_parts_verified": 0,
            "missing_mms_parts": [],
            "unsafe_mms_part_paths": [],
            "message_archive_links": 0,
            "missing_message_archives": [],
            "integrity_check": None,
        }

        with self.connect() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            required = {
                "devices",
                "archives",
                "messages",
                "mms_parts",
                "attachments",
            }
            missing_tables = sorted(required - tables)
            if missing_tables:
                raise RuntimeError(
                    "Required database tables are missing: "
                    + ", ".join(missing_tables)
                )

            result["integrity_check"] = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

            result["devices"] = connection.execute(
                "SELECT COUNT(*) FROM devices"
            ).fetchone()[0]

            archive_rows = connection.execute(
                """
                SELECT id, device_id, filename, archive_path
                FROM archives
                ORDER BY id
                """
            ).fetchall()
            result["archives"] = len(archive_rows)
            result["database_archive_records"] = len(archive_rows)

            archive_cache = {}

            for row in archive_rows:
                archive_id = row["id"]
                archive_path = Path(row["archive_path"]).expanduser()

                if not archive_path.is_absolute():
                    archive_path = self.archive_root / archive_path
                archive_path = archive_path.resolve()

                cache = {
                    "path": archive_path,
                    "members": None,
                    "readable": False,
                }
                archive_cache[archive_id] = cache

                if not archive_path.is_file():
                    result["missing_archives"].append(
                        {
                            "archive_id": archive_id,
                            "device_id": row["device_id"],
                            "filename": row["filename"],
                            "path": str(archive_path),
                        }
                    )
                    continue

                try:
                    with zipfile.ZipFile(archive_path, "r") as archive:
                        bad_member = archive.testzip()
                        if bad_member is not None:
                            result["archives_corrupt"].append(
                                {
                                    "archive_id": archive_id,
                                    "device_id": row["device_id"],
                                    "filename": row["filename"],
                                    "path": str(archive_path),
                                    "member": bad_member,
                                    "reason": "CRC check failed",
                                }
                            )
                            continue

                        cache["members"] = set(archive.namelist())
                        cache["readable"] = True
                        result["archives_readable"] += 1
                except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                    result["archives_corrupt"].append(
                        {
                            "archive_id": archive_id,
                            "device_id": row["device_id"],
                            "filename": row["filename"],
                            "path": str(archive_path),
                            "reason": str(exc),
                        }
                    )

            attachment_rows = connection.execute(
                """
                SELECT id, device_id, archive_id, message_id, part_id,
                       filename, archive_path
                FROM attachments
                ORDER BY id
                """
            ).fetchall()
            result["attachment_records"] = len(attachment_rows)

            for row in attachment_rows:
                archive = archive_cache.get(row["archive_id"])
                member = self._safe_member(row["archive_path"])

                if member is None:
                    result["unsafe_attachment_paths"].append(
                        {
                            "attachment_id": row["id"],
                            "archive_id": row["archive_id"],
                            "archive_path": row["archive_path"],
                        }
                    )
                    continue

                if archive is None or not archive["readable"]:
                    result["missing_attachments"].append(
                        {
                            "attachment_id": row["id"],
                            "archive_id": row["archive_id"],
                            "message_id": row["message_id"],
                            "part_id": row["part_id"],
                            "archive_path": member,
                            "reason": "source archive missing or unreadable",
                        }
                    )
                    continue

                if member not in archive["members"]:
                    result["missing_attachments"].append(
                        {
                            "attachment_id": row["id"],
                            "archive_id": row["archive_id"],
                            "message_id": row["message_id"],
                            "part_id": row["part_id"],
                            "archive_path": member,
                            "reason": "ZIP member not found",
                        }
                    )
                    continue

                result["attachments_verified"] += 1

            part_rows = connection.execute(
                """
                SELECT id, device_id, archive_id, message_id, part_id,
                       archive_member
                FROM mms_parts
                WHERE archive_member IS NOT NULL
                  AND archive_member <> ''
                ORDER BY id
                """
            ).fetchall()
            result["mms_part_records"] = len(part_rows)

            for row in part_rows:
                archive = archive_cache.get(row["archive_id"])
                member = self._safe_member(row["archive_member"])

                if member is None:
                    result["unsafe_mms_part_paths"].append(
                        {
                            "mms_part_id": row["id"],
                            "archive_id": row["archive_id"],
                            "archive_member": row["archive_member"],
                        }
                    )
                    continue

                if archive is None or not archive["readable"]:
                    result["missing_mms_parts"].append(
                        {
                            "mms_part_id": row["id"],
                            "archive_id": row["archive_id"],
                            "message_id": row["message_id"],
                            "part_id": row["part_id"],
                            "archive_member": member,
                            "reason": "source archive missing or unreadable",
                        }
                    )
                    continue

                if member not in archive["members"]:
                    result["missing_mms_parts"].append(
                        {
                            "mms_part_id": row["id"],
                            "archive_id": row["archive_id"],
                            "message_id": row["message_id"],
                            "part_id": row["part_id"],
                            "archive_member": member,
                            "reason": "ZIP member not found",
                        }
                    )
                    continue

                result["mms_parts_verified"] += 1

            message_rows = connection.execute(
                """
                SELECT id, device_id, message_type, message_id, archive_id
                FROM messages
                WHERE archive_id IS NOT NULL
                ORDER BY id
                """
            ).fetchall()
            result["message_archive_links"] = len(message_rows)

            for row in message_rows:
                archive = archive_cache.get(row["archive_id"])
                if archive is None or not archive["readable"]:
                    result["missing_message_archives"].append(
                        {
                            "message_db_id": row["id"],
                            "device_id": row["device_id"],
                            "message_type": row["message_type"],
                            "message_id": row["message_id"],
                            "archive_id": row["archive_id"],
                            "reason": "source archive missing or unreadable",
                        }
                    )

        return result

    @staticmethod
    def print_details(label, items, limit=20):
        if not items:
            return
        print(f"\n{label} ({len(items)}):")
        for item in items[:limit]:
            print(f"  {item}")
        if len(items) > limit:
            print(f"  ... {len(items) - limit} more")

    @staticmethod
    def print_report(result):
        print("Mint Message Archive — Archive Integrity Check")
        print("=" * 49)
        print()
        print(f"Devices checked:              {result['devices']}")
        print(f"Archives checked:             {result['archives']}")
        print(f"Archives readable:            {result['archives_readable']}")
        print(f"Archives corrupt:             {len(result['archives_corrupt'])}")
        print(f"Missing ZIP archives:         {len(result['missing_archives'])}")
        print()
        print(f"Database archive records:     {result['database_archive_records']}")
        print(f"Message archive links:        {result['message_archive_links']}")
        print(f"Broken message archive links: {len(result['missing_message_archives'])}")
        print()
        print(f"MMS part records:             {result['mms_part_records']}")
        print(f"MMS parts verified:           {result['mms_parts_verified']}")
        print(f"Missing MMS parts:            {len(result['missing_mms_parts'])}")
        print()
        print(f"MMS attachment records:       {result['attachment_records']}")
        print(f"Attachments verified:         {result['attachments_verified']}")
        print(f"Missing attachments:          {len(result['missing_attachments'])}")
        print(f"Unsafe attachment paths:      {len(result['unsafe_attachment_paths'])}")
        print(f"Unsafe MMS part paths:         {len(result['unsafe_mms_part_paths'])}")
        print()
        print(f"SQLite integrity check:       {result['integrity_check']}")

        ArchiveVerifier.print_details(
            "Corrupt archives", result["archives_corrupt"]
        )
        ArchiveVerifier.print_details(
            "Missing archives", result["missing_archives"]
        )
        ArchiveVerifier.print_details(
            "Broken message archive links",
            result["missing_message_archives"],
        )
        ArchiveVerifier.print_details(
            "Missing MMS parts", result["missing_mms_parts"]
        )
        ArchiveVerifier.print_details(
            "Missing attachments", result["missing_attachments"]
        )
        ArchiveVerifier.print_details(
            "Unsafe attachment paths", result["unsafe_attachment_paths"]
        )
        ArchiveVerifier.print_details(
            "Unsafe MMS part paths", result["unsafe_mms_part_paths"]
        )

        failed = (
            result["integrity_check"] != "ok"
            or result["archives_corrupt"]
            or result["missing_archives"]
            or result["missing_message_archives"]
            or result["missing_mms_parts"]
            or result["missing_attachments"]
            or result["unsafe_attachment_paths"]
            or result["unsafe_mms_part_paths"]
        )

        print()
        print("RESULT: FAIL" if failed else "RESULT: PASS")
        return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Verify preserved Mint Message Archive ZIP files and their "
            "SQLite index without modifying either."
        )
    )
    parser.add_argument(
        "--archive",
        default=str(Path.home() / "Phone Archive"),
        help="Archive root containing archive.db and devices/.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the verification result as JSON instead of the report.",
    )
    args = parser.parse_args()

    verifier = ArchiveVerifier(args.archive)

    try:
        result = verifier.verify()
    except (FileNotFoundError, RuntimeError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        import json

        print(json.dumps(result, indent=2, sort_keys=True))
        failed = (
            result["integrity_check"] != "ok"
            or result["archives_corrupt"]
            or result["missing_archives"]
            or result["missing_message_archives"]
            or result["missing_mms_parts"]
            or result["missing_attachments"]
            or result["unsafe_attachment_paths"]
            or result["unsafe_mms_part_paths"]
        )
        return 1 if failed else 0

    return verifier.print_report(result)


if __name__ == "__main__":
    raise SystemExit(main())
