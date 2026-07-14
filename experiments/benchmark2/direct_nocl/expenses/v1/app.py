#!/usr/bin/env python3
"""Expense claims tracker - multi-user HTTP app (Python 3 stdlib only).

Run: python3 app.py
Env: PORT / MIURA_PORT (default 8000), DB_PATH / MIURA_DB (default expenses.db)
"""

import os
import sys
import json
import sqlite3
import secrets
import hashlib
import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "expenses.db"
PORT = int(os.environ.get("PORT") or os.environ.get("MIURA_PORT") or "8000")

ELEVATED_ROLE = "manager"
BASIC_ROLE = "staff"

COOKIE_NAME = "session_id"

MIN_REF_LEN = 3
MAX_REF_LEN = 40
MIN_AMOUNT = 1
MAX_AMOUNT = 1000000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference TEXT UNIQUE NOT NULL,
    amount INTEGER NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    owner_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000)
    return digest.hex(), salt


def verify_password(password, salt, expected_hash):
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, expected_hash)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def user_public(row):
    return {"id": row["id"], "email": row["email"], "role": row["role"]}


def claim_public(row):
    return {
        "id": row["id"],
        "reference": row["reference"],
        "amount": row["amount"],
        "approved": bool(row["approved"]),
        "owner_id": row["owner_id"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Expense Claims</title>
<style>
body { font-family: sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; }
fieldset { margin-bottom: 1.5em; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
.err { color: red; }
.msg { color: green; }
button { cursor: pointer; }
</style>
</head>
<body>
<h1>Expense Claims</h1>

<div id="auth-section">
  <fieldset>
    <legend>Sign up</legend>
    <input id="su-email" placeholder="email">
    <input id="su-password" type="password" placeholder="password (min 8 chars)">
    <button onclick="signup()">Sign up</button>
  </fieldset>
  <fieldset>
    <legend>Log in</legend>
    <input id="li-email" placeholder="email">
    <input id="li-password" type="password" placeholder="password">
    <button onclick="login()">Log in</button>
  </fieldset>
</div>

<div id="app-section" style="display:none">
  <p>Signed in as <b id="me-email"></b> (<span id="me-role"></span>)
     <button onclick="logout()">Log out</button></p>

  <fieldset>
    <legend>Submit a claim</legend>
    <input id="ref" placeholder="reference (3-40 chars)">
    <input id="amount" type="number" placeholder="amount">
    <button onclick="submitClaim()">Submit</button>
  </fieldset>

  <h2>My claims</h2>
  <table id="my-table"><thead><tr><th>Reference</th><th>Amount</th><th>Approved</th><th>Actions</th></tr></thead><tbody></tbody></table>

  <h2>All claims</h2>
  <table id="all-table"><thead><tr><th>Reference</th><th>Amount</th><th>Approved</th><th>Owner</th><th>Actions</th></tr></thead><tbody></tbody></table>
</div>

<p id="status"></p>

<script>
let me = null;

function setStatus(msg, isErr) {
  const el = document.getElementById('status');
  el.textContent = msg || '';
  el.className = isErr ? 'err' : 'msg';
}

async function api(path, opts) {
  opts = opts || {};
  opts.headers = Object.assign({'Content-Type': 'application/json'}, opts.headers || {});
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch (e) { body = null; }
  if (!res.ok) {
    const err = new Error((body && body.error) || ('HTTP ' + res.status));
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

async function signup() {
  try {
    const email = document.getElementById('su-email').value;
    const password = document.getElementById('su-password').value;
    me = await api('/api/auth/signup', {method:'POST', body: JSON.stringify({email, password})});
    setStatus('Signed up as ' + me.email);
    await refresh();
  } catch (e) { setStatus(e.message, true); }
}

async function login() {
  try {
    const email = document.getElementById('li-email').value;
    const password = document.getElementById('li-password').value;
    me = await api('/api/auth/login', {method:'POST', body: JSON.stringify({email, password})});
    setStatus('Logged in as ' + me.email);
    await refresh();
  } catch (e) { setStatus(e.message, true); }
}

async function logout() {
  try {
    await api('/api/auth/logout', {method:'POST', body: '{}'});
    me = null;
    setStatus('Logged out');
    document.getElementById('app-section').style.display = 'none';
    document.getElementById('auth-section').style.display = 'block';
  } catch (e) { setStatus(e.message, true); }
}

async function submitClaim() {
  try {
    const reference = document.getElementById('ref').value;
    const amount = parseInt(document.getElementById('amount').value, 10);
    await api('/api/submit_claim', {method:'POST', body: JSON.stringify({reference, amount})});
    document.getElementById('ref').value = '';
    document.getElementById('amount').value = '';
    setStatus('Claim submitted');
    await loadClaims();
  } catch (e) { setStatus(e.message, true); }
}

async function approveClaim(id) {
  try {
    await api('/api/approve_claim', {method:'POST', body: JSON.stringify({id})});
    setStatus('Claim approved');
    await loadClaims();
  } catch (e) { setStatus(e.message, true); }
}

async function withdrawClaim(id) {
  try {
    await api('/api/withdraw_claim', {method:'POST', body: JSON.stringify({id})});
    setStatus('Claim withdrawn');
    await loadClaims();
  } catch (e) { setStatus(e.message, true); }
}

function renderRow(c, showOwner) {
  const tr = document.createElement('tr');
  const canApprove = me && me.role === 'manager' && !c.approved;
  const canWithdraw = me && (me.role === 'manager' || me.id === c.owner_id);
  tr.innerHTML = '<td>' + c.reference + '</td>' +
    '<td>' + c.amount + '</td>' +
    '<td>' + (c.approved ? 'yes' : 'no') + '</td>' +
    (showOwner ? '<td>' + c.owner_id + '</td>' : '') +
    '<td>' +
    (canApprove ? '<button data-act="approve">Approve</button>' : '') + ' ' +
    (canWithdraw ? '<button data-act="withdraw">Withdraw</button>' : '') +
    '</td>';
  const btns = tr.querySelectorAll('button');
  btns.forEach(b => {
    if (b.dataset.act === 'approve') b.onclick = () => approveClaim(c.id);
    if (b.dataset.act === 'withdraw') b.onclick = () => withdrawClaim(c.id);
  });
  return tr;
}

async function loadClaims() {
  const mine = await api('/api/my_claims');
  const all = await api('/api/all_claims');
  const myBody = document.querySelector('#my-table tbody');
  myBody.innerHTML = '';
  mine.forEach(c => myBody.appendChild(renderRow(c, false)));
  const allBody = document.querySelector('#all-table tbody');
  allBody.innerHTML = '';
  all.forEach(c => allBody.appendChild(renderRow(c, true)));
}

async function refresh() {
  document.getElementById('auth-section').style.display = 'none';
  document.getElementById('app-section').style.display = 'block';
  document.getElementById('me-email').textContent = me.email;
  document.getElementById('me-role').textContent = me.role;
  await loadClaims();
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "ExpensesHTTP/1.0"

    def log_message(self, fmt, *args):
        pass  # keep stdout quiet

    # -- helpers -----------------------------------------------------------

    def _send_json(self, status, payload, set_cookie=None, clear_cookie=False):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            cookie = SimpleCookie()
            cookie[COOKIE_NAME] = set_cookie
            cookie[COOKIE_NAME]["path"] = "/"
            cookie[COOKIE_NAME]["httponly"] = True
            self.send_header("Set-Cookie", cookie.output(header="").strip())
        if clear_cookie:
            cookie = SimpleCookie()
            cookie[COOKIE_NAME] = ""
            cookie[COOKIE_NAME]["path"] = "/"
            cookie[COOKIE_NAME]["max-age"] = 0
            self.send_header("Set-Cookie", cookie.output(header="").strip())
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
            raise ApiError(400, "expected a JSON object body")
        return data

    def _get_session_token(self):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return None
        if COOKIE_NAME in cookie:
            return cookie[COOKIE_NAME].value
        return None

    def _current_user(self, conn):
        token = self._get_session_token()
        if not token:
            return None
        row = conn.execute(
            "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ?",
            (token,),
        ).fetchone()
        return row

    def _require_user(self, conn):
        user = self._current_user(conn)
        if user is None:
            raise ApiError(401, "not signed in")
        return user

    # -- routing -------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/":
                self._send_html(200, PAGE)
                return
            if path == "/api/all_claims":
                self._handle_all_claims()
                return
            if path == "/api/my_claims":
                self._handle_my_claims()
                return
            self._send_json(404, {"error": "not found"})
        except ApiError as e:
            self._send_json(e.status, {"error": e.message})
        except Exception as e:
            self._send_json(400, {"error": "bad request"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/auth/signup":
                self._handle_signup()
                return
            if path == "/api/auth/login":
                self._handle_login()
                return
            if path == "/api/auth/logout":
                self._handle_logout()
                return
            if path == "/api/submit_claim":
                self._handle_submit_claim()
                return
            if path == "/api/approve_claim":
                self._handle_approve_claim()
                return
            if path == "/api/withdraw_claim":
                self._handle_withdraw_claim()
                return
            self._send_json(404, {"error": "not found"})
        except ApiError as e:
            self._send_json(e.status, {"error": e.message})
        except Exception as e:
            self._send_json(400, {"error": "bad request"})

    # -- auth handlers -----------------------------------------------------

    def _handle_signup(self):
        data = self._read_json_body()
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or "@" not in email:
            raise ApiError(400, "invalid email")
        if not isinstance(password, str) or len(password) < 8:
            raise ApiError(400, "password too short")

        conn = get_conn()
        try:
            existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                raise ApiError(400, "email already registered")

            count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            role = ELEVATED_ROLE if count == 0 else BASIC_ROLE

            pw_hash, salt = hash_password(password)
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, salt, role) VALUES (?, ?, ?, ?)",
                (email, pw_hash, salt, role),
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
        finally:
            conn.close()

    def _handle_login(self):
        data = self._read_json_body()
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            raise ApiError(400, "invalid credentials")

        conn = get_conn()
        try:
            user_row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if user_row is None or not verify_password(password, user_row["salt"], user_row["password_hash"]):
                raise ApiError(400, "invalid email or password")

            token = secrets.token_hex(32)
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                (token, user_row["id"], now_iso()),
            )
            conn.commit()
            self._send_json(200, user_public(user_row), set_cookie=token)
        finally:
            conn.close()

    def _handle_logout(self):
        conn = get_conn()
        try:
            token = self._get_session_token()
            if token:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                conn.commit()
            self._send_json(200, {"ok": True}, clear_cookie=True)
        finally:
            conn.close()

    # -- claim action handlers ----------------------------------------------

    def _handle_submit_claim(self):
        conn = get_conn()
        try:
            user = self._require_user(conn)
            data = self._read_json_body()
            reference = data.get("reference")
            amount = data.get("amount")

            if not isinstance(reference, str):
                raise ApiError(400, "reference is required")
            if len(reference) < MIN_REF_LEN or len(reference) > MAX_REF_LEN:
                raise ApiError(400, "reference must be 3-40 chars")

            if isinstance(amount, bool) or not isinstance(amount, (int, float)):
                raise ApiError(400, "amount must be a number")
            if isinstance(amount, float) and not amount.is_integer():
                raise ApiError(400, "amount must be an integer")
            amount = int(amount)
            if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
                raise ApiError(400, "amount out of range")

            existing = conn.execute(
                "SELECT id FROM claims WHERE reference = ?", (reference,)
            ).fetchone()
            if existing:
                raise ApiError(400, "duplicate reference")

            created_at = now_iso()
            cur = conn.execute(
                "INSERT INTO claims (reference, amount, approved, owner_id, created_at) "
                "VALUES (?, ?, 0, ?, ?)",
                (reference, amount, user["id"], created_at),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM claims WHERE id = ?", (cur.lastrowid,)).fetchone()
            self._send_json(200, claim_public(row))
        finally:
            conn.close()

    def _handle_approve_claim(self):
        conn = get_conn()
        try:
            user = self._require_user(conn)
            data = self._read_json_body()
            claim_id = data.get("id")

            if user["role"] != ELEVATED_ROLE:
                raise ApiError(403, "manager role required")

            if not isinstance(claim_id, (int, float)) or isinstance(claim_id, bool):
                raise ApiError(400, "invalid id")
            claim_id = int(claim_id)

            row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
            if row is None:
                raise ApiError(400, "unknown claim id")

            conn.execute("UPDATE claims SET approved = 1 WHERE id = ?", (claim_id,))
            conn.commit()
            row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
            self._send_json(200, claim_public(row))
        finally:
            conn.close()

    def _handle_withdraw_claim(self):
        conn = get_conn()
        try:
            user = self._require_user(conn)
            data = self._read_json_body()
            claim_id = data.get("id")

            if not isinstance(claim_id, (int, float)) or isinstance(claim_id, bool):
                raise ApiError(400, "invalid id")
            claim_id = int(claim_id)

            row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
            if row is None:
                raise ApiError(400, "unknown claim id")

            if row["owner_id"] != user["id"] and user["role"] != ELEVATED_ROLE:
                raise ApiError(403, "not permitted to withdraw this claim")

            conn.execute("DELETE FROM claims WHERE id = ?", (claim_id,))
            conn.commit()
            self._send_json(200, {"id": claim_id, "deleted": True})
        finally:
            conn.close()

    # -- queries -------------------------------------------------------

    def _handle_all_claims(self):
        conn = get_conn()
        try:
            self._require_user(conn)
            rows = conn.execute(
                "SELECT * FROM claims ORDER BY created_at DESC, id DESC"
            ).fetchall()
            self._send_json(200, [claim_public(r) for r in rows])
        finally:
            conn.close()

    def _handle_my_claims(self):
        conn = get_conn()
        try:
            user = self._require_user(conn)
            rows = conn.execute(
                "SELECT * FROM claims WHERE owner_id = ? ORDER BY created_at DESC, id DESC",
                (user["id"],),
            ).fetchall()
            self._send_json(200, [claim_public(r) for r in rows])
        finally:
            conn.close()


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Serving on http://127.0.0.1:{PORT} (DB: {DB_PATH})", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
