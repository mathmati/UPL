#!/usr/bin/env python3
"""Migrate an existing v1 'Shared docs' SQLite database to v2 in place.

v2 change: docs gains an `archived` (bool, default false) column.

This script is idempotent: running it more than once, or against a database
that is already on v2 (or a brand new/empty database), is safe and will not
lose data.

Usage:
    DB_PATH=/path/to/docs.db python3 migrate.py
"""

import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "docs_v1.db"


def table_exists(conn, name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def column_exists(conn, table, column):
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c[1] == column for c in cols)


def migrate(db_path):
    conn = sqlite3.connect(db_path)
    try:
        # Make sure the baseline tables exist (covers running against a
        # fresh/empty database file too, matching the app's own init_db).
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(owner_id) REFERENCES users(id)
            );
            """
        )
        conn.commit()

        if not column_exists(conn, "docs", "archived"):
            # Existing rows get the new field's default: false (0).
            conn.execute("ALTER TABLE docs ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            conn.commit()
            print(f"Migrated {db_path}: added docs.archived (default 0).")
        else:
            print(f"{db_path} already has docs.archived; nothing to do.")
    finally:
        conn.close()


def main():
    migrate(DB_PATH)


if __name__ == "__main__":
    main()
