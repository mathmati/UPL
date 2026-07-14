#!/usr/bin/env python3
"""Room bookings multi-user app - v2 (Python 3 stdlib only).

v2 change: Booking gains an `attendees` field (int, default 1).
"""

import os
import re
import json
import sqlite3
import secrets
import hashlib
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "bookings_v2.db"
PORT = int(os.environ.get("PORT") or os.environ.get("MIURA_PORT") or "8000")

ELEVATED_ROLE = "admin"
BASIC_ROLE = "member"

COOKIE_NAME = "session_token"

DEFAULT_ATTENDEES = 1


def now_iso():
    return datetime.datetime.utcnow().isoformat()


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
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
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
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
                created_at TEXT NOT NULL,
                attendees INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (owner_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return salt + "$" + digest.hex()


def verify_password(password, stored):
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(hash_password(password, salt), stored)


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
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
        "attendees": row["attendees"],
    }


def parse_cookies(header):
    cookies = {}
    if not header:
        return cookies
    for part in header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        cookies[k.strip()] = v.strip()
    return cookies


def parse_attendees(value):
    """Validate/normalize the optional `attendees` input. Returns an int >= 1.

    Raises ApiError(400) on an invalid value; missing/None -> default.
    """
    if value is None:
        return DEFAULT_ATTENDEES
    if isinstance(value, bool):
        raise ApiError(400, "attendees must be a positive integer")
    if isinstance(value, int):
        n = value
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        n = int(value)
    else:
        raise ApiError(400, "attendees must be a positive integer")
    if n < 1:
        raise ApiError(400, "attendees must be a positive integer")
    return n


