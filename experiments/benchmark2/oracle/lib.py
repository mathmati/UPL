"""Shared bench2 oracle harness: boots an app (either arm), supports
multiple independent cookie sessions, and a check collector.

Arm-agnostic: everything drives the pinned HTTP + auth contract, so the
same oracle grades a Miura-compiled server and a hand-written one."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """A running app server bound to a specific SQLite db path."""

    def __init__(self, entry_path, db_path):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        cwd = os.path.dirname(entry_path)
        env = dict(
            os.environ,
            PORT=str(self.port), MIURA_PORT=str(self.port),
            DB_PATH=db_path, MIURA_DB=db_path,
        )
        self.proc = subprocess.Popen(
            [sys.executable, os.path.basename(entry_path)],
            cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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

    def session(self):
        return Session(self.base)


class Session:
    """One caller with its own cookie jar (name-agnostic)."""

    def __init__(self, base):
        self.base = base
        self.cookies = {}

    def _update_cookies(self, headers):
        for key, value in headers.items():
            if key.lower() == "set-cookie":
                pair = value.split(";", 1)[0]
                name, _, val = pair.partition("=")
                if val in ("", '""'):
                    self.cookies.pop(name.strip(), None)
                else:
                    self.cookies[name.strip()] = val.strip()

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        return h

    def _request(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                self._update_cookies(res.headers)
                raw, status = res.read(), res.status
        except urllib.error.HTTPError as err:
            self._update_cookies(err.headers)
            raw, status = err.read(), err.code
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw.decode(errors="replace")
        return status, body

    def signup(self, email, password="password-123"):
        return self._request("POST", "/api/auth/signup", {"email": email, "password": password})

    def login(self, email, password="password-123"):
        return self._request("POST", "/api/auth/login", {"email": email, "password": password})

    def logout(self):
        return self._request("POST", "/api/auth/logout", {})

    def post(self, action, payload):
        return self._request("POST", f"/api/{action}", payload)

    def get(self, query, params=None):
        path = f"/api/{query}"
        if params:
            path += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return self._request("GET", path)


class Checks:
    def __init__(self):
        self.results = []

    def check(self, name, cond, detail=""):
        self.results.append({"name": name, "passed": bool(cond), "detail": "" if cond else str(detail)[:300]})

    def summary(self):
        passed = sum(1 for r in self.results if r["passed"])
        return {"passed": passed, "total": len(self.results),
                "failures": [r for r in self.results if not r["passed"]]}
