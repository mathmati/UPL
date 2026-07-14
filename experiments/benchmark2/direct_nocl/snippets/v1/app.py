#!/usr/bin/env python3
"""Snippet locker - a shared code-snippet locker (v1).

Multi-user HTTP app, Python 3 stdlib only.
Run: python3 app.py
Env: PORT / MIURA_PORT (default 8000), DB_PATH / MIURA_DB (default snippets_v1.db)
"""
import os
import re
import json
import sqlite3
import hashlib
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ELEVATED_ROLE = "admin"
BASIC_ROLE = "member"

PORT = int(os.environ.get("PORT") or os.environ.get("MIURA_PORT") or 8000)
DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "snippets_v1.db"

DB_LOCK = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with DB_LOCK:
        conn = get_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL
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
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000).hex()


def user_public(row):
    return {"id": row["id"], "email": row["email"], "role": row["role"]}


def snippet_public(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "owner_id": row["owner_id"],
        "owner": row["owner_email"] if "owner_email" in row.keys() else None,
        "created_at": row["created_at"],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "SnippetLocker/1.0"

    def log_message(self, fmt, *args):
        pass  # keep test output quiet

    # ---------- helpers ----------
    def _send(self, status, body_bytes, content_type="application/json", extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body_bytes)
        except BrokenPipeError:
            pass

    def send_json(self, status, obj, set_cookie=None, clear_cookie=False):
        body = json.dumps(obj).encode("utf-8")
        headers = []
        if set_cookie:
            headers.append(("Set-Cookie", f"session={set_cookie}; Path=/; HttpOnly"))
        if clear_cookie:
            headers.append(("Set-Cookie", "session=; Path=/; HttpOnly; Max-Age=0"))
        self._send(status, body, "application/json", headers)

    def send_html(self, status, html):
        self._send(status, html.encode("utf-8"), "text/html; charset=utf-8")

    def read_json_body(self):
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

    def get_cookie(self, name):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        for part in cookie_header.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                if k == name:
                    return v
        return None

    def get_current_user(self, conn):
        token = self.get_cookie("session")
        if not token:
            return None
        row = conn.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)).fetchone()
        if not row:
            return None
        user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        return user

    # ---------- routing ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self.send_html(200, INDEX_HTML)
            return
        if path == "/api/all_snippets":
            self.handle_all_snippets()
            return
        if path == "/api/my_snippets":
            self.handle_my_snippets()
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        routes = {
            "/api/auth/signup": self.handle_signup,
            "/api/auth/login": self.handle_login,
            "/api/auth/logout": self.handle_logout,
            "/api/save_snippet": self.handle_save_snippet,
            "/api/edit_snippet": self.handle_edit_snippet,
            "/api/delete_snippet": self.handle_delete_snippet,
        }
        fn = routes.get(path)
        if not fn:
            self.send_json(404, {"error": "not found"})
            return
        fn()

    # ---------- auth ----------
    def handle_signup(self):
        data = self.read_json_body()
        if data is None:
            self.send_json(400, {"error": "invalid json"})
            return
        email = (data.get("email") or "").strip()
        password = data.get("password") or ""
        if "@" not in email or len(password) < 8:
            self.send_json(400, {"error": "invalid email or password"})
            return
        with DB_LOCK:
            conn = get_conn()
            try:
                existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
                if existing:
                    self.send_json(400, {"error": "email already registered"})
                    return
                count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
                role = ELEVATED_ROLE if count == 0 else BASIC_ROLE
                salt = secrets.token_hex(16)
                pwhash = hash_password(password, salt)
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, salt, role, created_at) VALUES (?,?,?,?,?)",
                    (email, pwhash, salt, role, now_iso()),
                )
                user_id = cur.lastrowid
                token = secrets.token_hex(32)
                conn.execute(
                    "INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
                    (token, user_id, now_iso()),
                )
                conn.commit()
                user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                self.send_json(200, user_public(user_row), set_cookie=token)
            finally:
                conn.close()

    def handle_login(self):
        data = self.read_json_body()
        if data is None:
            self.send_json(400, {"error": "invalid json"})
            return
        email = (data.get("email") or "").strip()
        password = data.get("password") or ""
        with DB_LOCK:
            conn = get_conn()
            try:
                user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if not user:
                    self.send_json(400, {"error": "invalid email or password"})
                    return
                pwhash = hash_password(password, user["salt"])
                if not secrets.compare_digest(pwhash, user["password_hash"]):
                    self.send_json(400, {"error": "invalid email or password"})
                    return
                token = secrets.token_hex(32)
                conn.execute(
                    "INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
                    (token, user["id"], now_iso()),
                )
                conn.commit()
                self.send_json(200, user_public(user), set_cookie=token)
            finally:
                conn.close()

    def handle_logout(self):
        token = self.get_cookie("session")
        with DB_LOCK:
            conn = get_conn()
            try:
                if token:
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                    conn.commit()
            finally:
                conn.close()
        self.send_json(200, {"ok": True}, clear_cookie=True)

    # ---------- snippet validation ----------
    @staticmethod
    def valid_title(title):
        return isinstance(title, str) and 1 <= len(title) <= 80

    @staticmethod
    def valid_body(body):
        return isinstance(body, str) and 1 <= len(body) <= 4000

    def query_snippet_row(self, conn, sid):
        return conn.execute(
            """
            SELECT s.*, u.email AS owner_email
            FROM snippets s JOIN users u ON s.owner_id = u.id
            WHERE s.id = ?
            """,
            (sid,),
        ).fetchone()

    # ---------- actions ----------
    def handle_save_snippet(self):
        with DB_LOCK:
            conn = get_conn()
            try:
                user = self.get_current_user(conn)
                if not user:
                    self.send_json(401, {"error": "not signed in"})
                    return
                data = self.read_json_body()
                if data is None:
                    self.send_json(400, {"error": "invalid json"})
                    return
                title = data.get("title")
                body = data.get("body")
                if not self.valid_title(title) or not self.valid_body(body):
                    self.send_json(400, {"error": "invalid title or body length"})
                    return
                dup = conn.execute("SELECT id FROM snippets WHERE title = ?", (title,)).fetchone()
                if dup:
                    self.send_json(400, {"error": "duplicate title"})
                    return
                cur = conn.execute(
                    "INSERT INTO snippets (title, body, owner_id, created_at) VALUES (?,?,?,?)",
                    (title, body, user["id"], now_iso()),
                )
                conn.commit()
                row = self.query_snippet_row(conn, cur.lastrowid)
                self.send_json(200, snippet_public(row))
            finally:
                conn.close()

    def handle_edit_snippet(self):
        with DB_LOCK:
            conn = get_conn()
            try:
                user = self.get_current_user(conn)
                if not user:
                    self.send_json(401, {"error": "not signed in"})
                    return
                data = self.read_json_body()
                if data is None:
                    self.send_json(400, {"error": "invalid json"})
                    return
                sid = data.get("id")
                body = data.get("body")
                row = None
                if sid is not None:
                    try:
                        sid_int = int(sid)
                        row = self.query_snippet_row(conn, sid_int)
                    except (ValueError, TypeError):
                        row = None
                if not row:
                    self.send_json(400, {"error": "unknown id"})
                    return
                if row["owner_id"] != user["id"] and user["role"] != ELEVATED_ROLE:
                    self.send_json(403, {"error": "forbidden"})
                    return
                if not self.valid_body(body):
                    self.send_json(400, {"error": "invalid body length"})
                    return
                conn.execute("UPDATE snippets SET body = ? WHERE id = ?", (body, row["id"]))
                conn.commit()
                updated = self.query_snippet_row(conn, row["id"])
                self.send_json(200, snippet_public(updated))
            finally:
                conn.close()

    def handle_delete_snippet(self):
        with DB_LOCK:
            conn = get_conn()
            try:
                user = self.get_current_user(conn)
                if not user:
                    self.send_json(401, {"error": "not signed in"})
                    return
                data = self.read_json_body()
                if data is None:
                    self.send_json(400, {"error": "invalid json"})
                    return
                sid = data.get("id")
                row = None
                if sid is not None:
                    try:
                        sid_int = int(sid)
                        row = self.query_snippet_row(conn, sid_int)
                    except (ValueError, TypeError):
                        row = None
                if not row:
                    self.send_json(400, {"error": "unknown id"})
                    return
                if row["owner_id"] != user["id"] and user["role"] != ELEVATED_ROLE:
                    self.send_json(403, {"error": "forbidden"})
                    return
                conn.execute("DELETE FROM snippets WHERE id = ?", (row["id"],))
                conn.commit()
                self.send_json(200, {"ok": True, "id": row["id"]})
            finally:
                conn.close()

    # ---------- queries ----------
    def handle_all_snippets(self):
        with DB_LOCK:
            conn = get_conn()
            try:
                user = self.get_current_user(conn)
                if not user:
                    self.send_json(401, {"error": "not signed in"})
                    return
                rows = conn.execute(
                    """
                    SELECT s.*, u.email AS owner_email
                    FROM snippets s JOIN users u ON s.owner_id = u.id
                    ORDER BY s.created_at DESC, s.id DESC
                    """
                ).fetchall()
                self.send_json(200, [snippet_public(r) for r in rows])
            finally:
                conn.close()

    def handle_my_snippets(self):
        with DB_LOCK:
            conn = get_conn()
            try:
                user = self.get_current_user(conn)
                if not user:
                    self.send_json(401, {"error": "not signed in"})
                    return
                rows = conn.execute(
                    """
                    SELECT s.*, u.email AS owner_email
                    FROM snippets s JOIN users u ON s.owner_id = u.id
                    WHERE s.owner_id = ?
                    ORDER BY s.created_at DESC, s.id DESC
                    """,
                    (user["id"],),
                ).fetchall()
                self.send_json(200, [snippet_public(r) for r in rows])
            finally:
                conn.close()


INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Snippet Locker</title>
<style>
body { font-family: sans-serif; max-width: 800px; margin: 2em auto; padding: 0 1em; }
input, textarea { width: 100%; box-sizing: border-box; margin: 0.25em 0; }
textarea { min-height: 80px; }
.snippet { border: 1px solid #ccc; border-radius: 6px; padding: 0.75em; margin: 0.5em 0; }
.snippet h3 { margin: 0 0 0.25em 0; }
.meta { color: #666; font-size: 0.85em; }
button { margin-right: 0.5em; }
#authbar { display: flex; gap: 0.5em; align-items: center; margin-bottom: 1em; }
.error { color: #b00020; }
fieldset { margin-bottom: 1em; }
</style>
</head>
<body>
<h1>Snippet Locker</h1>
<div id="authbar"></div>

<fieldset id="authbox">
  <legend>Sign up / Log in</legend>
  <input id="email" placeholder="email">
  <input id="password" type="password" placeholder="password (min 8 chars)">
  <button onclick="signup()">Sign up</button>
  <button onclick="login()">Log in</button>
  <div id="autherr" class="error"></div>
</fieldset>

<fieldset id="savebox" style="display:none">
  <legend>Save a snippet</legend>
  <input id="title" placeholder="title">
  <textarea id="body" placeholder="body"></textarea>
  <button onclick="saveSnippet()">Save</button>
  <div id="saveerr" class="error"></div>
</fieldset>

<div id="lists" style="display:none">
  <h2>All snippets</h2>
  <div id="all"></div>
  <h2>My snippets</h2>
  <div id="mine"></div>
</div>

<script>
let me = null;

async function api(path, opts) {
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch (e) {}
  return { status: res.status, body };
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function renderAuthbar() {
  const bar = document.getElementById('authbar');
  if (me) {
    bar.innerHTML = 'Signed in as ' + esc(me.email) + ' (' + esc(me.role) + ') ' +
      '<button onclick="logout()">Log out</button>';
    document.getElementById('authbox').style.display = 'none';
    document.getElementById('savebox').style.display = 'block';
    document.getElementById('lists').style.display = 'block';
  } else {
    bar.innerHTML = 'Not signed in';
    document.getElementById('authbox').style.display = 'block';
    document.getElementById('savebox').style.display = 'none';
    document.getElementById('lists').style.display = 'none';
  }
}

async function signup() {
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const r = await api('/api/auth/signup', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({email, password})});
  if (r.status === 200) { me = r.body; document.getElementById('autherr').textContent=''; renderAuthbar(); refresh(); }
  else { document.getElementById('autherr').textContent = (r.body && r.body.error) || 'error'; }
}

async function login() {
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const r = await api('/api/auth/login', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({email, password})});
  if (r.status === 200) { me = r.body; document.getElementById('autherr').textContent=''; renderAuthbar(); refresh(); }
  else { document.getElementById('autherr').textContent = (r.body && r.body.error) || 'error'; }
}

async function logout() {
  await api('/api/auth/logout', {method: 'POST'});
  me = null;
  renderAuthbar();
}

async function saveSnippet() {
  const title = document.getElementById('title').value;
  const body = document.getElementById('body').value;
  const r = await api('/api/save_snippet', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({title, body})});
  if (r.status === 200) {
    document.getElementById('saveerr').textContent = '';
    document.getElementById('title').value = '';
    document.getElementById('body').value = '';
    refresh();
  } else {
    document.getElementById('saveerr').textContent = (r.body && r.body.error) || 'error';
  }
}

function snippetCard(s) {
  const canEdit = me && (me.id === s.owner_id || me.role === 'admin');
  const canDelete = canEdit;
  let html = '<div class="snippet" id="s' + s.id + '">';
  html += '<h3>' + esc(s.title) + '</h3>';
  if (s.language) html += '<div class="meta">language: ' + esc(s.language) + '</div>';
  html += '<div class="meta">by ' + esc(s.owner) + ' at ' + esc(s.created_at) + '</div>';
  html += '<pre>' + esc(s.body) + '</pre>';
  if (canEdit) {
    html += '<button onclick="startEdit(' + s.id + ')">Edit</button>';
  }
  if (canDelete) {
    html += '<button onclick="doDelete(' + s.id + ')">Delete</button>';
  }
  html += '</div>';
  return html;
}

async function startEdit(id) {
  const newBody = prompt('New body:');
  if (newBody === null) return;
  const r = await api('/api/edit_snippet', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({id, body: newBody})});
  if (r.status === 200) refresh();
  else alert((r.body && r.body.error) || 'error');
}

async function doDelete(id) {
  if (!confirm('Delete this snippet?')) return;
  const r = await api('/api/delete_snippet', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({id})});
  if (r.status === 200) refresh();
  else alert((r.body && r.body.error) || 'error');
}

async function refresh() {
  if (!me) return;
  const all = await api('/api/all_snippets', {method: 'GET'});
  const mine = await api('/api/my_snippets', {method: 'GET'});
  if (all.status === 200) {
    document.getElementById('all').innerHTML = all.body.map(snippetCard).join('') || '<i>none</i>';
  }
  if (mine.status === 200) {
    document.getElementById('mine').innerHTML = mine.body.map(snippetCard).join('') || '<i>none</i>';
  }
}

renderAuthbar();
</script>
</body>
</html>
"""


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Snippet Locker (v1) listening on 127.0.0.1:{PORT}, db={DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
