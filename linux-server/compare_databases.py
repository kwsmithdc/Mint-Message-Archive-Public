#!/usr/bin/env python3

"""Compare two Mint Message Archive SQLite databases read-only.

The comparison ignores SQLite-generated row IDs and archive_id values, which
may legitimately differ after a rebuild. Logical archive references are
resolved using (device_id, filename).
"""

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path


TABLE_SPECS = {
    "devices": {
        "key": ("device_id",),
        "columns": ("device_id", "device_alias", "first_seen", "last_seen"),
    },
    "archives": {
        "key": ("device_id", "filename"),
        "columns": (
            "device_id",
            "filename",
            "archive_path",
            "received_at",
        ),
    },
    "messages": {
        "key": ("device_id", "message_type", "message_id"),
        "columns": (
            "device_id",
            "message_type",
            "message_id",
            "thread_id",
            "address",
            "body",
            "subject",
            "message_box",
            "sms_type",
            "sms_read",
            "timestamp",
            "_archive",
        ),
    },
    "mms_parts": {
        "key": ("device_id", "message_id", "part_id"),
        "columns": (
            "device_id",
            "message_id",
            "part_id",
            "content_type",
            "name",
            "filename",
            "text",
            "archive_member",
            "size",
            "_archive",
        ),
    },
    "message_participants": {
        "key": ("device_id", "message_type", "message_id", "address", "role"),
        "columns": (
            "device_id",
            "message_type",
            "message_id",
            "address",
            "role",
        ),
    },
    "attachments": {
        "key": (
            "device_id",
            "message_id",
            "part_id",
            "filename",
            "archive_path",
        ),
        "columns": (
            "device_id",
            "message_id",
            "part_id",
            "filename",
            "mime_type",
            "size",
            "archive_path",
            "_archive",
        ),
    },
}


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def archive_map(connection):
    rows = connection.execute(
        """
        SELECT device_id, filename, archive_path, received_at
        FROM archives
        ORDER BY device_id, filename
        """
    ).fetchall()
    return {
        (row["device_id"], row["filename"]): (
            row["archive_path"],
            row["received_at"],
        )
        for row in rows
    }


def logical_archive(connection, archive_id, maps):
    if archive_id is None:
        return None
    row = connection.execute(
        "SELECT device_id, filename FROM archives WHERE id = ?",
        (archive_id,),
    ).fetchone()
    if row is None:
        return ("<missing>", str(archive_id))
    return (row["device_id"], row["filename"])


def table_rows(connection, table, archive_map_cache):
    spec = TABLE_SPECS[table]
    sql_columns = []
    for column in spec["columns"]:
        if column == "_archive":
            sql_columns.append("archive_id")
        else:
            sql_columns.append(column)

    rows = connection.execute(
        f"SELECT {', '.join(sql_columns)} FROM {table}"
    ).fetchall()

    normalized = []
    for row in rows:
        values = []
        for column in spec["columns"]:
            if column == "_archive":
                values.append(logical_archive(
                    connection, row["archive_id"], archive_map_cache
                ))
            else:
                values.append(row[column])
        normalized.append(tuple(values))
    return normalized


def key_for(row, spec):
    indexes = [spec["columns"].index(column) for column in spec["key"]]
    return tuple(row[index] for index in indexes)


def compare_table(production, rebuilt, table):
    spec = TABLE_SPECS[table]
    prod_rows = table_rows(production, table, None)
    rebuilt_rows = table_rows(rebuilt, table, None)

    prod_counter = Counter(prod_rows)
    rebuilt_counter = Counter(rebuilt_rows)

    missing = prod_counter - rebuilt_counter
    extra = rebuilt_counter - prod_counter

    return {
        "production": len(prod_rows),
        "rebuilt": len(rebuilt_rows),
        "missing": missing,
        "extra": extra,
        "pass": not missing and not extra,
    }


def print_differences(result, spec, limit=5):
    indexes = {column: i for i, column in enumerate(spec["columns"])}

    if result["missing"]:
        print("  Missing from rebuilt:")
        for row, count in list(result["missing"].items())[:limit]:
            print(f"    {format_row(row, spec)}" + (f" (x{count})" if count > 1 else ""))

    if result["extra"]:
        print("  Extra in rebuilt:")
        for row, count in list(result["extra"].items())[:limit]:
            print(f"    {format_row(row, spec)}" + (f" (x{count})" if count > 1 else ""))


def format_row(row, spec):
    parts = []
    for column, value in zip(spec["columns"], row):
        parts.append(f"{column}={value!r}")
    return ", ".join(parts)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Compare two Mint Message Archive databases without modifying either."
        )
    )
    parser.add_argument(
        "--production",
        required=True,
        help="Production archive.db path.",
    )
    parser.add_argument(
        "--rebuilt",
        required=True,
        help="Rebuilt archive.db path.",
    )
    parser.add_argument(
        "--max-differences",
        type=int,
        default=5,
        help="Maximum missing/extra rows printed per table (default: 5).",
    )
    args = parser.parse_args()

    production_path = Path(args.production).expanduser().resolve()
    rebuilt_path = Path(args.rebuilt).expanduser().resolve()

    if not production_path.is_file():
        print(f"ERROR: production database does not exist: {production_path}", file=sys.stderr)
        return 2
    if not rebuilt_path.is_file():
        print(f"ERROR: rebuilt database does not exist: {rebuilt_path}", file=sys.stderr)
        return 2
    if args.max_differences < 0:
        print("ERROR: --max-differences must be zero or greater", file=sys.stderr)
        return 2

    production = connect(production_path)
    rebuilt = connect(rebuilt_path)

    try:
        print("Mint Message Archive — Database Comparison")
        print("=" * 60)
        print()
        print(f"Production: {production_path}")
        print(f"Rebuilt:    {rebuilt_path}")
        print()
        print(f"{'Table':<25} {'Production':>12} {'Rebuilt':>12} {'Match':>10}")
        print("-" * 60)

        all_match = True
        results = {}

        for table, spec in TABLE_SPECS.items():
            result = compare_table(production, rebuilt, table)
            results[table] = result
            all_match &= result["pass"]
            print(
                f"{table:<25} "
                f"{result['production']:>12,} "
                f"{result['rebuilt']:>12,} "
                f"{'YES' if result['pass'] else 'NO':>10}"
            )

        print()
        for table, result in results.items():
            if not result["pass"]:
                print(f"{table.upper()} DIFFERENCES")
                print("-" * 60)
                print_differences(
                    result,
                    TABLE_SPECS[table],
                    limit=args.max_differences,
                )
                print()

        print("RESULT:", "PASS" if all_match else "DIFFERENCES FOUND")
        return 0 if all_match else 1
    finally:
        production.close()
        rebuilt.close()


if __name__ == "__main__":
    raise SystemExit(main())
