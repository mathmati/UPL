"""Compiler tests: parsing, canonical form, validation, determinism."""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "compiler"))

from miurac import BundleError, load  # noqa: E402
from miurac.sexpr import dumps, parse  # noqa: E402

EXAMPLE = os.path.join(ROOT, "examples", "tasks.miura")


def read_example():
    with open(EXAMPLE, "r", encoding="utf-8") as fh:
        return fh.read()


class TestSexpr(unittest.TestCase):
    def test_roundtrip_is_idempotent(self):
        tree = parse(read_example())
        once = dumps(tree)
        twice = dumps(parse(once))
        self.assertEqual(once, twice)

    def test_atoms(self):
        self.assertEqual(parse("(a 1 true false \"x\\ny\")"), [parse("a"), 1, True, False, "x\ny"][0:1] + [1, True, False, "x\ny"])

    def test_comments_ignored(self):
        self.assertEqual(dumps(parse("(a b) ; tail")), dumps(parse("; head\n(a b)")))


class TestLoad(unittest.TestCase):
    def test_example_loads(self):
        app = load(read_example())
        self.assertEqual([e.name for e in app.entities], ["Task"])
        self.assertEqual([a.name for a in app.actions], ["create_task", "toggle_task", "delete_task"])
        self.assertEqual([q.name for q in app.queries], ["list_tasks"])
        self.assertEqual(len(app.bundle_hash), 64)

    def test_hash_ignores_formatting(self):
        text = read_example()
        reformatted = "  " + text.replace("\n", "\n ")
        self.assertEqual(load(text).bundle_hash, load(reformatted).bundle_hash)

    def assert_error(self, text, fragment):
        with self.assertRaises(BundleError) as ctx:
            load(text)
        self.assertIn(fragment, str(ctx.exception))

    def test_unknown_entity_in_query(self):
        bad = read_example().replace("(from Task)", "(from Nope)")
        self.assert_error(bad, "unknown entity 'Nope'")

    def test_unknown_action_in_form(self):
        bad = read_example().replace("(action create_task)\n        (field title", "(action create_missing)\n        (field title")
        self.assert_error(bad, "unknown action 'create_missing'")

    def test_unbound_name_in_requires(self):
        bad = read_example().replace("(requires (>= (len title) 1))", "(requires (>= (len nope) 1))")
        self.assert_error(bad, "unbound names: nope")

    def test_effect_unknown_field(self):
        bad = read_example().replace("(insert Task (title title) (done false))", "(insert Task (title title) (bogus false))")
        self.assert_error(bad, "unknown field 'bogus'")

    def test_missing_required_assignment(self):
        bad = (
            read_example()
            .replace("(field done (bool) (default false))", "(field done (bool))")
            .replace("(insert Task (title title) (done false))", "(insert Task (title title))")
        )
        self.assert_error(bad, "must assign field 'done'")


