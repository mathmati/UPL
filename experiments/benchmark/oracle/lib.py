"""Shared oracle harness: boots an app (either arm) and provides
HTTP helpers + a check collector. Arm-agnostic by design."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


def as_bool(v):
    return bool(v)


class App:
    def __init__(self, app_dir):
        entry = None
        for candidate in ("app.py", os.path.join("server", "app.py")):
            if os.path.exists(os.path.join(app_dir, candidate)):
                entry = os.path.join(app_dir, candidate)
                break
        if entry is None:
            raise RuntimeError(f"no app entrypoint found in {app_dir}")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self._tmp = tempfile.mkdtemp(prefix="oracle-db-")
        db_path = os.path.join(self._tmp, "oracle.db")
        env = dict(
            os.environ,
            PORT=str(self.port), UPL_PORT=str(self.port),
            DB_PATH=db_path, UPL_DB=db_path,
        )
        self.proc = subprocess.Popen(
            [sys.executable, os.path.basename(entry)],
            cwd=os.path.join(app_dir, os.path.dirname(entry)) or app_dir,
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.proc.poll() is not None:
                out = self.proc.stdout.read().decode(errors="replace")
                raise RuntimeError(f"server exited at boot:\n{out[:2000]}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("server did not start in 15s")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def _request(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                raw = res.read()
                status = res.status
        except urllib.error.HTTPError as err:
            raw = err.read()
            status = err.code
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw.decode(errors="replace")
        return status, body

    def post(self, action, payload):
        return self._request("POST", f"/api/{action}", payload)

    def get(self, query, params=None):
        path = f"/api/{query}"
        if params:
            path += "?" + urllib.parse.urlencode(params)
        return self._request("GET", path)

    def page(self):
        req = urllib.request.Request(self.base + "/")
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, res.read().decode(errors="replace")
        except urllib.error.HTTPError as err:
            return err.code, ""


class Checks:
    def __init__(self):
        self.results = []

    def check(self, name, cond, detail=""):
        self.results.append({"name": name, "passed": bool(cond), "detail": "" if cond else str(detail)[:300]})

    def summary(self):
        passed = sum(1 for r in self.results if r["passed"])
        return {
            "passed": passed,
            "total": len(self.results),
            "failures": [r for r in self.results if not r["passed"]],
        }


def pause():
    time.sleep(0.02)
