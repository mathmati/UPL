"""Deterministic SQL (SQLite) schema emitter."""

from __future__ import annotations

from .model import App

_SQL_TYPES = {"id": "TEXT", "text": "TEXT", "int": "INTEGER", "bool": "INTEGER", "timestamp": "TEXT"}


def table_name(entity_name: str) -> str:
    out = []
    for i, ch in enumerate(entity_name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


_AUTH_TABLES = """
CREATE TABLE IF NOT EXISTS user (
    id TEXT NOT NULL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
    token TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES user(id),
    created_at TEXT NOT NULL
);"""


def emit_sql(app: App, header: str) -> str:
    lines = [f"-- {line}" for line in header.splitlines()]
    if app.auth:
        lines.append(_AUTH_TABLES)
    for e in app.entities:
        lines.append("")
        lines.append(f"CREATE TABLE IF NOT EXISTS {table_name(e.name)} (")
        cols = []
        for f in e.fields:
            if f.type == "ref":
                col = f"    {f.name} TEXT NOT NULL REFERENCES {table_name(f.ref_entity)}(id)"
            else:
                col = f"    {f.name} {_SQL_TYPES[f.type]} NOT NULL"
                if f.type == "id":
                    col += " PRIMARY KEY"
            if f.unique and f.type != "id":
                col += " UNIQUE"
            cols.append(col)
        lines.append(",\n".join(cols))
        lines.append(");")
    return "\n".join(lines) + "\n"