class Handler(BaseHTTPRequestHandler):
    server_version = "BookingsHTTP/2.0"

    def log_message(self, fmt, *args):
        pass  # keep stdout clean

    # ---- helpers ----
    def _send_json(self, status, payload, set_cookie=None, clear_cookie=False):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}={set_cookie}; Path=/; HttpOnly; SameSite=Lax",
            )
        if clear_cookie:
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
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
            raise ApiError(400, "JSON body must be an object")
        return data

    def _current_user(self, conn):
        cookies = parse_cookies(self.headers.get("Cookie"))
        token = cookies.get(COOKIE_NAME)
        if not token:
            return None
        row = conn.execute(
            "SELECT users.* FROM sessions JOIN users ON sessions.user_id = users.id "
            "WHERE sessions.token = ?",
            (token,),
        ).fetchone()
        return row

    def _require_user(self, conn):
        user = self._current_user(conn)
        if user is None:
            raise ApiError(401, "not signed in")
        return user

    # ---- routing ----
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        conn = get_conn()
        try:
            if path == "/":
                self._send_html(200, INDEX_HTML)
                return
            if path == "/api/all_bookings":
                user = self._require_user(conn)
                rows = conn.execute(
                    "SELECT * FROM bookings ORDER BY id DESC"
                ).fetchall()
                self._send_json(200, [booking_public(r) for r in rows])
                return
            if path == "/api/my_bookings":
                user = self._require_user(conn)
                rows = conn.execute(
                    "SELECT * FROM bookings WHERE owner_id = ? ORDER BY id DESC",
                    (user["id"],),
                ).fetchall()
                self._send_json(200, [booking_public(r) for r in rows])
                return
            self._send_json(404, {"error": "not found"})
        except ApiError as e:
            self._send_json(e.status, {"error": e.message})
        except Exception as e:
            self._send_json(400, {"error": str(e)})
        finally:
            conn.close()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        conn = get_conn()
        try:
            if path == "/api/auth/signup":
                self._handle_signup(conn)
                return
            if path == "/api/auth/login":
                self._handle_login(conn)
                return
            if path == "/api/auth/logout":
                self._handle_logout(conn)
                return
            if path == "/api/book":
                self._handle_book(conn)
                return
            if path == "/api/change_purpose":
                self._handle_change_purpose(conn)
                return
            if path == "/api/cancel":
                self._handle_cancel(conn)
                return
            self._send_json(404, {"error": "not found"})
        except ApiError as e:
            self._send_json(e.status, {"error": e.message})
        except Exception as e:
            self._send_json(400, {"error": str(e)})
        finally:
            conn.close()

    # ---- auth handlers ----
    def _handle_signup(self, conn):
        data = self._read_json_body()
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or "@" not in email:
            raise ApiError(400, "invalid email")
        if not isinstance(password, str) or len(password) < 8:
            raise ApiError(400, "password too short")
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()
        if existing:
            raise ApiError(400, "email already registered")
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        role = ELEVATED_ROLE if count == 0 else BASIC_ROLE
        pw_hash = hash_password(password)
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (email, pw_hash, role, now_iso()),
        )
        user_id = cur.lastrowid
        token = secrets.token_hex(32)
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, now_iso()),
        )
        conn.commit()
        user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        self._send_json(200, user_public(user_row), set_cookie=token)

    def _handle_login(self, conn):
        data = self._read_json_body()
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            raise ApiError(400, "invalid credentials")
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            raise ApiError(400, "wrong email or password")
        token = secrets.token_hex(32)
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, row["id"], now_iso()),
        )
        conn.commit()
        self._send_json(200, user_public(row), set_cookie=token)

    def _handle_logout(self, conn):
        cookies = parse_cookies(self.headers.get("Cookie"))
        token = cookies.get(COOKIE_NAME)
        if token:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
        self._send_json(200, {"ok": True}, clear_cookie=True)

    # ---- booking handlers ----
    def _handle_book(self, conn):
        user = self._require_user(conn)
        data = self._read_json_body()
        slot = data.get("slot")
        purpose = data.get("purpose")
        attendees = parse_attendees(data.get("attendees"))
        if not isinstance(slot, str) or not (3 <= len(slot) <= 40):
            raise ApiError(400, "slot must be 3-40 chars")
        if not isinstance(purpose, str) or not (1 <= len(purpose) <= 120):
            raise ApiError(400, "purpose must be 1-120 chars")
        existing = conn.execute(
            "SELECT id FROM bookings WHERE slot = ?", (slot,)
        ).fetchone()
        if existing:
            raise ApiError(400, "slot is taken")
        cur = conn.execute(
            "INSERT INTO bookings (slot, purpose, owner_id, created_at, attendees) "
            "VALUES (?, ?, ?, ?, ?)",
            (slot, purpose, user["id"], now_iso(), attendees),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        self._send_json(200, booking_public(row))

    def _handle_change_purpose(self, conn):
        user = self._require_user(conn)
        data = self._read_json_body()
        booking_id = data.get("id")
        purpose = data.get("purpose")
        row = self._lookup_booking(conn, booking_id)
        if not isinstance(purpose, str) or not (1 <= len(purpose) <= 120):
            raise ApiError(400, "purpose must be 1-120 chars")
        if row["owner_id"] != user["id"] and user["role"] != ELEVATED_ROLE:
            raise ApiError(403, "not permitted")
        conn.execute(
            "UPDATE bookings SET purpose = ? WHERE id = ?", (purpose, row["id"])
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (row["id"],)
        ).fetchone()
        self._send_json(200, booking_public(updated))

    def _handle_cancel(self, conn):
        user = self._require_user(conn)
        data = self._read_json_body()
        booking_id = data.get("id")
        row = self._lookup_booking(conn, booking_id)
        if row["owner_id"] != user["id"] and user["role"] != ELEVATED_ROLE:
            raise ApiError(403, "not permitted")
        conn.execute("DELETE FROM bookings WHERE id = ?", (row["id"],))
        conn.commit()
        self._send_json(200, {"ok": True})

    def _lookup_booking(self, conn, booking_id):
        if booking_id is None:
            raise ApiError(400, "id required")
        try:
            bid = int(booking_id)
        except (TypeError, ValueError):
            raise ApiError(400, "invalid id")
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone()
        if row is None:
            raise ApiError(400, "unknown id")
        return row


INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Room Bookings</title>
<style>
body { font-family: sans-serif; max-width: 720px; margin: 2em auto; padding: 0 1em; }
fieldset { margin-bottom: 1em; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
.err { color: #b00020; }
button { cursor: pointer; }
</style>
</head>
<body>
<h1>Room Bookings</h1>

<fieldset id="auth-box">
  <legend>Account</legend>
  <div id="auth-forms">
    <div>
      <h3>Sign up</h3>
      <input id="su-email" placeholder="email">
      <input id="su-password" placeholder="password" type="password">
      <button onclick="signup()">Sign up</button>
    </div>
    <div>
      <h3>Log in</h3>
      <input id="li-email" placeholder="email">
      <input id="li-password" placeholder="password" type="password">
      <button onclick="login()">Log in</button>
    </div>
  </div>
  <div id="whoami" style="display:none">
    Signed in as <b id="whoami-email"></b> (<span id="whoami-role"></span>)
    <button onclick="logout()">Log out</button>
  </div>
  <div id="auth-err" class="err"></div>
</fieldset>

<fieldset>
  <legend>Book a slot</legend>
  <input id="book-slot" placeholder="slot (e.g. RoomA-2026-07-14-10:00)">
  <input id="book-purpose" placeholder="purpose">
  <input id="book-attendees" placeholder="attendees" type="number" min="1" value="1" style="width:5em">
  <button onclick="book()">Book</button>
  <div id="book-err" class="err"></div>
</fieldset>

<h2>All bookings</h2>
<table id="all-table">
  <thead><tr><th>Slot</th><th>Purpose</th><th>Attendees</th><th>Owner</th><th>Actions</th></tr></thead>
  <tbody></tbody>
</table>

<h2>My bookings</h2>
<table id="my-table">
  <thead><tr><th>Slot</th><th>Purpose</th><th>Attendees</th><th>Actions</th></tr></thead>
  <tbody></tbody>
</table>

<script>
let me = null;

async function api(path, opts) {
  const res = await fetch(path, Object.assign({credentials: 'same-origin'}, opts));
  let body = null;
  try { body = await res.json(); } catch (e) {}
  if (!res.ok) throw (body && body.error) || ('error ' + res.status);
  return body;
}

async function refreshAuthUi() {
  const box = document.getElementById('whoami');
  const forms = document.getElementById('auth-forms');
  if (me) {
    box.style.display = '';
    forms.style.display = 'none';
    document.getElementById('whoami-email').textContent = me.email;
    document.getElementById('whoami-role').textContent = me.role;
  } else {
    box.style.display = 'none';
    forms.style.display = '';
  }
}

async function signup() {
  document.getElementById('auth-err').textContent = '';
  try {
    me = await api('/api/auth/signup', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: document.getElementById('su-email').value, password: document.getElementById('su-password').value})});
    await refreshAuthUi();
    await loadAll();
  } catch (e) { document.getElementById('auth-err').textContent = e; }
}

