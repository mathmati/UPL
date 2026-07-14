"""Migration engine: diff classification, refusal gates, and a real
apply against a live SQLite database with data preserved."""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "compiler"))

from miurac import load  # noqa: E402
from miurac.migrate import plan  # noqa: E402

BASE = """(miura 0.1
  (intent "base")
  (schema (entity Item
    (field id (id) (auto))
    (field name (text) (require (>= (len name) 1)))
    (field qty (int) (default 0))
    (field created_at (timestamp) (auto))))
  (workflow
    (action add (input (name text)) (effect (insert Item (name name))))
    (query list (from Item) (order-by created_at desc)))
  (ui (page home "/" (heading "Items")
    (form (action add) (field name (label "Name")))
    (list (query list) (item (text name))))))
"""


def variant(**repl):
    text = BASE
    for old, new in repl.items():
        text = text.replace(old.replace("__", " "), new)
    return load(text)


class TestPlan(unittest.TestCase):
    def sev(self, old, new):
        return {s.summary: s.severity for s in plan(old, new).steps}

    def test_no_change(self):
        self.assertEqual(plan(load(BASE), load(BASE)).steps, [])

    def test_add_field_with_default_is_safe(self):
        new = load(BASE.replace("(field qty (int) (default 0))",
                                "(field qty (int) (default 0))\n    (field tag (text) (default \"x\"))"))
        sev = self.sev(load(BASE), new)
        self.assertEqual(sev.get("add field Item.tag"), "safe")

    def test_add_notnull_no_default_is_blocked(self):
        new = load(BASE.replace("(field qty (int) (default 0))",
                                "(field qty (int) (default 0))\n    (field note (text))")
                        .replace("(effect (insert Item (name name)))",
                                 "(effect (insert Item (name name) (note \"n\")))"))
        step = next(s for s in plan(load(BASE), new).steps if "note" in s.summary)
        self.assertEqual(step.severity, "blocked")
        self.assertEqual(step.sql, "")

    def test_add_unique_field_is_verify(self):
        new = load(BASE.replace("(field qty (int) (default 0))",
                                "(field qty (int) (default 0))\n    (field slug (text) (unique) (default \"s\"))")
                        .replace("(effect (insert Item (name name)))",
                                 "(effect (insert Item (name name) (slug \"s\")))"))
        step = next(s for s in plan(load(BASE), new).steps if "add field Item.slug" in s.summary)
        self.assertEqual(step.severity, "verify")

    def test_drop_field_is_destructive(self):
        new = load(BASE.replace("\n    (field qty (int) (default 0))", ""))
        step = next(s for s in plan(load(BASE), new).steps if "drop field Item.qty" in s.summary)
        self.assertEqual(step.severity, "destructive")
        self.assertIn("DROP COLUMN qty", step.sql)

    def test_type_change_is_blocked(self):
        new = load(BASE.replace("(field qty (int) (default 0))", "(field qty (text) (default \"0\"))"))
        step = next(s for s in plan(load(BASE), new).steps if s.severity == "blocked")
        self.assertIn("type change", step.summary)

    def test_new_entity_is_safe_and_drop_is_destructive(self):
        two = """(miura 0.1
  (intent "two entities")
  (schema
    (entity Item
      (field id (id) (auto))
      (field name (text) (require (>= (len name) 1)))
      (field qty (int) (default 0))
      (field created_at (timestamp) (auto)))
    (entity Tag
      (field id (id) (auto))
      (field label (text) (require (>= (len label) 1)))))
  (workflow
    (action add (input (name text)) (effect (insert Item (name name))))
    (action addtag (input (label text)) (effect (insert Tag (label label))))
    (query list (from Item) (order-by created_at desc)))
  (ui (page home "/" (heading "Items")
    (form (action add) (field name (label "Name")))
    (list (query list) (item (text name))))))
"""
        p = plan(load(BASE), load(two))
        self.assertEqual(next(s for s in p.steps if "create entity Tag" in s.summary).severity, "safe")
        p_back = plan(load(two), load(BASE))
        self.assertEqual(next(s for s in p_back.steps if "drop entity Tag" in s.summary).severity, "destructive")

    def test_safe_steps_sort_before_destructive(self):
        # add a field and drop another in the same migration
        new = load(BASE.replace("(field qty (int) (default 0))",
                                "(field tag (text) (default \"x\"))"))
        sevs = [s.severity for s in plan(load(BASE), new).steps]
        # every 'safe' index precedes every 'destructive' index
        last_safe = max((i for i, s in enumerate(sevs) if s == "safe"), default=-1)
        first_destructive = min((i for i, s in enumerate(sevs) if s == "destructive"), default=len(sevs))
        self.assertLess(last_safe, first_destructive)


class TestMigrateCLI(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "compiler"))
        return subprocess.run([sys.executable, "-m", "miurac", "migrate", *args],
                              capture_output=True, text=True, env=env, cwd=ROOT)

    def test_apply_preserves_data_and_backfills(self):
        with tempfile.TemporaryDirectory() as tmp:
            v1 = os.path.join(tmp, "v1.miura")
            v2 = os.path.join(tmp, "v2.miura")
            with open(v1, "w") as fh:
                fh.write(BASE)
            with open(v2, "w") as fh:
                fh.write(BASE.replace("(field qty (int) (default 0))",
                                      "(field qty (int) (default 0))\n    (field tag (text) (default \"general\"))"))
            db = os.path.join(tmp, "app.db")
            conn = sqlite3.connect(db)
            conn.executescript("CREATE TABLE item (id TEXT PRIMARY KEY, name TEXT NOT NULL, qty INTEGER NOT NULL, created_at TEXT NOT NULL);")
            conn.execute("INSERT INTO item VALUES ('a', 'Ada', 3, '2026-01-01')")
            conn.commit()
            conn.close()

            res = self.run_cli(v1, v2, "--apply", db)
            self.assertEqual(res.returncode, 0, res.stderr)

            conn = sqlite3.connect(db)
            row = conn.execute("SELECT name, qty, tag FROM item").fetchone()
            conn.close()
            self.assertEqual(row, ("Ada", 3, "general"))

    def test_destructive_refused_without_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            v1 = os.path.join(tmp, "v1.miura")
            v2 = os.path.join(tmp, "v2.miura")
            with open(v1, "w") as fh:
                fh.write(BASE)
            with open(v2, "w") as fh:
                fh.write(BASE.replace("\n    (field qty (int) (default 0))", ""))
            db = os.path.join(tmp, "app.db")
            conn = sqlite3.connect(db)
            conn.executescript("CREATE TABLE item (id TEXT PRIMARY KEY, name TEXT NOT NULL, qty INTEGER NOT NULL, created_at TEXT NOT NULL);")
            conn.execute("INSERT INTO item VALUES ('a', 'Ada', 3, '2026-01-01')")
            conn.commit()
            conn.close()
            res = self.run_cli(v1, v2, "--apply", db)
            self.assertEqual(res.returncode, 1)
            self.assertIn("destructive", res.stderr)
            res2 = self.run_cli(v1, v2, "--apply", db, "--allow-destructive")
            self.assertEqual(res2.returncode, 0, res2.stderr)


if __name__ == "__main__":
    unittest.main()
