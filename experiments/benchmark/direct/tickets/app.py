#!/usr/bin/env python3
"""Tiny support-ticket tracker. Python 3 standard library only."""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

PORT = int(os.environ.get("PORT") or os.environ.get("UPL_PORT") or 8000)
DB_PATH = os.environ.get("DB_PATH") or os.environ.get("UPL_DB") or ":memory:"

_local = threading.local()
_db_lock = threading.Lock()


def get_conn():
    # Each thread gets its own connection; for a file-based DB this is safe.
    # For :memory: DB we must share a single connection across threads.
    if DB_PATH == ":memory:":
        if not hasattr(get_conn, "_shared"):
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            conn.row_factory = sqlite3.Row
            get_conn._shared = conn
        return get_conn._shared
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    conn = get_conn()
    with _db_lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                priority INTEGER NOT NULL,
                open INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def row_to_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "priority": row["priority"],
        "open": bool(row["open"]),
        "created_at": row["created_at"],
    }


class ApiError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def parse_id(value):
    """Coerce an incoming id (int or numeric string) to int, or raise ApiError."""
    if isinstance(value, bool):
        raise ApiError("invalid id")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            raise ApiError("invalid id")
    raise ApiError("invalid id")


def fetch_ticket(conn, ticket_id):
    cur = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    return cur.fetchone()


# ---- Actions -----------------------------------------------------------

def action_open_ticket(body):
    title = body.get("title")
    priority = body.get("priority")

    if not isinstance(title, str):
        raise ApiError("title is required")
    if len(title) < 1 or len(title) > 120:
        raise ApiError("title must be 1-120 characters")

    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ApiError("priority must be an integer between 1 and 5")
    if priority < 1 or priority > 5:
        raise ApiError("priority must be between 1 and 5")

    conn = get_conn()
    with _db_lock:
        cur = conn.execute(
            "INSERT INTO tickets (title, priority, open, created_at) VALUES (?, ?, 1, ?)",
            (title, priority, now_iso()),
        )
        conn.commit()
        row = fetch_ticket(conn, cur.lastrowid)
    return row_to_dict(row)


def action_close_ticket(body):
    ticket_id = parse_id(body.get("id"))
    conn = get_conn()
    with _db_lock:
        row = fetch_ticket(conn, ticket_id)
        if row is None:
            raise ApiError("ticket not found")
        conn.execute("UPDATE tickets SET open = 0 WHERE id = ?", (ticket_id,))
        conn.commit()
        row = fetch_ticket(conn, ticket_id)
    return row_to_dict(row)


def action_reopen_ticket(body):
    ticket_id = parse_id(body.get("id"))
    conn = get_conn()
    with _db_lock:
        row = fetch_ticket(conn, ticket_id)
        if row is None:
            raise ApiError("ticket not found")
        conn.execute("UPDATE tickets SET open = 1 WHERE id = ?", (ticket_id,))
        conn.commit()
        row = fetch_ticket(conn, ticket_id)
    return row_to_dict(row)


def action_delete_ticket(body):
    ticket_id = parse_id(body.get("id"))
    conn = get_conn()
    with _db_lock:
        row = fetch_ticket(conn, ticket_id)
        if row is None:
            raise ApiError("ticket not found")
        conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        conn.commit()
    return {"ok": True}


ACTIONS = {
    "open_ticket": action_open_ticket,
    "close_ticket": action_close_ticket,
    "reopen_ticket": action_reopen_ticket,
    "delete_ticket": action_delete_ticket,
}


# ---- Queries -------------------------------------------------------------

def query_list_tickets(params):
    conn = get_conn()
    with _db_lock:
        cur = conn.execute("SELECT * FROM tickets ORDER BY id DESC")
        rows = cur.fetchall()
    return [row_to_dict(r) for r in rows]


def query_list_open(params):
    conn = get_conn()
    with _db_lock:
        cur = conn.execute(
            "SELECT * FROM tickets WHERE open = 1 ORDER BY priority DESC, id DESC"
        )
        rows = cur.fetchall()
    return [row_to_dict(r) for r in rows]


QUERIES = {
    "list_tickets": query_list_tickets,
    "list_open": query_list_open,
}