async function login() {
  document.getElementById('auth-err').textContent = '';
  try {
    me = await api('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: document.getElementById('li-email').value, password: document.getElementById('li-password').value})});
    await refreshAuthUi();
    await loadAll();
  } catch (e) { document.getElementById('auth-err').textContent = e; }
}

async function logout() {
  await api('/api/auth/logout', {method: 'POST'});
  me = null;
  await refreshAuthUi();
  await loadAll();
}

async function book() {
  document.getElementById('book-err').textContent = '';
  try {
    const attendeesVal = document.getElementById('book-attendees').value;
    await api('/api/book', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        slot: document.getElementById('book-slot').value,
        purpose: document.getElementById('book-purpose').value,
        attendees: attendeesVal ? parseInt(attendeesVal, 10) : 1
      })});
    document.getElementById('book-slot').value = '';
    document.getElementById('book-purpose').value = '';
    document.getElementById('book-attendees').value = '1';
    await loadAll();
  } catch (e) { document.getElementById('book-err').textContent = e; }
}

async function changePurpose(id) {
  const purpose = prompt('New purpose?');
  if (purpose === null) return;
  try {
    await api('/api/change_purpose', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: id, purpose: purpose})});
    await loadAll();
  } catch (e) { alert(e); }
}

async function cancelBooking(id) {
  try {
    await api('/api/cancel', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: id})});
    await loadAll();
  } catch (e) { alert(e); }
}

async function loadAll() {
  const allBody = document.querySelector('#all-table tbody');
  const myBody = document.querySelector('#my-table tbody');
  allBody.innerHTML = '';
  myBody.innerHTML = '';
  if (!me) return;
  try {
    const all = await api('/api/all_bookings');
    for (const b of all) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${b.slot}</td><td>${b.purpose}</td><td>${b.attendees}</td><td>${b.owner_id}</td><td></td>`;
      const td = tr.lastElementChild;
      if (b.owner_id === me.id || me.role === 'admin') {
        const editBtn = document.createElement('button');
        editBtn.textContent = 'Edit';
        editBtn.onclick = () => changePurpose(b.id);
        td.appendChild(editBtn);
        const cancelBtn = document.createElement('button');
        cancelBtn.textContent = 'Cancel';
        cancelBtn.onclick = () => cancelBooking(b.id);
        td.appendChild(cancelBtn);
      }
      allBody.appendChild(tr);
    }
    const mine = await api('/api/my_bookings');
    for (const b of mine) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${b.slot}</td><td>${b.purpose}</td><td>${b.attendees}</td><td></td>`;
      const td = tr.lastElementChild;
      const editBtn = document.createElement('button');
      editBtn.textContent = 'Edit';
      editBtn.onclick = () => changePurpose(b.id);
      td.appendChild(editBtn);
      const cancelBtn = document.createElement('button');
      cancelBtn.textContent = 'Cancel';
      cancelBtn.onclick = () => cancelBooking(b.id);
      td.appendChild(cancelBtn);
      myBody.appendChild(tr);
    }
  } catch (e) { /* ignore */ }
}

refreshAuthUi();
loadAll();
</script>
</body>
</html>
"""


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
