#!/usr/bin/env python3
"""Migrate an existing v1 Snippet Locker SQLite database to v2, in place.

v2 change: adds a `language` TEXT column to `snippets`, defaulting existing
(and future) rows to "text". Existing rows are preserved untouched aside
from gaining the new column.

Run: python3 migrate.py
Env: DB_PATH (or MIURA_DB) points at the v1 database file to migrate.
     Defaults to "snippets_v1.db" if unset, matching the v1 app's default.

Safe to run more than once (idempotent): if the column already exists,
the script does nothing.
"""
import os
import sqlite3

DEFAULT_LANGUAGE = "text"

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "snippets_v1.db"


def migrate(db_path):
    if not os.path.exists(db_path):
        raise SystemExit(f"Database not found at {db_path!r}; nothing to migrate.")

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "snippets" not in tables:
            print("No 'snippets' table found; nothing to migrate.")
            return

        cols = [row[1] for row in conn.execute("PRAGMA table_info(snippets)").fetchall()]
        if "language" in cols:
            print("Column 'language' already present on 'snippets'; nothing to do.")
            return

        # SQLite's ALTER TABLE does not accept bind parameters in the DEFAULT
        # clause (it must be a constant literal), so embed a safely quoted
        # literal via SQLite's own quoting function instead of raw string
        # formatting.
        quoted_default = conn.execute("SELECT quote(?)", (DEFAULT_LANGUAGE,)).fetchone()[0]
        conn.execute(
            f"ALTER TABLE snippets ADD COLUMN language TEXT NOT NULL DEFAULT {quoted_default}"
        )
        conn.commit()

        count = conn.execute("SELECT COUNT(*) FROM snippets").fetchone()[0]
        print(
            f"Migration complete: added 'language' column to 'snippets' "
            f"(default {DEFAULT_LANGUAGE!r}). {count} existing row(s) preserved."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    migrate(DB_PATH)
