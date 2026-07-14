"""Deterministic schema migration: diff two bundles into an ordered
migration plan.

Design decisions (flagged for review):
- Migrations are an OPERATOR tool, not a bundle-authoring construct. There
  is deliberately no migration syntax in the .miura language — keeping the
  authoring guide small. The plan is a pure function of (old schema, new
  schema), so it is deterministic and reproducible like everything else.
- Step severity, chosen conservatively:
    * safe        — cannot lose data or fail on existing rows
                    (new table, new column WITH a literal default).
    * verify      — applies, but MIGHT fail against existing data the
                    engine can't see statically (adding UNIQUE, adding a
                    field require). Emitted, but the operator is warned.
    * destructive — loses data (drop column, drop table). Refused unless
                    --allow-destructive.
    * blocked     — cannot be expressed as a safe deterministic step
                    (add a NOT-NULL column with no default; change a
                    column's type). Refused; needs a hand-written step.
- Renames are undetectable from a pure schema diff (they look like
  drop+add). v0.5 does not attempt rename inference; a rename shows up as a
  destructive drop plus a blocked/safe add, and the operator is told.
- SQLite target. DROP COLUMN needs SQLite >= 3.35 (2021); assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .emit_sql import column_ddl, table_ddl, table_name

SEVERITY_ORDER = {"safe": 0, "verify": 1, "destructive": 2, "blocked": 3}


@dataclass
class Step:
    severity: str  # safe | verify | destructive | blocked
    summary: str
    sql: str = ""  # empty for blocked steps

    @property
    def emittable(self) -> bool:
        return self.severity != "blocked" and bool(self.sql)


@dataclass
class Plan:
    steps: list

    @property
    def worst(self) -> str:
        return max((s.severity for s in self.steps), key=lambda s: SEVERITY_ORDER[s], default="safe")

    @property
    def has_destructive(self) -> bool:
        return any(s.severity == "destructive" for s in self.steps)

    @property
    def has_blocked(self) -> bool:
        return any(s.severity == "blocked" for s in self.steps)


def _entities(app):
    return {e.name: e for e in app.entities}


def _lit(value) -> str:
    if value is True:
        return "1"
    if value is False:
        return "0"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def plan(old_app, new_app) -> Plan:
    """Diff old_app -> new_app into an ordered, deterministic plan.

    Ordering: creates first, then per-entity field changes (adds before
    drops), then drops of whole tables last — so a run stops before any
    destructive step if the operator declines them, having already applied
    every safe addition."""
    steps = []
    old_e, new_e = _entities(old_app), _entities(new_app)

    # auth tables (injected, not user entities)
    if new_app.auth and not old_app.auth:
        steps.append(Step("safe", "add auth tables (user, session)",
                          "CREATE TABLE IF NOT EXISTS user (\n    id TEXT NOT NULL PRIMARY KEY,\n    email TEXT NOT NULL UNIQUE,\n    password_hash TEXT NOT NULL,\n    salt TEXT NOT NULL,\n    role TEXT NOT NULL,\n    created_at TEXT NOT NULL\n);\nCREATE TABLE IF NOT EXISTS session (\n    token TEXT NOT NULL PRIMARY KEY,\n    user_id TEXT NOT NULL REFERENCES user(id),\n    created_at TEXT NOT NULL\n);"))
    if old_app.auth and not new_app.auth:
        steps.append(Step("destructive", "drop auth tables (user, session) and all accounts",
                          "DROP TABLE IF EXISTS session;\nDROP TABLE IF EXISTS user;"))

    # new entities -> CREATE (safe)
    for name in new_e:
        if name not in old_e:
            steps.append(Step("safe", f"create entity {name}", table_ddl(new_e[name], if_not_exists=False)))

    # entities present in both -> field-level diff
    for name in new_e:
        if name not in old_e:
            continue
        table = table_name(name)
        old_fields = {f.name: f for f in old_e[name].fields}
        new_fields = {f.name: f for f in new_e[name].fields}

        # added fields
        for fname, f in new_fields.items():
            if fname in old_fields:
                continue
            if f.auto or f.type == "ref" and f.auto_user:
                steps.append(Step("blocked", f"{name}.{fname}: cannot add an (auto)/managed field to a table with existing rows — backfill by hand"))
            elif f.has_default:
                sev = "verify" if f.unique else "safe"
                note = " [UNIQUE — will fail if existing rows share the default]" if f.unique else ""
                steps.append(Step(sev, f"add field {name}.{fname}{note}",
                                  f"ALTER TABLE {table} ADD COLUMN {column_ddl(f)} DEFAULT {_lit(f.default)};"))
            else:
                steps.append(Step("blocked", f"{name}.{fname}: new NOT NULL field has no (default) — existing rows can't satisfy it; add a (default) or backfill by hand"))

        # dropped fields
        for fname in old_fields:
            if fname not in new_fields:
                steps.append(Step("destructive", f"drop field {name}.{fname} (data in this column is lost)",
                                  f"ALTER TABLE {table} DROP COLUMN {fname};"))

        # changed fields (present in both)
        for fname, nf in new_fields.items():
            of = old_fields.get(fname)
            if of is None:
                continue
            if of.type != nf.type or of.ref_entity != nf.ref_entity:
                steps.append(Step("blocked", f"{name}.{fname}: type change {of.type}->{nf.type} can't be migrated automatically on SQLite — rebuild the table by hand"))
            elif nf.unique and not of.unique:
                steps.append(Step("verify", f"{name}.{fname}: add UNIQUE constraint [will fail if existing rows already collide]",
                                  f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_{fname} ON {table} ({fname});"))
            elif of.unique and not nf.unique:
                steps.append(Step("safe", f"{name}.{fname}: drop UNIQUE constraint",
                                  f"DROP INDEX IF EXISTS ux_{table}_{fname};"))

    # dropped entities -> DROP TABLE (destructive), last
    for name in old_e:
        if name not in new_e:
            steps.append(Step("destructive", f"drop entity {name} (all its rows are lost)",
                              f"DROP TABLE IF EXISTS {table_name(name)};"))

    steps.sort(key=lambda s: SEVERITY_ORDER[s.severity])  # stable: safe first, blocked last
    return Plan(steps=steps)
