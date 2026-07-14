#!/usr/bin/env python3
"""Migrate a v1 Snippet Locker SQLite database to v2 in place.

v2 change: adds `language` (text, default "text") to the `snippets` table.

This script only ADDs the new column with SQLite's ALTER TABLE ... ADD COLUMN,
which backfills the default value into every existing row without dropping
or recreating any table, so all existing users, sessions, and snippets are
preserved untouched.

Run with `python3 migrate.py`. Reads DB_PATH (or MIURA_DB) from env, same as
app.py; defaults to snippets_v2.db if unset (matching app.py's default).
"""

import os
import sqlite3
import sys

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "snippets_v2.db"

DEFAULT_LANGUAGE = "text"


def column_exists(conn, table, column) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def main():
    if not os.path.exists(DB_PATH):
        print(f"No database found at {DB_PATH!r}; nothing to migrate.")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='snippets'"
            ).fetchall()
        }
        if "snippets" not in tables:
            print("No 'snippets' table found; nothing to migrate.")
            return

        if column_exists(conn, "snippets", "language"):
            print("Column 'language' already present on 'snippets'; nothing to do.")
            return

        before_count = conn.execute("SELECT COUNT(*) FROM snippets").fetchone()[0]

        # ALTER TABLE ... ADD COLUMN with a DEFAULT backfills the default value
        # into all existing rows in place; it does not drop or recreate the
        # table, so no existing data (snippets, users, sessions) is lost.
        conn.execute(
            "ALTER TABLE snippets ADD COLUMN language TEXT NOT NULL DEFAULT "
            + repr(DEFAULT_LANGUAGE)
        )
        conn.commit()

        after_count = conn.execute("SELECT COUNT(*) FROM snippets").fetchone()[0]
        backfilled = conn.execute(
            "SELECT COUNT(*) FROM snippets WHERE language = ?", (DEFAULT_LANGUAGE,)
        ).fetchone()[0]

        if after_count != before_count:
            print(
                f"ERROR: row count changed during migration ({before_count} -> {after_count})",
                file=sys.stderr,
            )
            sys.exit(1)

        print(
            f"Migrated {DB_PATH!r}: added 'language' column to 'snippets' "
            f"({after_count} rows preserved, {backfilled} defaulted to "
            f"{DEFAULT_LANGUAGE!r})."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
