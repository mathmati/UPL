"""End-to-end tests: unpack the example bundle, run the generated
server, and exercise the API — including contract enforcement."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "examples", "tasks.upl")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestGeneratedApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "compiler"))
        subprocess.run(
            [sys.executable, "-m", "uplc", "unpack", EXAMPLE, "-o", cls.tmp.name],
            check=True, capture_output=True, env=env, cwd=ROOT,
        )
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.proc = subprocess.Popen(
            [sys.executable, os.path.join(cls.tmp.name, "server", "app.py")],
            env=dict(os.environ, UPL_PORT=str(cls.port), UPL_DB=os.path.join(cls.tmp.name, "test.db")),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                out = cls.proc.stdout.read().decode()
                raise RuntimeError(f"server exited early:\n{out}")
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("server did not start in time")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.tmp.cleanup()

    def request(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_full_lifecycle(self):
        status, task = self.request("POST", "/api/create_task", {"title": "write the compiler"})
        self.assertEqual(status, 200, task)
        self.assertEqual(task["title"], "write the compiler")
        self.assertFalse(task["done"])
        self.assertTrue(task["id"])

        status, rows = self.request("GET", "/api/list_tasks")
        self.assertEqual(status, 200)
        self.assertIn(task["id"], [r["id"] for r in rows])

        status, toggled = self.request("POST", "/api/toggle_task", {"id": task["id"]})
        self.assertEqual(status, 200, toggled)
        self.assertTrue(toggled["done"])

        status, toggled = self.request("POST", "/api/toggle_task", {"id": task["id"]})
        self.assertEqual(status, 200)
        self.assertFalse(toggled["done"])

        status, result = self.request("POST", "/api/delete_task", {"id": task["id"]})
        self.assertEqual(status, 200)
        self.assertEqual(result, {"ok": True})

        status, rows = self.request("GET", "/api/list_tasks")
        self.assertNotIn(task["id"], [r["id"] for r in rows])

    def test_requires_contract_rejects_empty_title(self):
        status, body = self.request("POST", "/api/create_task", {"title": ""})
        self.assertEqual(status, 400)
        self.assertIn("requires failed", body["error"])

    def test_field_require_rejects_oversize_title(self):
        status, body = self.request("POST", "/api/create_task", {"title": "x" * 201})
        self.assertEqual(status, 400)
        self.assertIn("require failed", body["error"])

    def test_input_type_checked(self):
        status, body = self.request("POST", "/api/create_task", {"title": 42})
        self.assertEqual(status, 400)
        self.assertIn("must be a string", body["error"])

    def test_missing_input_rejected(self):
        status, body = self.request("POST", "/api/create_task", {})
        self.assertEqual(status, 400)
        self.assertIn("missing input", body["error"])

    def test_unknown_id_rejected(self):
        status, body = self.request("POST", "/api/toggle_task", {"id": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("no Task with id", body["error"])

    def test_ordering_newest_first(self):
        _, first = self.request("POST", "/api/create_task", {"title": "older"})
        time.sleep(0.01)
        _, second = self.request("POST", "/api/create_task", {"title": "newer"})
        _, rows = self.request("GET", "/api/list_tasks")
        ids = [r["id"] for r in rows]
        self.assertLess(ids.index(second["id"]), ids.index(first["id"]))

    def test_page_serves_html(self):
        req = urllib.request.Request(self.base + "/")
        with urllib.request.urlopen(req) as res:
            body = res.read().decode()
        self.assertEqual(res.status, 200)
        self.assertIn("UI_MODEL", body)
        self.assertIn("Tasks", body)


if __name__ == "__main__":
    unittest.main()
