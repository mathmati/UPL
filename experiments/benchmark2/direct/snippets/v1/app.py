#!/usr/bin/env python3
"""Snippet locker - multi-user shared code-snippet locker (v1).

Python 3 standard library only. Run with `python3 app.py`.
Reads PORT (or MIURA_PORT) and DB_PATH (or MIURA_DB) from env.
"""

import binascii
import hashlib
import http.cookies
import json
import os
import re
import secrets
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ELEVATED_ROLE = "admin"
BASIC_ROLE = "member"

PORT = int(os.environ.get("PORT") or os.environ.get("MIURA_PORT") or 8000)
DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "snippets_v1.db"

SESSION_COOKIE = "session"

_db_lock = threading.Lock()


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with _db_lock:
        conn = get_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snippets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT UNIQUE NOT NULL,
                    body TEXT NOT NULL,
                    owner_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    FOREIGN KEY(owner_id) REFERENCES users(id)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


# ---------- password hashing ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return binascii.hexlify(salt).decode() + "$" + binascii.hexlify(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = binascii.unhexlify(salt_hex)
        expected = binascii.unhexlify(hash_hex)
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return secrets.compare_digest(dk, expected)


def is_valid_email(email) -> bool:
    return isinstance(email, str) and "@" in email


def is_valid_password(password) -> bool:
    return isinstance(password, str) and len(password) >= 8


# ---------- serialization ----------

def user_public(row) -> dict:
    return {"id": row["id"], "email": row["email"], "role": row["role"]}


def snippet_public(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "owner_id": row["owner_id"],
        "created_at": row["created_at"],
    }


