#!/usr/bin/env python3
"""Room bookings — multi-user booking board (v1).

Python 3 standard library only. Run with:
    python3 app.py
Reads PORT (or MIURA_PORT) and DB_PATH (or MIURA_DB) from the environment.
"""

import hashlib
import hmac
import http.server
import json
import os
import re
import secrets
import socketserver
import sqlite3
import threading
import time
import urllib.parse

ELEVATED_ROLE = "admin"
BASIC_ROLE = "member"

PORT = int(os.environ.get("PORT") or os.environ.get("MIURA_PORT") or 8000)
DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "bookings.db"

DB_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
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
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot TEXT UNIQUE NOT NULL,
                    purpose TEXT NOT NULL,
                    owner_id INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(owner_id) REFERENCES users(id)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
    return dk.hex(), salt


def verify_password(password, salt, expected_hash):
    dk, _ = hash_password(password, salt)
    return hmac.compare_digest(dk, expected_hash)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def user_public(row):
    return {"id": row["id"], "email": row["email"], "role": row["role"]}


def booking_public(row):
    return {
        "id": row["id"],
        "slot": row["slot"],
        "purpose": row["purpose"],
        "owner_id": row["owner_id"],
        "created_at": row["created_at"],
    }


def is_valid_email(email):
    return isinstance(email, str) and "@" in email


def new_session(conn, user_id):
    token = secrets.token_hex(32)
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, user_id, time.time()),
    )
    return token


def get_current_user(conn, cookie_header):
    token = None
    if cookie_header:
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("session="):
                token = part[len("session="):]
                break
    if not token:
        return None
    row = conn.execute(
        """
        SELECT users.* FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ?
        """,
        (token,),
    ).fetchone()
    return row


# --------------------------------------------------------------------------
# Action / query handlers
# All take (conn, user, payload) and return (status, body_dict_or_list)
# user may be None if not signed in.
# --------------------------------------------------------------------------

def require_user(user):
    if user is None:
        raise ApiError(401, "not signed in")
    return user


def action_signup(conn, user, payload):
    email = payload.get("email")
    password = payload.get("password")
    if not is_valid_email(email) or not isinstance(password, str) or len(password) < 8:
        raise ApiError(400, "invalid email or password")
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise ApiError(400, "email already registered")
    count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    role = ELEVATED_ROLE if count == 0 else BASIC_ROLE
    pw_hash, salt = hash_password(password)
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, salt, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (email, pw_hash, salt, role, time.time()),
    )
    user_id = cur.lastrowid
    token = new_session(conn, user_id)
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return 200, user_public(row), token


def action_login(conn, user, payload):
    email = payload.get("email")
    password = payload.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        raise ApiError(400, "invalid credentials")
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not row or not verify_password(password, row["salt"], row["password_hash"]):
        raise ApiError(400, "invalid credentials")
    token = new_session(conn, row["id"])
    conn.commit()
    return 200, user_public(row), token


def action_logout(conn, user, payload):
    return 200, {"ok": True}, None


