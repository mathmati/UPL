#!/usr/bin/env python3
"""Expense claims tracker - multi-user app, Python 3 stdlib only (v2).

v2 change: Claim gains a `category` field (text, default "general").
"""
import datetime
import hashlib
import json
import os
import secrets
import sqlite3
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DB_PATH = os.environ.get("DB_PATH") or os.environ.get("MIURA_DB") or "expenses.db"
PORT = int(os.environ.get("PORT") or os.environ.get("MIURA_PORT") or 8000)

MANAGER = "manager"
STAFF = "staff"

PBKDF2_ITERATIONS = 100_000


def now_iso():
    return datetime.datetime.utcnow().isoformat()


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
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
            created_at TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general'
        );
        """
    )
    conn.commit()
    conn.close()


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return dk.hex(), salt


def verify_password(password, salt, hash_hex):
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return secrets.compare_digest(dk.hex(), hash_hex)


INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Expense Claims</title>
<style>
body { font-family: sans-serif; max-width: 780px; margin: 2em auto; padding: 0 1em; }
fieldset { margin-bottom: 1.5em; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
.error { color: red; }
button { cursor: pointer; }
</style>
</head>
<body>
<h1>Expense Claims</h1>

<div id="auth-section">
  <fieldset id="signed-out">
    <legend>Sign up / Log in</legend>
    <input id="email" placeholder="email" type="email">
    <input id="password" placeholder="password" type="password">
    <button onclick="signup()">Sign up</button>
    <button onclick="login()">Log in</button>
    <div id="auth-error" class="error"></div>
  </fieldset>
  <fieldset id="signed-in" style="display:none">
    <legend>Account</legend>
    <span id="whoami"></span>
    <button onclick="logout()">Log out</button>
  </fieldset>
</div>

<fieldset id="submit-section" style="display:none">
  <legend>Submit a claim</legend>
  <input id="reference" placeholder="reference (3-40 chars)">
  <input id="amount" placeholder="amount" type="number">
  <input id="category" placeholder="category (default: general)">
  <button onclick="submitClaim()">Submit</button>
  <div id="submit-error" class="error"></div>
</fieldset>

<fieldset id="claims-section" style="display:none">
  <legend>Claims</legend>
  <label><input type="radio" name="view" value="all" checked onchange="refresh()"> All claims</label>
  <label><input type="radio" name="view" value="mine" onchange="refresh()"> My claims</label>
  <table id="claims-table">
    <thead><tr><th>Ref</th><th>Amount</th><th>Category</th><th>Approved</th><th>Owner</th><th>Actions</th></tr></thead>
    <tbody id="claims-body"></tbody>
  </table>
</fieldset>

<script>
let currentUser = null;

function api(path, opts) {
  opts = opts || {};
  opts.credentials = 'same-origin';
  return fetch(path, opts).then(async r => {
    let body = null;
    try { body = await r.json(); } catch (e) {}
    return { status: r.status, body };
  });
}

function post(path, data) {
  return api(path, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
}

async function signup() {
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const res = await post('/api/auth/signup', {email, password});
  if (res.status === 200) { onAuth(res.body); } else { showAuthError(res.body); }
}

async function login() {
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const res = await post('/api/auth/login', {email, password});
  if (res.status === 200) { onAuth(res.body); } else { showAuthError(res.body); }
}

async function logout() {
  await post('/api/auth/logout', {});
  currentUser = null;
  document.getElementById('signed-in').style.display = 'none';
  document.getElementById('signed-out').style.display = 'block';
  document.getElementById('submit-section').style.display = 'none';
  document.getElementById('claims-section').style.display = 'none';
}

function showAuthError(body) {
  document.getElementById('auth-error').textContent = (body && body.error) || 'error';
}

function onAuth(user) {
  currentUser = user;
  document.getElementById('auth-error').textContent = '';
  document.getElementById('signed-out').style.display = 'none';
  document.getElementById('signed-in').style.display = 'block';
  document.getElementById('whoami').textContent = user.email + ' (' + user.role + ')';
  document.getElementById('submit-section').style.display = 'block';
  document.getElementById('claims-section').style.display = 'block';
  refresh();
}

async function submitClaim() {
  const reference = document.getElementById('reference').value;
  const amount = parseInt(document.getElementById('amount').value, 10);
  const category = document.getElementById('category').value;
  const res = await post('/api/submit_claim', {reference, amount, category});
  if (res.status === 200) {
    document.getElementById('submit-error').textContent = '';
    document.getElementById('reference').value = '';
    document.getElementById('amount').value = '';
    document.getElementById('category').value = '';
    refresh();
  } else {
    document.getElementById('submit-error').textContent = (res.body && res.body.error) || 'error';
  }
}

async function approveClaim(id) {
  const res = await post('/api/approve_claim', {id});
  refresh();
}

async function withdrawClaim(id) {
  const res = await post('/api/withdraw_claim', {id});
  refresh();
}

async function refresh() {
  const view = document.querySelector('input[name="view"]:checked').value;
  const path = view === 'mine' ? '/api/my_claims' : '/api/all_claims';
  const res = await api(path);
  if (res.status !== 200) return;
  const tbody = document.getElementById('claims-body');
  tbody.innerHTML = '';
  for (const c of res.body) {
    const tr = document.createElement('tr');
    const isOwner = currentUser && c.owner_id === currentUser.id;
    const isManager = currentUser && currentUser.role === 'manager';
    let actions = '';
    if (!c.approved && isManager) {
      actions += '<button onclick="approveClaim(' + c.id + ')">Approve</button> ';
    }
    if (isOwner || isManager) {
      actions += '<button onclick="withdrawClaim(' + c.id + ')">Withdraw</button>';
    }
    tr.innerHTML = '<td>' + c.reference + '</td><td>' + c.amount + '</td><td>' + c.category + '</td><td>' +
      (c.approved ? 'yes' : 'no') + '</td><td>' + c.owner_id + '</td><td>' + actions + '</td>';
    tbody.appendChild(tr);
  }
}

// Try to detect existing session on load.
(async function init() {
  const res = await api('/api/all_claims');
  if (res.status === 200) {
    // We are signed in but don't know who; fetch my_claims won't tell us email.
    // Leave auth section visible as a fallback; user info unknown until login.
  }
})();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "ExpenseApp/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # ---------- helpers ----------
    def _send_json(self, status, obj, cookie=None):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

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

    def _get_cookie_token(self):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        c = SimpleCookie()
        try:
            c.load(cookie_header)
        except Exception:
            return None
        if "sid" in c:
            return c["sid"].value
        return None

    def _get_current_user(self, conn):
        token = self._get_cookie_token()
        if not token:
            return None
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        return row

    def _claim_to_dict(self, row):
        return {
            "id": row["id"],
            "reference": row["reference"],
            "amount": row["amount"],
            "approved": bool(row["approved"]),
            "owner_id": row["owner_id"],
            "created_at": row["created_at"],
            "category": row["category"],
        }

    def _fetch_claims(self, conn, owner_id=None):
        if owner_id is not None:
            rows = conn.execute(
                "SELECT * FROM claims WHERE owner_id = ? ORDER BY id DESC", (owner_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM claims ORDER BY id DESC").fetchall()
        return [self._claim_to_dict(r) for r in rows]

    # ---------- routing ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send_html(200, INDEX_HTML)
            return
        conn = get_conn()
        try:
            if path == "/api/all_claims":
                user = self._get_current_user(conn)
                if not user:
                    self._send_json(401, {"error": "unauthorized"})
                    return
                self._send_json(200, self._fetch_claims(conn))
                return
            if path == "/api/my_claims":
                user = self._get_current_user(conn)
                if not user:
                    self._send_json(401, {"error": "unauthorized"})
                    return
                self._send_json(200, self._fetch_claims(conn, owner_id=user["id"]))
                return
            self._send_json(404, {"error": "not found"})
        finally:
            conn.close()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        conn = get_conn()
        try:
            if path == "/api/auth/signup":
                self._handle_signup(conn)
            elif path == "/api/auth/login":
                self._handle_login(conn)
            elif path == "/api/auth/logout":
                self._handle_logout(conn)
            elif path == "/api/submit_claim":
                self._handle_submit_claim(conn)
            elif path == "/api/approve_claim":
                self._handle_approve_claim(conn)
            elif path == "/api/withdraw_claim":
                self._handle_withdraw_claim(conn)
            else:
                self._send_json(404, {"error": "not found"})
        finally:
            conn.close()

    # ---------- auth ----------
    def _handle_signup(self, conn):
        data = self._read_json_body()
        if data is None:
            self._send_json(400, {"error": "invalid json"})
            return
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or "@" not in email:
            self._send_json(400, {"error": "invalid email"})
            return
        if not isinstance(password, str) or len(password) < 8:
            self._send_json(400, {"error": "password too short"})
            return
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            self._send_json(400, {"error": "email already registered"})
            return
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        role = MANAGER if count == 0 else STAFF
        pw_hash, salt = hash_password(password)
        ts = now_iso()
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, salt, role, created_at) VALUES (?,?,?,?,?)",
            (email, pw_hash, salt, role, ts),
        )
        conn.commit()
        user_id = cur.lastrowid
        token = secrets.token_hex(32)
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
            (token, user_id, ts),
        )
        conn.commit()
        cookie = "sid=%s; Path=/; HttpOnly; SameSite=Lax" % token
        self._send_json(200, {"id": user_id, "email": email, "role": role}, cookie=cookie)

    def _handle_login(self, conn):
        data = self._read_json_body()
        if data is None:
            self._send_json(400, {"error": "invalid json"})
            return
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            self._send_json(400, {"error": "invalid credentials"})
            return
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row or not verify_password(password, row["salt"], row["password_hash"]):
            self._send_json(400, {"error": "invalid credentials"})
            return
        token = secrets.token_hex(32)
        ts = now_iso()
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
            (token, row["id"], ts),
        )
        conn.commit()
        cookie = "sid=%s; Path=/; HttpOnly; SameSite=Lax" % token
        self._send_json(
            200, {"id": row["id"], "email": row["email"], "role": row["role"]}, cookie=cookie
        )

    def _handle_logout(self, conn):
        token = self._get_cookie_token()
        if token:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
        cookie = "sid=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
        self._send_json(200, {"ok": True}, cookie=cookie)

    # ---------- claims ----------
    def _handle_submit_claim(self, conn):
        user = self._get_current_user(conn)
        if not user:
            self._send_json(401, {"error": "unauthorized"})
            return
        data = self._read_json_body()
        if data is None:
            self._send_json(400, {"error": "invalid json"})
            return
        reference = data.get("reference")
        amount = data.get("amount")
        if not isinstance(reference, str) or not (3 <= len(reference) <= 40):
            self._send_json(400, {"error": "invalid reference"})
            return
        if isinstance(amount, bool) or not isinstance(amount, int) or not (1 <= amount <= 1000000):
            self._send_json(400, {"error": "invalid amount"})
            return
        category = data.get("category")
        if not isinstance(category, str) or not category.strip():
            category = "general"
        ts = now_iso()
        try:
            cur = conn.execute(
                "INSERT INTO claims (reference, amount, approved, owner_id, created_at, category) VALUES (?,?,0,?,?,?)",
                (reference, amount, user["id"], ts, category),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            self._send_json(400, {"error": "duplicate reference"})
            return
        row = conn.execute("SELECT * FROM claims WHERE id = ?", (cur.lastrowid,)).fetchone()
        self._send_json(200, self._claim_to_dict(row))

    def _handle_approve_claim(self, conn):
        user = self._get_current_user(conn)
        if not user:
            self._send_json(401, {"error": "unauthorized"})
            return
        data = self._read_json_body()
        if data is None:
            self._send_json(400, {"error": "invalid json"})
            return
        claim_id = data.get("id")
        row = None
        if isinstance(claim_id, int) and not isinstance(claim_id, bool):
            row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        if not row:
            self._send_json(400, {"error": "unknown id"})
            return
        if user["role"] != MANAGER:
            self._send_json(403, {"error": "manager role required"})
            return
        conn.execute("UPDATE claims SET approved = 1 WHERE id = ?", (claim_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        self._send_json(200, self._claim_to_dict(row))

    def _handle_withdraw_claim(self, conn):
        user = self._get_current_user(conn)
        if not user:
            self._send_json(401, {"error": "unauthorized"})
            return
        data = self._read_json_body()
        if data is None:
            self._send_json(400, {"error": "invalid json"})
            return
        claim_id = data.get("id")
        row = None
        if isinstance(claim_id, int) and not isinstance(claim_id, bool):
            row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        if not row:
            self._send_json(400, {"error": "unknown id"})
            return
        if row["owner_id"] != user["id"] and user["role"] != MANAGER:
            self._send_json(403, {"error": "not owner"})
            return
        conn.execute("DELETE FROM claims WHERE id = ?", (claim_id,))
        conn.commit()
        self._send_json(200, {"ok": True})


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
