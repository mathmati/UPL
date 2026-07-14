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


def column_ddl(f) -> str:
    """The column definition for a field, as it appears in CREATE TABLE."""
    if f.type == "ref":
        col = f"{f.name} TEXT NOT NULL REFERENCES {table_name(f.ref_entity)}(id)"
    else:
        col = f"{f.name} {_SQL_TYPES[f.type]} NOT NULL"
        if f.type == "id":
            col += " PRIMARY KEY"
    if f.unique and f.type != "id":
        col += " UNIQUE"
    return col


def table_ddl(entity, if_not_exists: bool = True) -> str:
    ine = "IF NOT EXISTS " if if_not_exists else ""
    cols = ",\n".join("    " + column_ddl(f) for f in entity.fields)
    return f"CREATE TABLE {ine}{table_name(entity.name)} (\n{cols}\n);"


def emit_sql(app: App, header: str) -> str:
    lines = [f"-- {line}" for line in header.splitlines()]
    if app.auth:
        lines.append(_AUTH_TABLES)
    for e in app.entities:
        lines.append("")
        lines.append(table_ddl(e))
    return "\n".join(lines) + "\n"