def action_book(conn, user, payload):
    user = require_user(user)
    slot = payload.get("slot")
    purpose = payload.get("purpose")
    if not isinstance(slot, str) or not (3 <= len(slot) <= 40):
        raise ApiError(400, "slot must be 3-40 chars")
    if not isinstance(purpose, str) or not (1 <= len(purpose) <= 120):
        raise ApiError(400, "purpose must be 1-120 chars")
    existing = conn.execute("SELECT id FROM bookings WHERE slot = ?", (slot,)).fetchone()
    if existing:
        raise ApiError(400, "slot is taken")
    cur = conn.execute(
        "INSERT INTO bookings (slot, purpose, owner_id, created_at) VALUES (?, ?, ?, ?)",
        (slot, purpose, user["id"], time.time()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (cur.lastrowid,)).fetchone()
    return 200, booking_public(row), None


def action_change_purpose(conn, user, payload):
    user = require_user(user)
    bid = payload.get("id")
    purpose = payload.get("purpose")
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone()
    if not row:
        raise ApiError(400, "unknown id")
    if row["owner_id"] != user["id"] and user["role"] != ELEVATED_ROLE:
        raise ApiError(403, "not the owner")
    if not isinstance(purpose, str) or not (1 <= len(purpose) <= 120):
        raise ApiError(400, "purpose must be 1-120 chars")
    conn.execute("UPDATE bookings SET purpose = ? WHERE id = ?", (purpose, bid))
    conn.commit()
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone()
    return 200, booking_public(row), None


def action_cancel(conn, user, payload):
    user = require_user(user)
    bid = payload.get("id")
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone()
    if not row:
        raise ApiError(400, "unknown id")
    if row["owner_id"] != user["id"] and user["role"] != ELEVATED_ROLE:
        raise ApiError(403, "not the owner")
    conn.execute("DELETE FROM bookings WHERE id = ?", (bid,))
    conn.commit()
    return 200, {"ok": True}, None


def query_all_bookings(conn, user, params):
    user = require_user(user)
    rows = conn.execute("SELECT * FROM bookings ORDER BY created_at DESC, id DESC").fetchall()
    return 200, [booking_public(r) for r in rows], None


def query_my_bookings(conn, user, params):
    user = require_user(user)
    rows = conn.execute(
        "SELECT * FROM bookings WHERE owner_id = ? ORDER BY created_at DESC, id DESC",
        (user["id"],),
    ).fetchall()
    return 200, [booking_public(r) for r in rows], None


ACTIONS = {
    "auth/signup": action_signup,
    "auth/login": action_login,
    "auth/logout": action_logout,
    "book": action_book,
    "change_purpose": action_change_purpose,
    "cancel": action_cancel,
}

QUERIES = {
    "all_bookings": query_all_bookings,
    "my_bookings": query_my_bookings,
}


# --------------------------------------------------------------------------
# HTML page
# --------------------------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Room Bookings</title>
<style>
body { font-family: sans-serif; max-width: 720px; margin: 2em auto; padding: 0 1em; }
fieldset { margin-bottom: 1.5em; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
.err { color: red; }
input { margin: 2px; }
</style>
</head>
<body>
<h1>Room Bookings</h1>

<div id="whoami"></div>

<fieldset id="auth-box">
  <legend>Sign up / Log in</legend>
  <input id="email" placeholder="email">
  <input id="password" type="password" placeholder="password">
  <button onclick="signup()">Sign up</button>
  <button onclick="login()">Log in</button>
  <button onclick="logout()">Log out</button>
  <div class="err" id="auth-err"></div>
</fieldset>

<fieldset id="book-box">
  <legend>Book a slot</legend>
  <input id="slot" placeholder="slot (e.g. RoomA-Mon-9am)">
  <input id="purpose" placeholder="purpose">
  <button onclick="book()">Book</button>
  <div class="err" id="book-err"></div>
</fieldset>

<h2>All bookings</h2>
<table id="all-table"><thead><tr><th>slot</th><th>purpose</th><th>owner</th><th></th></tr></thead><tbody></tbody></table>

<h2>My bookings</h2>
<table id="my-table"><thead><tr><th>slot</th><th>purpose</th><th></th></tr></thead><tbody></tbody></table>

<script>
let me = null;

async function api(path, opts) {
  opts = opts || {};
  opts.headers = opts.headers || {};
  if (opts.body) opts.headers['Content-Type'] = 'application/json';
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) {}
  return { status: res.status, data };
}

async function refresh() {
  document.getElementById('whoami').textContent = me ? ('Signed in as ' + me.email + ' (' + me.role + ')') : 'Not signed in';
  if (!me) {
    document.getElementById('all-table').querySelector('tbody').innerHTML = '';
    document.getElementById('my-table').querySelector('tbody').innerHTML = '';
    return;
  }
  const all = await api('/api/all_bookings');
  const mine = await api('/api/my_bookings');
  renderTable('all-table', all.data || [], true);
  renderTable('my-table', mine.data || [], false);
}

function renderTable(tableId, rows, showOwner) {
  const tbody = document.getElementById(tableId).querySelector('tbody');
  tbody.innerHTML = '';
  for (const b of rows) {
    const tr = document.createElement('tr');
    let html = '<td>' + b.slot + '</td><td>' + b.purpose + '</td>';
    if (showOwner) html += '<td>' + b.owner_id + '</td>';
    html += '<td>' +
      '<input size=10 id="p-' + b.id + '" placeholder="new purpose">' +
      '<button onclick="changePurpose(' + b.id + ')">Change</button>' +
      '<button onclick="cancelBooking(' + b.id + ')">Cancel</button>' +
      '</td>';
    tr.innerHTML = html;
    tbody.appendChild(tr);
  }
}

async function signup() {
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const r = await api('/api/auth/signup', { method: 'POST', body: JSON.stringify({ email, password }) });
  document.getElementById('auth-err').textContent = r.status === 200 ? '' : (r.data && r.data.error) || 'error';
  if (r.status === 200) { me = r.data; refresh(); }
}

async function login() {
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const r = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
  document.getElementById('auth-err').textContent = r.status === 200 ? '' : (r.data && r.data.error) || 'error';
  if (r.status === 200) { me = r.data; refresh(); }
}

async function logout() {
  await api('/api/auth/logout', { method: 'POST', body: JSON.stringify({}) });
  me = null;
  refresh();
}

async function book() {
  const slot = document.getElementById('slot').value;
  const purpose = document.getElementById('purpose').value;
  const r = await api('/api/book', { method: 'POST', body: JSON.stringify({ slot, purpose }) });
  document.getElementById('book-err').textContent = r.status === 200 ? '' : (r.data && r.data.error) || 'error';
  if (r.status === 200) refresh();
}

async function changePurpose(id) {
  const purpose = document.getElementById('p-' + id).value;
  const r = await api('/api/change_purpose', { method: 'POST', body: JSON.stringify({ id, purpose }) });
  if (r.status === 200) refresh(); else alert((r.data && r.data.error) || 'error');
}

async function cancelBooking(id) {
  const r = await api('/api/cancel', { method: 'POST', body: JSON.stringify({ id }) });
  if (r.status === 200) refresh(); else alert((r.data && r.data.error) || 'error');
}

refresh();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "BookingsHTTP/1.0"

    def log_message(self, format, *args):
        pass  # keep test output quiet

    def _send_json(self, status, obj, set_cookie=None, clear_cookie=False):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", "session={}; Path=/; HttpOnly".format(set_cookie))
        if clear_cookie:
            self.send_header("Set-Cookie", "session=; Path=/; HttpOnly; Max-Age=0")
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
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "invalid JSON body")
        if not isinstance(data, dict):
            raise ApiError(400, "invalid JSON body")
        return data

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._send_html(200, INDEX_HTML)
            return

        if path.startswith("/api/"):
            name = path[len("/api/"):]
            if name in QUERIES:
                params = urllib.parse.parse_qs(parsed.query)
                with DB_LOCK:
                    conn = get_conn()
                    try:
                        user = get_current_user(conn, self.headers.get("Cookie"))
                        try:
                            status, result, _ = QUERIES[name](conn, user, params)
                            self._send_json(status, result)
                        except ApiError as e:
                            self._send_json(e.status, {"error": e.message})
                    finally:
                        conn.close()
                return
            self._send_json(404, {"error": "not found"})
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if not path.startswith("/api/"):
            self._send_json(404, {"error": "not found"})
            return

        name = path[len("/api/"):]
        if name not in ACTIONS:
            self._send_json(404, {"error": "not found"})
            return

        with DB_LOCK:
            conn = get_conn()
            try:
                try:
                    payload = self._read_json_body()
                except ApiError as e:
                    self._send_json(e.status, {"error": e.message})
                    return
                user = get_current_user(conn, self.headers.get("Cookie"))
                try:
                    status, result, token = ACTIONS[name](conn, user, payload)
                    if name == "auth/logout":
                        # remove the session row if present
                        cookie = self.headers.get("Cookie")
                        if cookie:
                            for part in cookie.split(";"):
                                part = part.strip()
                                if part.startswith("session="):
                                    tok = part[len("session="):]
                                    conn.execute("DELETE FROM sessions WHERE token = ?", (tok,))
                                    conn.commit()
                        self._send_json(status, result, clear_cookie=True)
                    else:
                        self._send_json(status, result, set_cookie=token)
                except ApiError as e:
                    self._send_json(e.status, {"error": e.message})
            finally:
                conn.close()


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Listening on http://127.0.0.1:{}  (db={})".format(PORT, DB_PATH))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
