"""Compiler tests: parsing, canonical form, validation, determinism."""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "compiler"))

from uplc import BundleError, load  # noqa: E402
from uplc.sexpr import dumps, parse  # noqa: E402

EXAMPLE = os.path.join(ROOT, "examples", "tasks.upl")


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
        from uplc.runner import run_tests
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
        self.assertIn("expected a contract rejection", case.failures[0])

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


class TestUnpack(unittest.TestCase):
    def unpack(self, out_dir):
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "compiler"))
        subprocess.run(
            [sys.executable, "-m", "uplc", "unpack", EXAMPLE, "-o", out_dir],
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