HTML_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Snippet Locker</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 780px; margin: 2em auto; padding: 0 1em; }
fieldset { margin-bottom: 1.5em; }
label { display:block; margin-top: 0.5em; }
input, textarea { width: 100%; box-sizing: border-box; padding: 0.4em; margin-top: 0.2em; }
textarea { min-height: 80px; font-family: monospace; }
.snippet { border: 1px solid #ccc; border-radius: 6px; padding: 0.75em; margin-bottom: 0.75em; }
.snippet h4 { margin: 0 0 0.25em 0; }
.snippet pre { white-space: pre-wrap; word-break: break-word; background:#f7f7f7; padding:0.5em; }
.meta { color: #666; font-size: 0.85em; }
button { margin-right: 0.5em; margin-top: 0.4em; }
.error { color: #b00020; }
#who { font-weight: bold; }
.tabs button.active { font-weight: bold; text-decoration: underline; }
</style>
</head>
<body>
<h1>Snippet Locker</h1>

<div id="authArea">
  <fieldset id="loginBox">
    <legend>Login</legend>
    <label>Email <input id="loginEmail" type="email"></label>
    <label>Password <input id="loginPassword" type="password"></label>
    <button onclick="login()">Login</button>
    <button onclick="signup()">Sign up</button>
    <div class="error" id="authError"></div>
  </fieldset>
  <div id="loggedInBox" style="display:none">
    Signed in as <span id="who"></span> (<span id="role"></span>)
    <button onclick="logout()">Logout</button>
  </div>
</div>

<fieldset id="saveBox" style="display:none">
  <legend>Save a snippet</legend>
  <label>Title <input id="snipTitle" maxlength="80"></label>
  <label>Body <textarea id="snipBody" maxlength="4000"></textarea></label>
  <button onclick="saveSnippet()">Save</button>
  <div class="error" id="saveError"></div>
</fieldset>

<div class="tabs" id="tabsBox" style="display:none">
  <button id="tabAll" class="active" onclick="switchTab('all')">All snippets</button>
  <button id="tabMine" onclick="switchTab('mine')">My snippets</button>
</div>
<div id="list"></div>

<script>
let ME = null;
let TAB = 'all';

function qs(id) { return document.getElementById(id); }

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  return { status: res.status, data };
}

async function refreshMe() {
  // no whoami endpoint defined by contract; rely on login/signup response state kept client-side
}

async function login() {
  qs('authError').textContent = '';
  const email = qs('loginEmail').value;
  const password = qs('loginPassword').value;
  const r = await api('POST', '/api/auth/login', { email, password });
  if (r.status === 200) { onSignedIn(r.data); } else { qs('authError').textContent = (r.data && r.data.error) || 'Login failed'; }
}

async function signup() {
  qs('authError').textContent = '';
  const email = qs('loginEmail').value;
  const password = qs('loginPassword').value;
  const r = await api('POST', '/api/auth/signup', { email, password });
  if (r.status === 200) { onSignedIn(r.data); } else { qs('authError').textContent = (r.data && r.data.error) || 'Signup failed'; }
}

async function logout() {
  await api('POST', '/api/auth/logout');
  ME = null;
  qs('loggedInBox').style.display = 'none';
  qs('loginBox').style.display = '';
  qs('saveBox').style.display = 'none';
  qs('tabsBox').style.display = 'none';
  qs('list').innerHTML = '';
}

function onSignedIn(user) {
  ME = user;
  qs('loginBox').style.display = 'none';
  qs('loggedInBox').style.display = '';
  qs('who').textContent = user.email;
  qs('role').textContent = user.role;
  qs('saveBox').style.display = '';
  qs('tabsBox').style.display = '';
  loadList();
}

async function saveSnippet() {
  qs('saveError').textContent = '';
  const title = qs('snipTitle').value;
  const body = qs('snipBody').value;
  const r = await api('POST', '/api/save_snippet', { title, body });
  if (r.status === 200) {
    qs('snipTitle').value = '';
    qs('snipBody').value = '';
    loadList();
  } else {
    qs('saveError').textContent = (r.data && r.data.error) || 'Save failed';
  }
}

function switchTab(tab) {
  TAB = tab;
  qs('tabAll').className = tab === 'all' ? 'active' : '';
  qs('tabMine').className = tab === 'mine' ? 'active' : '';
  loadList();
}

async function loadList() {
  const path = TAB === 'all' ? '/api/all_snippets' : '/api/my_snippets';
  const r = await api('GET', path);
  const list = qs('list');
  list.innerHTML = '';
  if (r.status !== 200 || !Array.isArray(r.data)) return;
  for (const s of r.data) {
    const div = document.createElement('div');
    div.className = 'snippet';
    const canEdit = ME && (ME.id === s.owner_id || ME.role === 'admin');
    div.innerHTML = `
      <h4>${escapeHtml(s.title)}</h4>
      <pre>${escapeHtml(s.body)}</pre>
      <div class="meta">owner #${s.owner_id} &middot; ${escapeHtml(s.created_at || '')}</div>
    `;
    if (canEdit) {
      const editBtn = document.createElement('button');
      editBtn.textContent = 'Edit';
      editBtn.onclick = () => editSnippet(s);
      div.appendChild(editBtn);
      const delBtn = document.createElement('button');
      delBtn.textContent = 'Delete';
      delBtn.onclick = () => deleteSnippet(s.id);
      div.appendChild(delBtn);
    }
    list.appendChild(div);
  }
}

async function editSnippet(s) {
  const body = prompt('New body for "' + s.title + '"', s.body);
  if (body === null) return;
  const r = await api('POST', '/api/edit_snippet', { id: s.id, body });
  if (r.status === 200) loadList();
  else alert((r.data && r.data.error) || 'Edit failed');
}

async function deleteSnippet(id) {
  if (!confirm('Delete this snippet?')) return;
  const r = await api('POST', '/api/delete_snippet', { id });
  if (r.status === 200) loadList();
  else alert((r.data && r.data.error) || 'Delete failed');
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "SnippetLocker/1.0"

    def log_message(self, fmt, *args):
        pass  # keep test output quiet

    # ---------- helpers ----------

    def _send_json(self, status: int, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._maybe_set_cookie()
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html: str):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    _new_cookie = None
    _clear_cookie = False

    def _maybe_set_cookie(self):
        if self._clear_cookie:
            c = http.cookies.SimpleCookie()
            c[SESSION_COOKIE] = ""
            c[SESSION_COOKIE]["path"] = "/"
            c[SESSION_COOKIE]["max-age"] = 0
            self.send_header("Set-Cookie", c[SESSION_COOKIE].OutputString())
        elif self._new_cookie:
            c = http.cookies.SimpleCookie()
            c[SESSION_COOKIE] = self._new_cookie
            c[SESSION_COOKIE]["path"] = "/"
            c[SESSION_COOKIE]["httponly"] = True
            self.send_header("Set-Cookie", c[SESSION_COOKIE].OutputString())

    def _get_cookie_token(self):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        c = http.cookies.SimpleCookie()
        try:
            c.load(cookie_header)
        except Exception:
            return None
        if SESSION_COOKIE in c:
            return c[SESSION_COOKIE].value
        return None

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _current_user(self, conn):
        token = self._get_cookie_token()
        if not token:
            return None
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        return row

    # ---------- routing ----------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send_html(200, HTML_PAGE)
            return
        if path == "/api/all_snippets":
            self._handle_all_snippets()
            return
        if path == "/api/my_snippets":
            self._handle_my_snippets()
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        routes = {
            "/api/auth/signup": self._handle_signup,
            "/api/auth/login": self._handle_login,
            "/api/auth/logout": self._handle_logout,
            "/api/save_snippet": self._handle_save_snippet,
            "/api/edit_snippet": self._handle_edit_snippet,
            "/api/delete_snippet": self._handle_delete_snippet,
        }
        handler = routes.get(path)
        if handler is None:
            self._send_json(404, {"error": "not found"})
            return
        handler()

    # ---------- auth handlers ----------

    def _handle_signup(self):
        self._new_cookie = None
        self._clear_cookie = False
        data = self._read_json_body()
        if data is None:
            self._send_json(400, {"error": "invalid json body"})
            return
        email = data.get("email")
        password = data.get("password")
        if not is_valid_email(email) or not is_valid_password(password):
            self._send_json(400, {"error": "invalid email or password"})
            return
        with _db_lock:
            conn = get_conn()
            try:
                existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
                if existing:
                    self._send_json(400, {"error": "email already registered"})
                    return
                count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
                role = ELEVATED_ROLE if count == 0 else BASIC_ROLE
                pw_hash = hash_password(password)
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
                    (email, pw_hash, role),
                )
                user_id = cur.lastrowid
                token = secrets.token_hex(32)
                conn.execute(
                    "INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id)
                )
                conn.commit()
                row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                self._new_cookie = token
                self._send_json(200, user_public(row))
            finally:
                conn.close()

    def _handle_login(self):
        self._new_cookie = None
        self._clear_cookie = False
        data = self._read_json_body()
        if data is None:
            self._send_json(400, {"error": "invalid json body"})
            return
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            self._send_json(400, {"error": "invalid email or password"})
            return
        conn = get_conn()
        try:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if not row or not verify_password(password, row["password_hash"]):
                self._send_json(400, {"error": "invalid email or password"})
                return
            token = secrets.token_hex(32)
            with _db_lock:
                conn.execute(
                    "INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, row["id"])
                )
                conn.commit()
            self._new_cookie = token
            self._send_json(200, user_public(row))
        finally:
            conn.close()

    def _handle_logout(self):
        self._new_cookie = None
        self._clear_cookie = True
        token = self._get_cookie_token()
        if token:
            with _db_lock:
                conn = get_conn()
                try:
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                    conn.commit()
                finally:
                    conn.close()
        self._send_json(200, {"ok": True})

    # ---------- snippet handlers ----------

    def _handle_save_snippet(self):
        self._new_cookie = None
        self._clear_cookie = False
        conn = get_conn()
        try:
            user = self._current_user(conn)
            if not user:
                self._send_json(401, {"error": "not signed in"})
                return
            data = self._read_json_body()
            if data is None:
                self._send_json(400, {"error": "invalid json body"})
                return
            title = data.get("title")
            body = data.get("body")
            if not isinstance(title, str) or not (1 <= len(title) <= 80):
                self._send_json(400, {"error": "title must be 1-80 chars"})
                return
            if not isinstance(body, str) or not (1 <= len(body) <= 4000):
                self._send_json(400, {"error": "body must be 1-4000 chars"})
                return
            with _db_lock:
                dup = conn.execute("SELECT id FROM snippets WHERE title = ?", (title,)).fetchone()
                if dup:
                    self._send_json(400, {"error": "title already exists"})
                    return
                cur = conn.execute(
                    "INSERT INTO snippets (title, body, owner_id) VALUES (?, ?, ?)",
                    (title, body, user["id"]),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM snippets WHERE id = ?", (cur.lastrowid,)).fetchone()
            self._send_json(200, snippet_public(row))
        finally:
            conn.close()

    def _handle_edit_snippet(self):
        self._new_cookie = None
        self._clear_cookie = False
        conn = get_conn()
        try:
            user = self._current_user(conn)
            if not user:
                self._send_json(401, {"error": "not signed in"})
                return
            data = self._read_json_body()
            if data is None:
                self._send_json(400, {"error": "invalid json body"})
                return
            sid = data.get("id")
            body = data.get("body")
            row = None
            if isinstance(sid, (int, float, str)):
                row = conn.execute("SELECT * FROM snippets WHERE id = ?", (sid,)).fetchone()
            if not row:
                self._send_json(400, {"error": "unknown snippet id"})
                return
            if not isinstance(body, str) or not (1 <= len(body) <= 4000):
                self._send_json(400, {"error": "body must be 1-4000 chars"})
                return
            if row["owner_id"] != user["id"] and user["role"] != ELEVATED_ROLE:
                self._send_json(403, {"error": "forbidden"})
                return
            with _db_lock:
                conn.execute("UPDATE snippets SET body = ? WHERE id = ?", (body, row["id"]))
                conn.commit()
                row = conn.execute("SELECT * FROM snippets WHERE id = ?", (row["id"],)).fetchone()
            self._send_json(200, snippet_public(row))
        finally:
            conn.close()

    def _handle_delete_snippet(self):
        self._new_cookie = None
        self._clear_cookie = False
        conn = get_conn()
        try:
            user = self._current_user(conn)
            if not user:
                self._send_json(401, {"error": "not signed in"})
                return
            data = self._read_json_body()
            if data is None:
                self._send_json(400, {"error": "invalid json body"})
                return
            sid = data.get("id")
            row = None
            if isinstance(sid, (int, float, str)):
                row = conn.execute("SELECT * FROM snippets WHERE id = ?", (sid,)).fetchone()
            if not row:
                self._send_json(400, {"error": "unknown snippet id"})
                return
            if row["owner_id"] != user["id"] and user["role"] != ELEVATED_ROLE:
                self._send_json(403, {"error": "forbidden"})
                return
            with _db_lock:
                conn.execute("DELETE FROM snippets WHERE id = ?", (row["id"],))
                conn.commit()
            self._send_json(200, {"ok": True})
        finally:
            conn.close()

    # ---------- query handlers ----------

    def _handle_all_snippets(self):
        conn = get_conn()
        try:
            user = self._current_user(conn)
            if not user:
                self._send_json(401, {"error": "not signed in"})
                return
            rows = conn.execute(
                "SELECT * FROM snippets ORDER BY created_at DESC, id DESC"
            ).fetchall()
            self._send_json(200, [snippet_public(r) for r in rows])
        finally:
            conn.close()

    def _handle_my_snippets(self):
        conn = get_conn()
        try:
            user = self._current_user(conn)
            if not user:
                self._send_json(401, {"error": "not signed in"})
                return
            rows = conn.execute(
                "SELECT * FROM snippets WHERE owner_id = ? ORDER BY created_at DESC, id DESC",
                (user["id"],),
            ).fetchall()
            self._send_json(200, [snippet_public(r) for r in rows])
        finally:
            conn.close()


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Snippet Locker (v1) listening on 127.0.0.1:{PORT}, db={DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
