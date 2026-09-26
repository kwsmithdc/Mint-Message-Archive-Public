#!/usr/bin/env python3

import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from archive_inventory import ArchiveInventory
from compare_databases import TABLE_SPECS, compare_table, connect as connect_database
from maintenance import DuplicateScanner
from rebuild_database import ArchiveRebuilder
from verify_archive import ArchiveVerifier


class ArchiveHealthReport:
    def __init__(self, archive_root):
        self.archive_root = Path(archive_root).expanduser().resolve()
        self.database_path = self.archive_root / "archive.db"

    def connect(self):
        if not self.database_path.is_file():
            raise FileNotFoundError(f"SQLite database not found: {self.database_path}")
        uri = f"file:{self.database_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def format_timestamp(value):
        if value is None:
            return "n/a"
        try:
            timestamp = int(value)
            if abs(timestamp) < 100_000_000_000:
                timestamp *= 1000
            return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).astimezone().strftime(
                "%Y-%m-%d %H:%M:%S %Z"
            )
        except (TypeError, ValueError, OverflowError, OSError):
            return str(value)

    def storage_bytes(self):
        total = 0
        for path in self.archive_root.rglob("*.zip"):
            try:
                total += path.stat().st_size
            except OSError:
                pass
        return total

    def collect(self, run_duplicates=True, check_recovery=False):
        inventory = ArchiveInventory(self.archive_root).report()
        verifier = ArchiveVerifier(self.archive_root)
        integrity = verifier.verify()

        with self.connect() as connection:
            devices = connection.execute(
                "SELECT device_id, device_alias, first_seen, last_seen FROM devices ORDER BY device_id"
            ).fetchall()

            archive_rows = connection.execute(
                """
                SELECT id, device_id, filename, archive_path, received_at
                FROM archives
                ORDER BY received_at, id
                """
            ).fetchall()

            message_counts = {
                row["message_type"]: row["count"]
                for row in connection.execute(
                    "SELECT message_type, COUNT(*) AS count FROM messages GROUP BY message_type ORDER BY message_type"
                )
            }

            total_messages = connection.execute(
                "SELECT COUNT(*) FROM messages"
            ).fetchone()[0]
            total_parts = connection.execute(
                "SELECT COUNT(*) FROM mms_parts"
            ).fetchone()[0]
            total_participants = connection.execute(
                "SELECT COUNT(*) FROM message_participants"
            ).fetchone()[0]
            total_attachments = connection.execute(
                "SELECT COUNT(*) FROM attachments"
            ).fetchone()[0]

            oldest = connection.execute(
                "SELECT message_type, message_id, timestamp FROM messages WHERE timestamp IS NOT NULL ORDER BY timestamp ASC, id ASC LIMIT 1"
            ).fetchone()
            newest = connection.execute(
                "SELECT message_type, message_id, timestamp FROM messages WHERE timestamp IS NOT NULL ORDER BY timestamp DESC, id DESC LIMIT 1"
            ).fetchone()

            device_stats = connection.execute(
                """
                SELECT
                    d.device_id,
                    d.device_alias,
                    d.first_seen,
                    d.last_seen,
                    COUNT(DISTINCT a.id) AS archives,
                    COUNT(DISTINCT m.id) AS messages,
                    COUNT(DISTINCT at.id) AS attachments
                FROM devices d
                LEFT JOIN archives a ON a.device_id = d.device_id
                LEFT JOIN messages m ON m.device_id = d.device_id
                LEFT JOIN attachments at ON at.device_id = d.device_id
                GROUP BY d.device_id, d.device_alias, d.first_seen, d.last_seen
                ORDER BY d.device_id
                """
            ).fetchall()

        duplicate_status = {
            "checked": False,
            "message_groups": None,
            "message_records": None,
            "attachment_groups": None,
            "attachment_records": None,
            "shared_content_groups": None,
            "unreadable_attachment_records": None,
        }

        if run_duplicates:
            scanner = DuplicateScanner(self.archive_root)
            _, message_groups, message_unreadable = scanner.scan_messages()
            _, attachment_groups, shared_content_groups, attachment_unreadable = (
                scanner.scan_attachments()
            )
            duplicate_status = {
                "checked": True,
                "message_groups": len(message_groups),
                "message_records": sum(len(group) - 1 for group in message_groups),
                "attachment_groups": len(attachment_groups),
                "attachment_records": sum(len(group) - 1 for group in attachment_groups),
                "shared_content_groups": len(shared_content_groups),
                "unreadable_attachment_records": len(
                    set(id(row) for row in message_unreadable + attachment_unreadable)
                ),
            }


        recovery = {
            "checked": False,
            "status": "NOT CHECKED",
            "rebuilt_database": None,
            "comparison": None,
        }

        if check_recovery:
            with tempfile.TemporaryDirectory(prefix="mint-message-archive-recovery-") as temp_dir:
                rebuilt_path = Path(temp_dir) / "rebuilt.db"
                try:
                    stats = ArchiveRebuilder(self.archive_root, rebuilt_path).rebuild()
                    production = connect_database(self.database_path)
                    rebuilt = connect_database(rebuilt_path)
                    try:
                        results = {
                            table: compare_table(production, rebuilt, table)
                            for table in TABLE_SPECS
                        }
                    finally:
                        production.close()
                        rebuilt.close()

                    passed = all(result["pass"] for result in results.values())
                    recovery = {
                        "checked": True,
                        "status": "PASS" if passed else "DIFFERENCES FOUND",
                        "rebuilt_database": stats,
                        "comparison": {
                            "status": "PASS" if passed else "DIFFERENCES FOUND",
                            "tables": {
                                table: {
                                    "production": result["production"],
                                    "rebuilt": result["rebuilt"],
                                    "match": result["pass"],
                                }
                                for table, result in results.items()
                            },
                        },
                    }
                except Exception as exc:
                    recovery = {
                        "checked": True,
                        "status": "FAIL",
                        "rebuilt_database": None,
                        "comparison": {"status": "ERROR", "error": str(exc)},
                    }

        return {
            "archive_root": str(self.archive_root),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "storage_bytes": inventory["storage_bytes"],
            "storage_gib": inventory["storage_bytes"] / (1024 ** 3),
            "devices": len(devices),
            "archives": len(archive_rows),
            "messages": total_messages,
            "messages_by_type": message_counts,
            "mms_parts": total_parts,
            "participants": total_participants,
            "attachments": total_attachments,
            "oldest_message": None if oldest is None else {
                "message_type": oldest["message_type"],
                "message_id": oldest["message_id"],
                "timestamp": oldest["timestamp"],
                "display": self.format_timestamp(oldest["timestamp"]),
            },
            "newest_message": None if newest is None else {
                "message_type": newest["message_type"],
                "message_id": newest["message_id"],
                "timestamp": newest["timestamp"],
                "display": self.format_timestamp(newest["timestamp"]),
            },
            "oldest_archive": None if not archive_rows else {
                "filename": archive_rows[0]["filename"],
                "received_at": archive_rows[0]["received_at"],
                "path": archive_rows[0]["archive_path"],
            },
            "newest_archive": None if not archive_rows else {
                "filename": archive_rows[-1]["filename"],
                "received_at": archive_rows[-1]["received_at"],
                "path": archive_rows[-1]["archive_path"],
            },
            "device_details": [dict(row) for row in device_stats],
            "inventory": {
                "devices": inventory["devices"],
                "archives": inventory["archives"],
                "storage_bytes": inventory["storage_bytes"],
                "storage_display": inventory["storage_display"],
            },
            "recovery": recovery,
            "integrity": {
                "result": "PASS" if not (
                    integrity["integrity_check"] != "ok"
                    or integrity["archives_corrupt"]
                    or integrity["missing_archives"]
                    or integrity["missing_message_archives"]
                    or integrity["missing_mms_parts"]
                    or integrity["missing_attachments"]
                    or integrity["unsafe_attachment_paths"]
                    or integrity["unsafe_mms_part_paths"]
                ) else "FAIL",
                "sqlite": integrity["integrity_check"],
                "archives_corrupt": len(integrity["archives_corrupt"]),
                "missing_archives": len(integrity["missing_archives"]),
                "broken_message_archive_links": len(integrity["missing_message_archives"]),
                "missing_mms_parts": len(integrity["missing_mms_parts"]),
                "missing_attachments": len(integrity["missing_attachments"]),
                "unsafe_attachment_paths": len(integrity["unsafe_attachment_paths"]),
                "unsafe_mms_part_paths": len(integrity["unsafe_mms_part_paths"]),
            },
            "duplicates": duplicate_status,
        }

    @staticmethod
    def print_report(report):
        print("Mint Message Archive — Archive Health Report")
        print("=" * 48)
        print()
        print(f"Archive root:                {report['archive_root']}")
        print(f"Report generated:            {report['generated_at']}")
        print(f"Archive storage:             {report['storage_bytes']:,} bytes ({report['storage_gib']:.2f} GiB)")
        print()

        print("ARCHIVE INVENTORY")
        print("-----------------")
        print(f"Devices:                     {report['inventory']['devices']}")
        print(f"Preserved archives:          {report['inventory']['archives']}")
        print(f"Preserved ZIP storage:       {report['inventory']['storage_bytes']:,} bytes ({report['inventory']['storage_display']})")
        print()
        print("DATABASE")
        print("--------")
        print(f"Devices:                     {report['devices']}")
        print(f"Archives:                    {report['archives']}")
        print(f"Messages:                    {report['messages']:,}")
        for message_type, count in sorted(report["messages_by_type"].items()):
            print(f"  {message_type}:              {count:,}")
        print(f"MMS parts:                   {report['mms_parts']:,}")
        print(f"Participants:                {report['participants']:,}")
        print(f"Attachments:                 {report['attachments']:,}")
        print()

        for label, key in (("Oldest message", "oldest_message"), ("Newest message", "newest_message")):
            item = report[key]
            if item:
                print(f"{label}:             {item['display']} ({item['message_type']} {item['message_id']})")
            else:
                print(f"{label}:             n/a")

        for label, key in (("Oldest archive", "oldest_archive"), ("Newest archive", "newest_archive")):
            item = report[key]
            if item:
                print(f"{label}:             {item['received_at']} ({item['filename']})")
            else:
                print(f"{label}:             n/a")

        print()
        print("INTEGRITY")
        print("---------")
        integrity = report["integrity"]
        print(f"Overall:                     {integrity['result']}")
        print(f"SQLite:                      {integrity['sqlite']}")
        print(f"Corrupt archives:            {integrity['archives_corrupt']}")
        print(f"Missing archives:            {integrity['missing_archives']}")
        print(f"Broken message links:        {integrity['broken_message_archive_links']}")
        print(f"Missing MMS parts:           {integrity['missing_mms_parts']}")
        print(f"Missing attachments:         {integrity['missing_attachments']}")
        print(f"Unsafe attachment paths:     {integrity['unsafe_attachment_paths']}")
        print(f"Unsafe MMS part paths:       {integrity['unsafe_mms_part_paths']}")
        print()


        print("RECOVERY READINESS")
        print("------------------")
        recovery = report["recovery"]
        print(f"Status:                      {recovery['status']}")
        if not recovery["checked"]:
            print("Run with --check-recovery to rebuild and compare a temporary database.")
        elif recovery["rebuilt_database"]:
            rebuilt = recovery["rebuilt_database"]
            print(f"Rebuilt devices:             {rebuilt['devices']}")
            print(f"Rebuilt archives:            {rebuilt['archives']}")
            print(f"Rebuilt SMS:                 {rebuilt['sms']:,}")
            print(f"Rebuilt MMS:                 {rebuilt['mms']:,}")
            print(f"Rebuilt MMS parts:           {rebuilt['mms_parts']:,}")
            print(f"Rebuilt participants:        {rebuilt['participants']:,}")
            print(f"Rebuilt attachments:         {rebuilt['attachments']:,}")
        print()

        print("DUPLICATE MAINTENANCE")
        print("---------------------")
        duplicates = report["duplicates"]
        if not duplicates["checked"]:
            print("Status:                      not run")
        else:
            print("Status:                      checked")
            print(f"Duplicate message groups:    {duplicates['message_groups']}")
            print(f"Duplicate message records:   {duplicates['message_records']}")
            print(f"Duplicate attachment groups: {duplicates['attachment_groups']}")
            print(f"Duplicate attachment records:{duplicates['attachment_records']}")
            print(f"Shared-content groups:       {duplicates['shared_content_groups']}")
            print(f"Unreadable attachment refs:  {duplicates['unreadable_attachment_records']}")
        print()

        print("DEVICES")
        print("-------")
        for device in report["device_details"]:
            alias = device["device_alias"] or "(no alias)"
            print(
                f"{alias} [{device['device_id']}] — "
                f"archives={device['archives']}, messages={device['messages']}, "
                f"attachments={device['attachments']}, last_seen={device['last_seen']}"
            )

        print()
        print(
            "RESULT: PASS"
            if integrity["result"] == "PASS"
            and (not recovery["checked"] or recovery["status"] == "PASS")
            else "RESULT: FAIL"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Report the health of a Mint Message Archive without modifying it."
    )
    parser.add_argument(
        "--archive",
        default=str(Path.home() / "Phone Archive"),
        help="Archive root containing archive.db and devices/.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON.",
    )
    parser.add_argument(
        "--skip-duplicates",
        action="store_true",
        help="Skip the duplicate scan for a faster health report.",
    )

    parser.add_argument(
        "--check-recovery",
        action="store_true",
        help="Rebuild the database in a temporary directory and compare it with production.",
    )
    args = parser.parse_args()

    try:
        report = ArchiveHealthReport(args.archive).collect(
            run_duplicates=not args.skip_duplicates,
            check_recovery=args.check_recovery
        )
    except (FileNotFoundError, RuntimeError, sqlite3.Error, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        ArchiveHealthReport.print_report(report)

    if report["integrity"]["result"] != "PASS":
        return 1
    if report["recovery"]["checked"] and report["recovery"]["status"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
