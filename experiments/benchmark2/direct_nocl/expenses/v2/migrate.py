#!/usr/bin/env python3
"""Migrate an existing v1 expenses database to the v2 schema, in place.

v2 change: adds a `category` (TEXT, default "general") column to the
`claims` table. Existing rows get the default value. Safe to run multiple
times (idempotent) and safe to run against a database that is already v2.

Run: python3 migrate.py
Env: DB_PATH / MIURA_DB (default expenses.db) - the database to migrate.
"""

import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "expenses.db"

DEFAULT_CATEGORY = "general"


def main():
    if not os.path.exists(DB_PATH):
        print(f"No database found at {DB_PATH!r}; nothing to migrate.")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(claims)").fetchall()]
        if not cols:
            print(f"No 'claims' table found in {DB_PATH!r}; nothing to migrate.")
            return

        if "category" in cols:
            print("Database already has 'category' column; nothing to do.")
            return

        conn.execute(
            "ALTER TABLE claims ADD COLUMN category TEXT NOT NULL DEFAULT '%s'"
            % DEFAULT_CATEGORY
        )
        conn.commit()

        count = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        print(
            f"Migrated {DB_PATH!r}: added 'category' column to 'claims' "
            f"(default {DEFAULT_CATEGORY!r}), {count} existing row(s) preserved."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
