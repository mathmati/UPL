#!/usr/bin/env python3
"""Migrate an existing v1 expenses database to v2 in place.

v2 change: adds a `category` column (TEXT, default "general") to the
`claims` table. This uses ALTER TABLE ... ADD COLUMN, which preserves all
existing rows and data (SQLite does not rewrite/rebuild other tables and
does not drop any rows) - existing claims get the default value.

Runnable as: python3 migrate.py
Reads the database path from DB_PATH (or MIURA_DB) env var, same as app.py.
Safe to run multiple times (idempotent): if the column already exists, it
does nothing.
"""
import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "expenses.db"


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

        print("Adding 'category' column to 'claims' table (default 'general')...")
        conn.execute(
            "ALTER TABLE claims ADD COLUMN category TEXT NOT NULL DEFAULT 'general'"
        )
        conn.commit()

        count = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        print(f"Migration complete. {count} existing claim row(s) preserved, "
              f"each with category='general'.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
