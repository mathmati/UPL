#!/usr/bin/env python3
"""Shared docs — multi-user document index app (v1). Python 3 stdlib only."""

import hashlib
import http.server
import json
import os
import secrets
import sqlite3
import threading
import time
from http.cookies import SimpleCookie
from urllib.parse import urlparse

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "docs_v1.db"
PORT = int(os.environ.get("PORT") or os.environ.get("MIURA_PORT") or 8000)

ELEVATED_ROLE = "editor"
BASIC_ROLE = "author"

COOKIE_NAME = "session"

db_lock = threading.Lock()
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row


def init_db():
    with db_lock:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        conn.commit()


# ---------------------------------------------------------------- passwords

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000)
    return f"{salt}${digest.hex()}"


def verify_password(password, stored):
    try:
        salt, _, hexhash = stored.partition("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000)
        return secrets.compare_digest(digest.hex(), hexhash)
    except Exception:
        return False


# ------------------------------------------------------------------ session

def create_session(user_id):
    token = secrets.token_hex(32)
    with db_lock:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
            (token, user_id, time.time()),
        )
        conn.commit()
    return token


def get_user_by_token(token):
    if not token:
        return None
    with db_lock:
        row = conn.execute(
            "SELECT users.* FROM sessions JOIN users ON sessions.user_id = users.id WHERE sessions.token=?",
            (token,),
        ).fetchone()
    return row


def delete_session(token):
    with db_lock:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()


# ---------------------------------------------------------------- doc utils

def doc_to_dict(row):
    return {
        "id": row["id"],
        "slug": row["slug"],
        "title": row["title"],
        "owner_id": row["owner_id"],
        "created_at": row["created_at"],
    }


def user_to_dict(row):
    return {"id": row["id"], "email": row["email"], "role": row["role"]}


# --------------------------------------------------------------------- HTTP

INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Shared Docs</title>
<style>
body { font-family: sans-serif; max-width: 720px; margin: 2em auto; }
fieldset { margin-bottom: 1.5em; }
li { margin-bottom: 0.4em; }
.err { color: red; }
</style>
</head>
<body>
<h1>Shared Docs</h1>

<div id="who"></div>

<fieldset id="auth-box">
  <legend>Sign up / Log in</legend>
  <input id="email" placeholder="email" type="email">
  <input id="password" placeholder="password" type="password">
  <button onclick="signup()">Sign up</button>
  <button onclick="login()">Log in</button>
  <button onclick="logout()">Log out</button>
  <div id="auth-err" class="err"></div>
</fieldset>

<fieldset>
  <legend>Create doc</legend>
  <input id="slug" placeholder="slug (3-50 chars)">
  <input id="title" placeholder="title (1-150 chars)">
  <button onclick="createDoc()">Create</button>
  <div id="create-err" class="err"></div>
</fieldset>

<h2>My docs</h2>
<ul id="my-docs"></ul>

<h2>All docs</h2>
<ul id="all-docs"></ul>

<script>
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) {}
  return { status: res.status, data };
}