# ---- HTML UI ---------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Support Tickets</title>
<style>
  body { font-family: -apple-system, Arial, sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; color: #222; }
  h1 { font-size: 1.5rem; }
  h2 { font-size: 1.1rem; margin-top: 2rem; }
  form.open-form { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
  form.open-form input[type=text] { flex: 1; min-width: 200px; padding: 0.4rem; }
  form.open-form input[type=number] { width: 5rem; padding: 0.4rem; }
  form.open-form button { padding: 0.4rem 1rem; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; }
  th, td { text-align: left; padding: 0.4rem 0.5rem; border-bottom: 1px solid #ddd; }
  tr.closed td { color: #888; text-decoration: line-through; }
  button.action { margin-right: 0.3rem; }
  .error { color: #b00020; margin-bottom: 1rem; }
  .empty { color: #888; font-style: italic; }
</style>
</head>
<body>
<h1>Support Tickets</h1>

<div id="error" class="error" style="display:none;"></div>

<form class="open-form" id="open-form">
  <input type="text" id="title" name="title" placeholder="Ticket title" maxlength="120" required>
  <input type="number" id="priority" name="priority" min="1" max="5" value="3" required>
  <button type="submit">Open ticket</button>
</form>

<h2>Open tickets (by priority)</h2>
<div id="open-list"></div>

<h2>All tickets (newest first)</h2>
<div id="all-list"></div>

<script>
function showError(msg) {
  const el = document.getElementById('error');
  el.textContent = msg;
  el.style.display = msg ? 'block' : 'none';
}

async function api(path, options) {
  const res = await fetch(path, options);
  let data;
  try {
    data = await res.json();
  } catch (e) {
    data = null;
  }
  if (!res.ok) {
    const msg = (data && data.error) ? data.error : ('Request failed (' + res.status + ')');
    throw new Error(msg);
  }
  return data;
}

function renderTable(tickets, showAllControls) {
  if (!tickets.length) {
    return '<p class="empty">No tickets.</p>';
  }
  let rows = tickets.map(function(t) {
    const cls = t.open ? '' : ' class="closed"';
    let controls = '';
    if (t.open) {
      controls += '<button class="action" data-action="close" data-id="' + t.id + '">Close</button>';
    } else {
      controls += '<button class="action" data-action="reopen" data-id="' + t.id + '">Reopen</button>';
    }
    controls += '<button class="action" data-action="delete" data-id="' + t.id + '">Delete</button>';
    return '<tr' + cls + '>' +
      '<td>#' + t.id + '</td>' +
      '<td>' + escapeHtml(t.title) + '</td>' +
      '<td>' + t.priority + '</td>' +
      '<td>' + (t.open ? 'open' : 'closed') + '</td>' +
      '<td>' + controls + '</td>' +
      '</tr>';
  }).join('');
  return '<table><thead><tr><th>ID</th><th>Title</th><th>Priority</th><th>Status</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function(c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

async function refresh() {
  try {
    const [all, open] = await Promise.all([
      api('/api/list_tickets'),
      api('/api/list_open')
    ]);
    document.getElementById('all-list').innerHTML = renderTable(all);
    document.getElementById('open-list').innerHTML = renderTable(open);
    showError('');
  } catch (e) {
    showError(e.message);
  }
}

document.getElementById('open-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  const title = document.getElementById('title').value;
  const priority = parseInt(document.getElementById('priority').value, 10);
  try {
    await api('/api/open_ticket', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title, priority: priority })
    });
    document.getElementById('title').value = '';
    document.getElementById('priority').value = '3';
    await refresh();
  } catch (err) {
    showError(err.message);
  }
});

document.body.addEventListener('click', async function(e) {
  const btn = e.target.closest('button.action');
  if (!btn) return;
  const action = btn.getAttribute('data-action');
  const id = btn.getAttribute('data-id');
  const endpoint = action === 'close' ? 'close_ticket' : (action === 'reopen' ? 'reopen_ticket' : 'delete_ticket');
  try {
    await api('/api/' + endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id })
    });
    await refresh();
  } catch (err) {
    showError(err.message);
  }
});

refresh();
</script>
</body>
</html>
"""


# ---- HTTP server -------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "TicketsHTTP/1.0"

    def log_message(self, fmt, *args):
        pass  # keep stdout quiet

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
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
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError("invalid JSON body")
        if not isinstance(data, dict):
            raise ApiError("request body must be a JSON object")
        return data

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path

        if path == "/":
            self._send_html(200, INDEX_HTML)
            return

        if path.startswith("/api/"):
            name = path[len("/api/"):]
            if name in QUERIES:
                params = parse_qs(parts.query)
                try:
                    result = QUERIES[name](params)
                    self._send_json(200, result)
                except ApiError as e:
                    self._send_json(400, {"error": e.message})
                except Exception as e:
                    self._send_json(400, {"error": str(e)})
                return
            self._send_json(404, {"error": "unknown query"})
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parts = urlsplit(self.path)
        path = parts.path

        if path.startswith("/api/"):
            name = path[len("/api/"):]
            if name in ACTIONS:
                try:
                    body = self._read_json_body()
                    result = ACTIONS[name](body)
                    self._send_json(200, result)
                except ApiError as e:
                    self._send_json(400, {"error": e.message})
                except Exception as e:
                    self._send_json(400, {"error": str(e)})
                return
            self._send_json(404, {"error": "unknown action"})
            return

        self._send_json(404, {"error": "not found"})


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Serving on http://127.0.0.1:{PORT} (db={DB_PATH})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