class TestBundleTests(unittest.TestCase):
    def run_bundle(self, text):
        from miurac.runner import run_tests
        return run_tests(load(text))

    def test_example_cases_pass(self):
        results = self.run_bundle(read_example())
        self.assertEqual([r.name for r in results], ["lifecycle", "contracts_reject_bad_titles", "newest_first"])
        self.assertTrue(all(r.ok for r in results), [r.failures for r in results])

    def test_failing_expect_is_reported(self):
        bad = read_example().replace('(expect (= (. result done) false))', '(expect (= (. result done) true))', 1)
        results = self.run_bundle(bad)
        lifecycle = results[0]
        self.assertFalse(lifecycle.ok)
        self.assertIn("expect failed", lifecycle.failures[0])

    def test_fail_step_that_succeeds_is_reported(self):
        bad = read_example().replace('(fail create_task (title ""))', '(fail create_task (title "valid title"))')
        results = self.run_bundle(bad)
        case = next(r for r in results if r.name == "contracts_reject_bad_titles")
        self.assertFalse(case.ok)
        self.assertIn("expected a contract or permission rejection", case.failures[0])

    def test_row_binding_asserts_ordering(self):
        results = self.run_bundle(read_example())
        newest = next(r for r in results if r.name == "newest_first")
        self.assertTrue(newest.ok, newest.failures)

    def test_row_binding_wrong_order_fails(self):
        bad = read_example().replace('(expect (= (. top title) "newer"))', '(expect (= (. top title) "older"))')
        results = self.run_bundle(bad)
        newest = next(r for r in results if r.name == "newest_first")
        self.assertFalse(newest.ok)
        self.assertIn("expect failed", newest.failures[0])

    def test_row_binding_out_of_range_fails(self):
        bad = read_example().replace("(row 0 (as top))", "(row 9 (as top))")
        results = self.run_bundle(bad)
        newest = next(r for r in results if r.name == "newest_first")
        self.assertFalse(newest.ok)
        self.assertIn("out of range", newest.failures[0])

    def test_unknown_action_in_case_is_compile_error(self):
        bad = read_example().replace("(do toggle_task (id (. t id)) (expect (= (. result done) true)))", "(do missing_action (id (. t id)))")
        with self.assertRaises(BundleError) as ctx:
            load(bad)
        self.assertIn("unknown action 'missing_action'", str(ctx.exception))

    def test_unbound_binding_is_compile_error(self):
        bad = read_example().replace("(do toggle_task (id (. t id)) (expect (= (. result done) true)))", "(do toggle_task (id (. ghost id)))")
        with self.assertRaises(BundleError) as ctx:
            load(bad)
        self.assertIn("unbound names: ghost", str(ctx.exception))


AUTH_EXAMPLE = os.path.join(ROOT, "examples", "team-tasks.miura")


def read_auth_example():
    with open(AUTH_EXAMPLE, "r", encoding="utf-8") as fh:
        return fh.read()


class TestAuth(unittest.TestCase):
    def assert_error(self, text, fragment):
        with self.assertRaises(BundleError) as ctx:
            load(text)
        self.assertIn(fragment, str(ctx.exception))

    def test_auth_example_loads_and_passes(self):
        from miurac.runner import run_tests
        app = load(read_auth_example())
        self.assertEqual(app.auth.roles, ["admin", "member"])
        results = run_tests(app)
        self.assertTrue(all(r.ok for r in results), [(r.name, r.failures) for r in results])

    def test_allow_without_auth_rejected(self):
        bad = read_example().replace("(action create_task", "(action create_task\n      (allow signed-in)", 1)
        self.assert_error(bad, "(allow ...) requires an (auth ...) section")

    def test_unknown_role_rejected(self):
        bad = read_auth_example().replace("(allow (role admin))", "(allow (role superuser))")
        self.assert_error(bad, "unknown role")

    def test_owner_rule_requires_ref_user_field(self):
        bad = read_auth_example().replace("(allow (owner owner))", "(allow (owner title))", 1)
        self.assert_error(bad, "must be a (ref User) field")

    def test_at_user_needs_signed_in_guarantee(self):
        bad = read_auth_example().replace(
            "(query my_tasks\n      (allow signed-in)", "(query my_tasks\n      (allow anyone)", 1)
        self.assert_error(bad, "@user")

    def test_by_requires_prior_user_step(self):
        bad = read_auth_example().replace("(user alice member)\n      (user bob member)", "(user bob member)", 1)
        self.assert_error(bad, "(by alice): no prior (user alice role) step")

    def test_unique_violation_at_runtime(self):
        from miurac.runner import run_tests
        bad = read_auth_example().replace('(fail create_task (slug "one-slug") (title "Second") (by gene))',
                                          '(do create_task (slug "one-slug") (title "Second") (by gene))')
        results = run_tests(load(bad))
        case = next(r for r in results if r.name == "slugs_are_unique")
        self.assertFalse(case.ok)
        self.assertIn("unique constraint violated", case.failures[0])


