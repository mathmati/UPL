#!/usr/bin/env python3
"""Migrate a v1 room-bookings SQLite database to v2 IN PLACE.

v2 adds a single new column to the `bookings` table:
    attendees INTEGER NOT NULL DEFAULT 1

This script:
  - opens the existing database at DB_PATH (or MIURA_DB), default "bookings.db"
  - adds the `attendees` column if it is not already present
  - existing rows automatically get the default value (1) — no rows are
    dropped, no tables are recreated
  - is idempotent: running it again on an already-migrated database is a
    harmless no-op

Run with:
    python3 migrate.py
"""

import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "bookings.db"


def column_exists(conn, table, column):
    cols = conn.execute("PRAGMA table_info({})".format(table)).fetchall()
    return any(c[1] == column for c in cols)


def main():
    if not os.path.exists(DB_PATH):
        print("No database found at {} — nothing to migrate.".format(DB_PATH))
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='bookings'"
            ).fetchall()
        }
        if "bookings" not in tables:
            print("No 'bookings' table found in {} — nothing to migrate.".format(DB_PATH))
            return

        if column_exists(conn, "bookings", "attendees"):
            print("Column 'attendees' already present on 'bookings' — nothing to do.")
            return

        before = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]

        # ALTER TABLE ... ADD COLUMN with a DEFAULT preserves all existing
        # rows in place; SQLite backfills the default for every existing
        # row instead of rewriting/dropping the table.
        conn.execute(
            "ALTER TABLE bookings ADD COLUMN attendees INTEGER NOT NULL DEFAULT 1"
        )
        conn.commit()

        after = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        missing_default = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE attendees != 1"
        ).fetchone()[0]

        print(
            "Migrated {} -> v2: added 'attendees' column (default 1).".format(DB_PATH)
        )
        print("Rows before: {}, rows after: {} (should match).".format(before, after))
        print(
            "Rows with non-default attendees after migration: {} (should be 0 "
            "immediately post-migration).".format(missing_default)
        )
        if before != after:
            raise SystemExit(
                "ERROR: row count changed during migration ({} -> {}) — "
                "data may have been lost!".format(before, after)
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
