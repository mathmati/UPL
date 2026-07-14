#!/usr/bin/env python3
"""Shared docs - multi-user app (v2). Python 3 stdlib only.

v2 change: Doc gains an `archived` (bool, default false) field.
"""

import os
import sqlite3
import json
import hashlib
import hmac
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs

ROLE_ELEVATED = "editor"
ROLE_BASIC = "author"

COOKIE_NAME = "session_token"

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "docs_v2.db"
PORT = int(os.environ.get("PORT") or os.environ.get("MIURA_PORT") or 8000)

LOCK = threading.RLock()
_conn = None


def get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
    return _conn


def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        );
        """
    )
    conn.commit()


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + (".%03dZ" % (int(time.time() * 1000) % 1000))


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return salt, dk.hex()


def verify_password(password, salt, expected_hash):
    _, computed = hash_password(password, salt)
    return hmac.compare_digest(computed, expected_hash)


def user_public(row):
    return {"id": row["id"], "email": row["email"], "role": row["role"]}


def doc_public(row):
    return {
        "id": row["id"],
        "slug": row["slug"],
        "title": row["title"],
        "owner_id": row["owner_id"],
        "created_at": row["created_at"],
        "archived": bool(row["archived"]),
    }


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def require_user(user):
    if user is None:
        raise ApiError(401, "not signed in")
    return user


def is_elevated(user):
    return user["role"] == ROLE_ELEVATED


def validate_slug(slug):
    if not isinstance(slug, str) or not (3 <= len(slug) <= 50):
        raise ApiError(400, "invalid slug")


def validate_title(title):
    if not isinstance(title, str) or not (1 <= len(title) <= 150):
        raise ApiError(400, "invalid title")


# ---------------------------------------------------------------------------
# Action / query implementations. Each takes (user, params) and returns a
# JSON-serializable value plus a status code (default 200).
# ---------------------------------------------------------------------------

def action_signup(user, body, set_cookie):
    email = body.get("email")
    password = body.get("password")
    if not isinstance(email, str) or "@" not in email:
        raise ApiError(400, "invalid email")
    if not isinstance(password, str) or len(password) < 8:
        raise ApiError(400, "invalid password")
    email_norm = email.strip().lower()

    with LOCK:
        conn = get_conn()
        cur = conn.execute("SELECT id FROM users WHERE email = ?", (email_norm,))
        if cur.fetchone() is not None:
            raise ApiError(400, "duplicate email")

        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        role = ROLE_ELEVATED if count == 0 else ROLE_BASIC

        salt, pw_hash = hash_password(password)
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, password_salt, role, created_at) VALUES (?,?,?,?,?)",
            (email_norm, pw_hash, salt, role, now_iso()),
        )
        conn.commit()
        user_id = cur.lastrowid
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

        token = secrets.token_hex(32)
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
            (token, user_id, now_iso()),
        )
        conn.commit()

    set_cookie(token)
    return 200, user_public(row)


def action_login(user, body, set_cookie):
    email = body.get("email")
    password = body.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        raise ApiError(400, "invalid credentials")
    email_norm = email.strip().lower()

    with LOCK:
        conn = get_conn()
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email_norm,)).fetchone()
        if row is None or not verify_password(password, row["password_salt"], row["password_hash"]):
            raise ApiError(400, "invalid credentials")

        token = secrets.token_hex(32)
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
            (token, row["id"], now_iso()),
        )
        conn.commit()

    set_cookie(token)
    return 200, user_public(row)


def action_logout(user, body, clear_cookie):
    clear_cookie()
    return 200, {"ok": True}


def action_create_doc(user, body):
    require_user(user)
    slug = body.get("slug")
    title = body.get("title")
    validate_slug(slug)
    validate_title(title)

    with LOCK:
        conn = get_conn()
        existing = conn.execute("SELECT id FROM docs WHERE slug = ?", (slug,)).fetchone()
        if existing is not None:
            raise ApiError(400, "duplicate slug")
        cur = conn.execute(
            "INSERT INTO docs (slug, title, owner_id, created_at) VALUES (?,?,?,?)",
            (slug, title, user["id"], now_iso()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM docs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return 200, doc_public(row)


def action_rename_doc(user, body):
    require_user(user)
    doc_id = body.get("id")
    title = body.get("title")

    with LOCK:
        conn = get_conn()
        row = conn.execute("SELECT * FROM docs WHERE id = ?", (doc_id,)).fetchone()
        if row is None:
            raise ApiError(400, "unknown id")
        validate_title(title)
        if row["owner_id"] != user["id"] and not is_elevated(user):
            raise ApiError(403, "not permitted")
        conn.execute("UPDATE docs SET title = ? WHERE id = ?", (title, doc_id))
        conn.commit()
        row = conn.execute("SELECT * FROM docs WHERE id = ?", (doc_id,)).fetchone()
    return 200, doc_public(row)


def action_delete_doc(user, body):
    require_user(user)
    doc_id = body.get("id")

    with LOCK:
        conn = get_conn()
        row = conn.execute("SELECT * FROM docs WHERE id = ?", (doc_id,)).fetchone()
        if row is None:
            raise ApiError(400, "unknown id")
        if row["owner_id"] != user["id"] and not is_elevated(user):
            raise ApiError(403, "not permitted")
        conn.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
        conn.commit()
    return 200, doc_public(row)


def query_all_docs(user, params):
    require_user(user)
    with LOCK:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM docs ORDER BY created_at DESC, id DESC").fetchall()
    return 200, [doc_public(r) for r in rows]


def query_my_docs(user, params):
    require_user(user)
    with LOCK:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM docs WHERE owner_id = ? ORDER BY created_at DESC, id DESC",
            (user["id"],),
        ).fetchall()
    return 200, [doc_public(r) for r in rows]


INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Shared Docs</title>
<style>
body { font-family: sans-serif; max-width: 800px; margin: 2em auto; }
input { display: block; margin: 4px 0; padding: 4px; width: 100%; box-sizing: border-box; }
button { padding: 6px 12px; margin: 4px 4px 4px 0; }
.doc { border: 1px solid #ccc; padding: 8px; margin: 6px 0; border-radius: 4px; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
#status { color: #555; margin-bottom: 1em; }
fieldset { margin-bottom: 1.5em; }
</style>
</head>
<body>
<h1>Shared Docs</h1>
<div id="status">Not signed in.</div>

<fieldset id="auth-box">
<legend>Account</legend>
<input id="email" placeholder="email">
<input id="password" type="password" placeholder="password">
<button onclick="signup()">Sign up</button>
<button onclick="login()">Log in</button>
<button onclick="logout()">Log out</button>
</fieldset>

<fieldset>
<legend>Create doc</legend>
<input id="slug" placeholder="slug (3-50 chars)">
<input id="title" placeholder="title (1-150 chars)">
<button onclick="createDoc()">Create</button>
</fieldset>

<h2>My docs</h2>
<div id="my-docs"></div>

<h2>All docs</h2>
<div id="all-docs"></div>

<script>
let me = null;

async function api(method, path, body) {
  const opts = { method, headers: {}, credentials: 'same-origin' };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) {
    throw new Error((data && data.error) || ('HTTP ' + res.status));
  }
  return data;
}

function setStatus(msg) { document.getElementById('status').textContent = msg; }

async function signup() {
  try {
    me = await api('POST', '/api/auth/signup', { email: val('email'), password: val('password') });
    setStatus('Signed up as ' + me.email + ' (' + me.role + ')');
    refresh();
  } catch (e) { setStatus('Error: ' + e.message); }
}

async function login() {
  try {
    me = await api('POST', '/api/auth/login', { email: val('email'), password: val('password') });
    setStatus('Logged in as ' + me.email + ' (' + me.role + ')');
    refresh();
  } catch (e) { setStatus('Error: ' + e.message); }
}

async function logout() {
  try {
    await api('POST', '/api/auth/logout', {});
    me = null;
    setStatus('Not signed in.');
    refresh();
  } catch (e) { setStatus('Error: ' + e.message); }
}

function val(id) { return document.getElementById(id).value; }

async function createDoc() {
  try {
    await api('POST', '/api/create_doc', { slug: val('slug'), title: val('title') });
    document.getElementById('slug').value = '';
    document.getElementById('title').value = '';
    refresh();
  } catch (e) { setStatus('Error: ' + e.message); }
}

async function renameDoc(id) {
  const title = prompt('New title:');
  if (title === null) return;
  try {
    await api('POST', '/api/rename_doc', { id: id, title: title });
    refresh();
  } catch (e) { setStatus('Error: ' + e.message); }
}

async function deleteDoc(id) {
  try {
    await api('POST', '/api/delete_doc', { id: id });
    refresh();
  } catch (e) { setStatus('Error: ' + e.message); }
}

function renderDocs(containerId, docs) {
  const el = document.getElementById(containerId);
  el.innerHTML = '';
  docs.forEach(d => {
    const div = document.createElement('div');
    div.className = 'doc';
    div.innerHTML = '<div class="row"><div><strong>' + escapeHtml(d.title) +
      '</strong> <code>' + escapeHtml(d.slug) + '</code> (owner ' + d.owner_id + ')' +
      (d.archived ? ' <em>[archived]</em>' : '') + '</div>' +
      '<div><button onclick="renameDoc(' + d.id + ')">Rename</button>' +
      '<button onclick="deleteDoc(' + d.id + ')">Delete</button></div></div>';
    el.appendChild(div);
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\\'':'&#39;'}[c]));
}

async function refresh() {
  try {
    const all = await api('GET', '/api/all_docs');
    renderDocs('all-docs', all);
  } catch (e) { document.getElementById('all-docs').textContent = ''; }
  try {
    const mine = await api('GET', '/api/my_docs');
    renderDocs('my-docs', mine);
  } catch (e) { document.getElementById('my-docs').textContent = ''; }
}

refresh();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "DocsApp/1.0"

    def log_message(self, fmt, *args):
        pass  # keep test output quiet

    # -- helpers -----------------------------------------------------
    def _get_cookie_token(self):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        c = SimpleCookie()
        c.load(cookie_header)
        if COOKIE_NAME in c:
            return c[COOKIE_NAME].value
        return None

    def _current_user(self):
        token = self._get_cookie_token()
        if not token:
            return None
        with LOCK:
            conn = get_conn()
            row = conn.execute(
                "SELECT users.* FROM sessions JOIN users ON sessions.user_id = users.id "
                "WHERE sessions.token = ?",
                (token,),
            ).fetchone()
        return row

    def _set_cookie_header(self, headers_list, token):
        headers_list.append(("Set-Cookie", f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax"))

    def _clear_cookie_header(self, headers_list):
        headers_list.append(("Set-Cookie", f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"))

    def _send_json(self, status, payload, extra_headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
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
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ApiError(400, "invalid JSON body")
        if not isinstance(data, dict):
            raise ApiError(400, "invalid JSON body")
        return data

    # -- routing -------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        try:
            if path == "/":
                self._send_html(200, INDEX_HTML)
                return
            user = self._current_user()
            if path == "/api/all_docs":
                status, result = query_all_docs(user, params)
                self._send_json(status, result)
                return
            if path == "/api/my_docs":
                status, result = query_my_docs(user, params)
                self._send_json(status, result)
                return
            self._send_json(404, {"error": "not found"})
        except ApiError as e:
            self._send_json(e.status, {"error": e.message})
        except Exception as e:
            self._send_json(400, {"error": str(e)})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json_body()
        except ApiError as e:
            self._send_json(e.status, {"error": e.message})
            return

        extra_headers = []

        try:
            user = self._current_user()

            if path == "/api/auth/signup":
                status, result = action_signup(
                    user, body, lambda tok: self._set_cookie_header(extra_headers, tok)
                )
            elif path == "/api/auth/login":
                status, result = action_login(
                    user, body, lambda tok: self._set_cookie_header(extra_headers, tok)
                )
            elif path == "/api/auth/logout":
                status, result = action_logout(
                    user, body, lambda: self._clear_cookie_header(extra_headers)
                )
            elif path == "/api/create_doc":
                status, result = action_create_doc(user, body)
            elif path == "/api/rename_doc":
                status, result = action_rename_doc(user, body)
            elif path == "/api/delete_doc":
                status, result = action_delete_doc(user, body)
            else:
                self._send_json(404, {"error": "not found"})
                return

            self._send_json(status, result, extra_headers)
        except ApiError as e:
            self._send_json(e.status, {"error": e.message}, extra_headers)
        except Exception as e:
            self._send_json(400, {"error": str(e)}, extra_headers)


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Serving on 127.0.0.1:{PORT}, db={DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
