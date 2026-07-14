#!/usr/bin/env python3
"""
Migrate a v1 "Shared docs" SQLite database to v2 IN PLACE.

v2 change: adds `archived` (bool, default false) to the `docs` table.

This script is safe to run multiple times (idempotent) and never drops or
recreates tables — it only adds the new column (via ALTER TABLE ... ADD
COLUMN) when it is missing, so all existing rows (users, sessions, docs)
are preserved untouched and existing docs simply take the new field's
default value (0 / false).

Usage:
    DB_PATH=/path/to/docs.db python3 migrate.py
    # or
    python3 migrate.py /path/to/docs.db
"""

import os
import sqlite3
import sys


def resolve_db_path():
    if len(sys.argv) > 1:
        return sys.argv[1]
    return os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "docs_v1.db"


def migrate(db_path):
    if not os.path.exists(db_path):
        print(f"No database found at {db_path!r}; nothing to migrate "
              f"(a fresh v2 app will create one with the correct schema).")
        return

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "docs" not in tables:
            print(f"No 'docs' table found in {db_path!r}; nothing to migrate.")
            return

        cols = [row[1] for row in conn.execute("PRAGMA table_info(docs)").fetchall()]

        if "archived" in cols:
            print("Column 'archived' already present on 'docs' — nothing to do.")
            return

        before_count = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]

        conn.execute(
            "ALTER TABLE docs ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()

        after_count = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        still_default = conn.execute(
            "SELECT COUNT(*) FROM docs WHERE archived = 0"
        ).fetchone()[0]

        assert after_count == before_count, "row count changed during migration!"
        assert still_default == after_count, "not all existing rows got the default!"

        print(
            f"Migrated {db_path!r}: added 'archived' column to 'docs' "
            f"(default 0/false). Preserved {after_count} row(s)."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    migrate(resolve_db_path())