LEDGER_EXAMPLE = os.path.join(ROOT, "examples", "ledger.miura")


def read_ledger():
    with open(LEDGER_EXAMPLE, "r", encoding="utf-8") as fh:
        return fh.read()


class TestTransactionsAndAggregates(unittest.TestCase):
    def assert_error(self, text, fragment):
        with self.assertRaises(BundleError) as ctx:
            load(text)
        self.assertIn(fragment, str(ctx.exception))

    def test_ledger_loads_and_passes(self):
        from miurac.runner import run_tests
        app = load(read_ledger())
        transfer = app.action("transfer")
        self.assertEqual(len(transfer.effects), 2)
        results = run_tests(app)
        self.assertTrue(all(r.ok for r in results), [(r.name, r.failures) for r in results])

    def test_multi_effect_atomic_rollback(self):
        # An ensures failure on a two-effect action must roll back the first write.
        from miurac.runner import run_tests
        bad = read_ledger().replace(
            "(ensures (= (. to_after balance) (+ (. to_before balance) amount)))",
            "(ensures (= (. to_after balance) 999999))",  # impossible -> always rolls back
        )
        results = run_tests(load(bad))
        # the atomic-transfer case does a transfer, which now always fails ensures;
        # the (do transfer ...) step should report an ensures violation, not corrupt state
        case = next(r for r in results if r.name == "transfer_is_atomic_and_conservative")
        self.assertFalse(case.ok)
        self.assertIn("ensures", case.failures[0].lower())

    def test_effect_binding_scopes_to_later_effects(self):
        bad = read_ledger().replace("(. from_before balance)", "(. nonexistent balance)")
        self.assert_error(bad, "ensures references unbound names: nonexistent")

    def test_was_binding_rejected_on_insert(self):
        bad = read_ledger().replace(
            "(effect (insert Account (name name)))",
            "(effect (insert Account (name name)) (was ghost))",
        )
        self.assert_error(bad, "(was name) applies to update/delete")

    def test_count_aggregate_scopes_entity(self):
        bad = read_ledger().replace("(requires (< (count Account) 1000))", "(requires (< (count Nope) 1000))")
        self.assert_error(bad, "aggregate over unknown entity 'Nope'")

    def test_sum_requires_int_field(self):
        bad = read_ledger().replace("(sum Account balance)", "(sum Account name)")
        self.assert_error(bad, "must exist and be (int)")

    def test_aggregate_rejected_in_effect_expr(self):
        bad = read_ledger().replace(
            "(effect (update Account id (balance (+ (. current balance) amount))))",
            "(effect (update Account id (balance (count Account))))",
        )
        self.assert_error(bad, "aggregates")

    def test_owner_rule_rejected_on_multi_effect(self):
        # craft a two-effect action with an owner allow -> should be rejected
        bad = read_auth_example().replace(
            "(action toggle_task\n      (allow (owner owner))",
            "(action toggle_task\n      (allow (owner owner))\n      (effect (update Task id (done true)))",
        )
        self.assert_error(bad, "single-effect")


