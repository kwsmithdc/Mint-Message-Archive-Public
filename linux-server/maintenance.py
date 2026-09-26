#!/usr/bin/env python3

import argparse
import hashlib
import json
import sqlite3
import zipfile
from collections import defaultdict
from pathlib import Path


class DuplicateScanner:
    def __init__(self, archive_root):
        self.archive_root = Path(archive_root)
        self.database_path = self.archive_root / "archive.db"

    def connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _sha256(values):
        return hashlib.sha256(
            json.dumps(values, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    @classmethod
    def sms_fingerprint(cls, row):
        values = (
            row["device_id"],
            row["message_type"],
            row["thread_id"] or "",
            row["address"] or "",
            row["body"] or "",
            row["timestamp"] if row["timestamp"] is not None else "",
            row["sms_type"] if row["sms_type"] is not None else "",
            row["sms_read"] if row["sms_read"] is not None else "",
        )
        return cls._sha256(values)

    @classmethod
    def mms_fingerprint(cls, row, participants, parts, attachment_hashes):
        participant_values = tuple(
            sorted((p["address"] or "", p["role"] or "") for p in participants)
        )
        part_values = tuple(
            sorted(
                (
                    p["content_type"] or "",
                    p["name"] or "",
                    p["filename"] or "",
                    p["text"] or "",
                    p["size"] if p["size"] is not None else "",
                    attachment_hashes.get(p["part_id"], ""),
                )
                for p in parts
            )
        )
        values = (
            row["device_id"],
            row["message_type"],
            row["thread_id"] or "",
            row["address"] or "",
            row["body"] or "",
            row["subject"] or "",
            row["message_box"] if row["message_box"] is not None else "",
            row["timestamp"] if row["timestamp"] is not None else "",
            participant_values,
            part_values,
        )
        return cls._sha256(values)

    @staticmethod
    def attachment_hash(archive_path, archive_member):
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                with archive.open(archive_member) as source:
                    digest = hashlib.sha256()
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                    return digest.hexdigest()
        except (OSError, KeyError, zipfile.BadZipFile):
            return None

    def scan_messages(self):
        groups = defaultdict(list)
        unreadable_attachments = []

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM messages
                ORDER BY device_id, message_type, timestamp, id
                """
            ).fetchall()

            attachment_rows = connection.execute(
                """
                SELECT
                    a.device_id,
                    a.message_id,
                    a.part_id,
                    a.archive_path AS archive_member,
                    ar.archive_path AS source_archive_path
                FROM attachments a
                JOIN archives ar ON ar.id = a.archive_id
                ORDER BY a.device_id, a.message_id, a.part_id, a.id
                """
            ).fetchall()

            attachment_hashes_by_message = defaultdict(dict)
            for attachment in attachment_rows:
                digest = self.attachment_hash(
                    attachment["source_archive_path"],
                    attachment["archive_member"],
                )
                if digest is None:
                    unreadable_attachments.append(attachment)
                    continue
                attachment_hashes_by_message[
                    (attachment["device_id"], attachment["message_id"])
                ][attachment["part_id"]] = digest

            for row in rows:
                message_type = (row["message_type"] or "").upper()
                if message_type == "SMS":
                    fingerprint = self.sms_fingerprint(row)
                else:
                    participants = connection.execute(
                        """
                        SELECT address, role
                        FROM message_participants
                        WHERE device_id = ?
                          AND message_type = ?
                          AND message_id = ?
                        ORDER BY role, address
                        """,
                        (row["device_id"], row["message_type"], row["message_id"]),
                    ).fetchall()
                    parts = connection.execute(
                        """
                        SELECT part_id, content_type, name, filename, text, size
                        FROM mms_parts
                        WHERE device_id = ? AND message_id = ?
                        ORDER BY part_id
                        """,
                        (row["device_id"], row["message_id"]),
                    ).fetchall()
                    fingerprint = self.mms_fingerprint(
                        row,
                        participants,
                        parts,
                        attachment_hashes_by_message.get(
                            (row["device_id"], row["message_id"]), {}
                        ),
                    )
                groups[fingerprint].append(row)

        return (
            rows,
            [group for group in groups.values() if len(group) > 1],
            unreadable_attachments,
        )

    def scan_attachments(self):
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT a.*, ar.archive_path AS source_archive_path
                FROM attachments a
                JOIN archives ar ON ar.id = a.archive_id
                ORDER BY a.device_id, a.id
                """
            ).fetchall()

        content_groups = defaultdict(list)
        unreadable = []
        for row in rows:
            digest = self.attachment_hash(
                row["source_archive_path"], row["archive_path"]
            )
            if digest is None:
                unreadable.append(row)
                continue
            content_groups[(row["device_id"], digest)].append(row)

        # Identical bytes used by different messages are legitimate shared
        # content candidates, not duplicate database references. Only rows
        # referring to the same message and part are removable duplicates.
        duplicate_groups = []
        shared_content_groups = []
        for group in content_groups.values():
            if len(group) < 2:
                continue
            by_reference = defaultdict(list)
            for row in group:
                by_reference[(row["device_id"], row["message_id"], row["part_id"])].append(row)

            removable = [
                rows_for_reference
                for rows_for_reference in by_reference.values()
                if len(rows_for_reference) > 1
            ]
            if removable:
                duplicate_groups.extend(removable)
            if len(by_reference) > 1:
                shared_content_groups.append(group)

        return (
            rows,
            duplicate_groups,
            shared_content_groups,
            unreadable,
        )

    def remove_duplicate_messages(self, groups):
        removed = 0
        with self.connect() as connection:
            for group in groups:
                keep = min(group, key=lambda row: row["id"])
                for row in group:
                    if row["id"] == keep["id"]:
                        continue
                    connection.execute(
                        """
                        DELETE FROM message_participants
                        WHERE device_id = ? AND message_type = ? AND message_id = ?
                        """,
                        (row["device_id"], row["message_type"], row["message_id"]),
                    )
                    connection.execute(
                        "DELETE FROM mms_parts WHERE device_id = ? AND message_id = ?",
                        (row["device_id"], row["message_id"]),
                    )
                    connection.execute(
                        "DELETE FROM attachments WHERE device_id = ? AND message_id = ?",
                        (row["device_id"], row["message_id"]),
                    )
                    connection.execute(
                        "DELETE FROM messages WHERE id = ? AND device_id = ?",
                        (row["id"], row["device_id"]),
                    )
                    removed += 1
            connection.commit()
        return removed

    def remove_duplicate_attachment_records(self, groups):
        removed = 0
        with self.connect() as connection:
            for group in groups:
                keep = min(group, key=lambda row: row["id"])
                for row in group:
                    if row["id"] == keep["id"]:
                        continue
                    connection.execute(
                        "DELETE FROM attachments WHERE id = ? AND device_id = ?",
                        (row["id"], row["device_id"]),
                    )
                    removed += 1
            connection.commit()
        return removed


def print_message_report(groups):
    print("Duplicate Message Scan")
    print("----------------------")
    print(f"Potential duplicate groups: {len(groups)}")
    print(f"Potential duplicate records: {sum(len(g) - 1 for g in groups)}")
    for number, group in enumerate(groups, 1):
        print(f"\nGroup {number}:")
        for row in group:
            print(
                f"  ID {row['id']} | {row['message_type']} | "
                f"message_id={row['message_id']} | timestamp={row['timestamp']} | "
                f"address={row['address'] or ''}"
            )


def print_attachment_report(duplicate_groups, shared_content_groups, unreadable):
    print("\nDuplicate Attachment Scan")
    print("-------------------------")
    print(f"Duplicate groups: {len(duplicate_groups)}")
    print(f"Duplicate records: {sum(len(g) - 1 for g in duplicate_groups)}")
    print(f"Unreadable/missing attachment records: {len(unreadable)}")

    for number, group in enumerate(duplicate_groups, 1):
        print(f"\nRemovable duplicate group {number}:")
        for row in group:
            print(
                f"  ID {row['id']} | message_id={row['message_id']} | "
                f"part_id={row['part_id']} | {row['filename']} | "
                f"{row['size'] or 0:,} bytes | archive={row['archive_id']} | "
                f"member={row['archive_path']}"
            )

    for number, group in enumerate(shared_content_groups, 1):
        print(f"\nIdentical content used by multiple references {number}:")
        for row in group:
            print(
                f"  ID {row['id']} | message_id={row['message_id']} | "
                f"part_id={row['part_id']} | {row['filename']} | "
                f"{row['size'] or 0:,} bytes | archive={row['archive_id']} | "
                f"member={row['archive_path']}"
            )


def main():
    parser = argparse.ArgumentParser(
        description="Scan the Mint Message Archive SQLite index for potential duplicates."
    )
    parser.add_argument(
        "--archive",
        default=str(Path.home() / "Phone Archive"),
        help="Archive root containing archive.db (default: ~/Phone Archive)",
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove duplicate records from SQLite after confirmation. ZIP files are never modified.",
    )
    args = parser.parse_args()

    scanner = DuplicateScanner(args.archive)
    if not scanner.database_path.exists():
        raise SystemExit(f"Database not found: {scanner.database_path}")

    _, message_groups, message_unreadable = scanner.scan_messages()
    _, attachment_groups, shared_content_groups, attachment_unreadable = (
        scanner.scan_attachments()
    )

    print_message_report(message_groups)
    print_attachment_report(
        attachment_groups,
        shared_content_groups,
        attachment_unreadable,
    )

    if message_unreadable:
        print(
            f"\nWarning: {len(message_unreadable)} attachment records could not "
            "be read while building MMS duplicate fingerprints."
        )
        print(
            "Affected MMS records are still reported, but their attachment "
            "content could not be included in the fingerprint."
        )

    if not args.remove:
        print("\nDry run only. No database records or ZIP files were changed.")
        return

    duplicate_messages = sum(len(g) - 1 for g in message_groups)
    duplicate_attachments = sum(len(g) - 1 for g in attachment_groups)

    if not duplicate_messages and not duplicate_attachments:
        print(
            "\nNo duplicate records were found that are safe to remove. "
            "Identical attachment content referenced by different messages is retained."
        )
        return

    print(
        f"\nThis will remove {duplicate_messages} duplicate message records and "
        f"{duplicate_attachments} duplicate attachment records from SQLite."
    )
    print(
        "Identical attachment content referenced by different messages will NOT "
        "be removed."
    )
    print("Preserved ZIP archives will NOT be modified or deleted.")
    answer = input("Continue? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print("Cancelled. No changes were made.")
        return

    removed_messages = scanner.remove_duplicate_messages(message_groups)
    removed_attachments = scanner.remove_duplicate_attachment_records(
        attachment_groups
    )

    print(
        f"Removed {removed_messages} duplicate message records and "
        f"{removed_attachments} duplicate attachment records from SQLite."
    )
    print("Preserved ZIP archives were not modified.")


if __name__ == "__main__":
    main()
