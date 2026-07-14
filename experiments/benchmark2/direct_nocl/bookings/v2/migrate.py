#!/usr/bin/env python3
"""Migrate a v1 bookings SQLite database to v2 IN PLACE.

v2 change: adds `attendees` (INTEGER, default 1) to the `bookings` table.

Usage:
    DB_PATH=/path/to/bookings.db python3 migrate.py

Reads DB_PATH (or MIURA_DB); defaults to bookings_v2.db like the app does.
Safe to run multiple times (idempotent): if the column already exists it
does nothing. Existing rows get attendees = 1 (the default). No rows are
dropped or altered otherwise.
"""

import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "bookings_v2.db"

DEFAULT_ATTENDEES = 1


def column_exists(conn, table, column):
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c[1] == column for c in cols)


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"No database found at {DB_PATH!r}; nothing to migrate.")
        return

    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "bookings" not in tables:
            print("No 'bookings' table found; nothing to migrate.")
            return

        if column_exists(conn, "bookings", "attendees"):
            print("Column 'attendees' already present; database is already v2.")
            return

        conn.execute("BEGIN")
        conn.execute(
            "ALTER TABLE bookings ADD COLUMN attendees INTEGER NOT NULL DEFAULT %d"
            % DEFAULT_ATTENDEES
        )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        print(
            f"Migration complete: added 'attendees' column to 'bookings' "
            f"({count} existing row(s) defaulted to {DEFAULT_ATTENDEES})."
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