class TestV07(unittest.TestCase):
    BASE = """(miura 0.1
  (intent "notes")
  (schema (entity Note
    (field id (id) (auto))
    (field title (text) (require (>= (len title) 1)))
    (field body (text) (default ""))
    (field created_at (timestamp) (auto))))
  (workflow
    (action add_note (input (title text)) (effect (insert Note (title title))))
    (action edit_note (input (id id) (title text)) (effect (update Note id (title title))))
    (query recent (from Note) (order-by created_at desc) (page-size 2)))
  (ui (page home "/"
    (heading "Notes")
    (form (action add_note) (field title (label "Title")))
    (list (query recent) (item
      (text title)
      (form (action edit_note) (bind id id) (field title (from title))))))))
"""

    def test_page_size_loads(self):
        app = load(self.BASE)
        self.assertEqual(app.query("recent").page_size, 2)

    def test_page_size_must_be_positive(self):
        with self.assertRaises(BundleError) as ctx:
            load(self.BASE.replace("(page-size 2)", "(page-size 0)"))
        self.assertIn("positive integer", str(ctx.exception))

    def test_prefill_loads(self):
        app = load(self.BASE)
        form = app.pages[0].components[2].item[1]
        self.assertEqual(form.fields[0].from_field, "title")

    def test_prefill_only_in_list_item(self):
        bad = self.BASE.replace(
            "(form (action add_note) (field title (label \"Title\")))",
            "(form (action add_note) (field title (from title)))")
        with self.assertRaises(BundleError) as ctx:
            load(bad)
        self.assertIn("only allowed on forms inside a list", str(ctx.exception))

    def test_prefill_unknown_row_field(self):
        bad = self.BASE.replace("(field title (from title))", "(field title (from ghost))")
        with self.assertRaises(BundleError) as ctx:
            load(bad)
        self.assertIn("row has no such field", str(ctx.exception))

    def test_pagination_slices_at_runtime(self):
        from miurac.emit_python import emit_python
        import types as _t
        src = emit_python(load(self.BASE), "test")
        mod = _t.ModuleType("pag")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["MIURA_DB"] = os.path.join(tmp, "p.db")
            mod.__dict__["__file__"] = os.path.join(tmp, "app.py")
            exec(compile(src, "pag", "exec"), mod.__dict__)
            mod.init_db()
            for i in range(5):
                mod.action_add_note({"title": f"n{i}"}, {"user": None})
            page0 = mod.query_recent({}, {"user": None}, 0)
            page1 = mod.query_recent({}, {"user": None}, 2)
            self.assertEqual(len(page0), 2)
            self.assertEqual(len(page1), 2)
            self.assertEqual(len(mod.query_recent({}, {"user": None}, 4)), 1)
            self.assertNotEqual([r["id"] for r in page0], [r["id"] for r in page1])


class TestUnpack(unittest.TestCase):
    def unpack(self, out_dir):
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "compiler"))
        subprocess.run(
            [sys.executable, "-m", "miurac", "unpack", EXAMPLE, "-o", out_dir],
            check=True, capture_output=True, env=env, cwd=ROOT,
        )

    def test_unpack_writes_targets_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
            self.unpack(a)
            self.unpack(b)
            rel_paths = ["server/app.py", "web/index.html", "db/schema.sql"]
            for rel in rel_paths:
                pa, pb = os.path.join(a, rel), os.path.join(b, rel)
                self.assertTrue(os.path.exists(pa), rel)
                with open(pa, "rb") as fa, open(pb, "rb") as fb:
                    self.assertEqual(fa.read(), fb.read(), f"nondeterministic output: {rel}")

    def test_verify_detects_drift(self):
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "compiler"))

        def verify(out_dir):
            return subprocess.run(
                [sys.executable, "-m", "miurac", "verify", EXAMPLE, "-o", out_dir],
                capture_output=True, env=env, cwd=ROOT, text=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            self.unpack(tmp)
            self.assertEqual(verify(tmp).returncode, 0)
            app_py = os.path.join(tmp, "server", "app.py")
            with open(app_py, "a", encoding="utf-8") as fh:
                fh.write("\n# hotfix nobody told the bundle about\n")
            result = verify(tmp)
            self.assertEqual(result.returncode, 1)
            self.assertIn("DRIFTED", result.stdout)
            os.remove(app_py)
            result = verify(tmp)
            self.assertEqual(result.returncode, 1)
            self.assertIn("MISSING", result.stdout)

    def test_generated_python_compiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.unpack(tmp)
            path = os.path.join(tmp, "server", "app.py")
            with open(path, "r", encoding="utf-8") as fh:
                source = fh.read()
            self.assertIn("DO NOT EDIT", source)
            compile(source, path, "exec")


if __name__ == "__main__":
    unittest.main()