async function signup() {
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const r = await api("POST", "/api/auth/signup", { email, password });
  document.getElementById("auth-err").textContent = r.status === 200 ? "" : JSON.stringify(r.data);
  refresh();
}
async function login() {
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const r = await api("POST", "/api/auth/login", { email, password });
  document.getElementById("auth-err").textContent = r.status === 200 ? "" : JSON.stringify(r.data);
  refresh();
}
async function logout() {
  await api("POST", "/api/auth/logout");
  refresh();
}
async function createDoc() {
  const slug = document.getElementById("slug").value;
  const title = document.getElementById("title").value;
  const r = await api("POST", "/api/create_doc", { slug, title });
  document.getElementById("create-err").textContent = r.status === 200 ? "" : JSON.stringify(r.data);
  refresh();
}
async function renameDoc(id) {
  const title = prompt("New title?");
  if (title === null) return;
  await api("POST", "/api/rename_doc", { id, title });
  refresh();
}
async function deleteDoc(id) {
  await api("POST", "/api/delete_doc", { id });
  refresh();
}
function renderList(el, docs) {
  el.innerHTML = "";
  for (const d of docs) {
    const li = document.createElement("li");
    li.textContent = `[${d.id}] ${d.slug} — ${d.title} (owner ${d.owner_id}) `;
    const rb = document.createElement("button");
    rb.textContent = "rename";
    rb.onclick = () => renameDoc(d.id);
    const db_ = document.createElement("button");
    db_.textContent = "delete";
    db_.onclick = () => deleteDoc(d.id);
    li.appendChild(rb);
    li.appendChild(db_);
    el.appendChild(li);
  }
}
async function refresh() {
  const my = await api("GET", "/api/my_docs");
  const all = await api("GET", "/api/all_docs");
  document.getElementById("who").textContent =
    my.status === 200 ? "Signed in." : "Not signed in.";
  renderList(document.getElementById("my-docs"), my.status === 200 ? my.data : []);
  renderList(document.getElementById("all-docs"), all.status === 200 ? all.data : []);
}
refresh();
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "SharedDocs/1.0"

    def log_message(self, fmt, *args):
        pass

    # -- helpers -----------------------------------------------------

    def _get_cookie_token(self):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        c = SimpleCookie()
        try:
            c.load(cookie_header)
        except Exception:
            return None
        if COOKIE_NAME in c:
            return c[COOKIE_NAME].value
        return None

    def _current_user(self):
        token = self._get_cookie_token()
        return get_user_by_token(token)

    def _send_json(self, status, obj, set_cookie=None, clear_cookie=False):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header(
                "Set-Cookie", f"{COOKIE_NAME}={set_cookie}; Path=/; HttpOnly"
            )
        if clear_cookie:
            self.send_header(
                "Set-Cookie", f"{COOKIE_NAME}=; Path=/; HttpOnly; Max-Age=0"
            )
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data

    @staticmethod
    def _as_int(value):
        try:
            if isinstance(value, bool):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    # -- routing -------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send_html(200, INDEX_HTML)
            return
        if path == "/api/all_docs":
            user = self._current_user()
            if not user:
                self._send_json(401, {"error": "unauthorized"})
                return
            with db_lock:
                rows = conn.execute(
                    "SELECT * FROM docs ORDER BY created_at DESC, id DESC"
                ).fetchall()
            self._send_json(200, [doc_to_dict(r) for r in rows])
            return
        if path == "/api/my_docs":
            user = self._current_user()
            if not user:
                self._send_json(401, {"error": "unauthorized"})
                return
            with db_lock:
                rows = conn.execute(
                    "SELECT * FROM docs WHERE owner_id=? ORDER BY created_at DESC, id DESC",
                    (user["id"],),
                ).fetchall()
            self._send_json(200, [doc_to_dict(r) for r in rows])
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        data = self._read_json_body()
        if data is None:
            self._send_json(400, {"error": "invalid json body"})
            return

        if path == "/api/auth/signup":
            self._signup(data)
        elif path == "/api/auth/login":
            self._login(data)
        elif path == "/api/auth/logout":
            self._logout()
        elif path == "/api/create_doc":
            self._create_doc(data)
        elif path == "/api/rename_doc":
            self._rename_doc(data)
        elif path == "/api/delete_doc":
            self._delete_doc(data)
        else:
            self._send_json(404, {"error": "not found"})

    # -- auth handlers ---------------------------------------------------

    def _signup(self, data):
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or "@" not in email:
            self._send_json(400, {"error": "invalid email"})
            return
        if not isinstance(password, str) or len(password) < 8:
            self._send_json(400, {"error": "password too short"})
            return
        with db_lock:
            existing = conn.execute(
                "SELECT id FROM users WHERE email=?", (email,)
            ).fetchone()
            if existing:
                self._send_json(400, {"error": "duplicate email"})
                return
            count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            role = ELEVATED_ROLE if count == 0 else BASIC_ROLE
            pw_hash = hash_password(password)
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, role, created_at) VALUES (?,?,?,?)",
                (email, pw_hash, role, time.time()),
            )
            conn.commit()
            user_id = cur.lastrowid
        token = create_session(user_id)
        self._send_json(
            200, {"id": user_id, "email": email, "role": role}, set_cookie=token
        )

    def _login(self, data):
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            self._send_json(400, {"error": "invalid credentials"})
            return
        with db_lock:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            self._send_json(400, {"error": "invalid credentials"})
            return
        token = create_session(row["id"])
        self._send_json(200, user_to_dict(row), set_cookie=token)

    def _logout(self):
        token = self._get_cookie_token()
        if token:
            delete_session(token)
        self._send_json(200, {"ok": True}, clear_cookie=True)

    # -- doc action handlers ---------------------------------------------

    def _create_doc(self, data):
        user = self._current_user()
        if not user:
            self._send_json(401, {"error": "unauthorized"})
            return
        slug = data.get("slug")
        title = data.get("title")
        if not isinstance(slug, str) or not isinstance(title, str):
            self._send_json(400, {"error": "invalid input"})
            return
        if not (3 <= len(slug) <= 50):
            self._send_json(400, {"error": "slug length"})
            return
        if not (1 <= len(title) <= 150):
            self._send_json(400, {"error": "title length"})
            return
        with db_lock:
            existing = conn.execute("SELECT id FROM docs WHERE slug=?", (slug,)).fetchone()
            if existing:
                self._send_json(400, {"error": "duplicate slug"})
                return
            cur = conn.execute(
                "INSERT INTO docs (slug, title, owner_id, created_at) VALUES (?,?,?,?)",
                (slug, title, user["id"], time.time()),
            )
            conn.commit()
            doc_id = cur.lastrowid
            row = conn.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
        self._send_json(200, doc_to_dict(row))

    def _rename_doc(self, data):
        user = self._current_user()
        if not user:
            self._send_json(401, {"error": "unauthorized"})
            return
        doc_id = self._as_int(data.get("id"))
        title = data.get("title")
        if doc_id is None:
            self._send_json(400, {"error": "invalid id"})
            return
        with db_lock:
            row = conn.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
            if not row:
                self._send_json(400, {"error": "unknown id"})
                return
            if row["owner_id"] != user["id"] and user["role"] != ELEVATED_ROLE:
                self._send_json(403, {"error": "forbidden"})
                return
            if not isinstance(title, str) or not (1 <= len(title) <= 150):
                self._send_json(400, {"error": "title length"})
                return
            conn.execute("UPDATE docs SET title=? WHERE id=?", (title, doc_id))
            conn.commit()
            row = conn.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
        self._send_json(200, doc_to_dict(row))

    def _delete_doc(self, data):
        user = self._current_user()
        if not user:
            self._send_json(401, {"error": "unauthorized"})
            return
        doc_id = self._as_int(data.get("id"))
        if doc_id is None:
            self._send_json(400, {"error": "invalid id"})
            return
        with db_lock:
            row = conn.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
            if not row:
                self._send_json(400, {"error": "unknown id"})
                return
            if row["owner_id"] != user["id"] and user["role"] != ELEVATED_ROLE:
                self._send_json(403, {"error": "forbidden"})
                return
            conn.execute("DELETE FROM docs WHERE id=?", (doc_id,))
            conn.commit()
        self._send_json(200, {"id": doc_id})


def main():
    init_db()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
