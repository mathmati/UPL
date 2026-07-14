#!/usr/bin/env python3
"""Event RSVP app - Python 3 standard library only."""

import json
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT") or os.environ.get("UPL_PORT") or 8000)
DB_PATH = os.environ.get("DB_PATH") or os.environ.get("UPL_DB") or ":memory:"

_local = threading.local()
_db_lock = threading.Lock()

# For in-memory DB, we need a single shared connection across threads.
_shared_conn = None


def get_conn():
    global _shared_conn
    if DB_PATH == ":memory:":
        if _shared_conn is None:
            _shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
            _shared_conn.row_factory = sqlite3.Row
        return _shared_conn
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    conn = get_conn()
    with _db_lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS guests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                attending INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL
            )
            """
        )
        conn.commit()


def now():
    return time.time()


def event_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
    }


def guest_to_dict(row):
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "name": row["name"],
        "attending": bool(row["attending"]),
        "created_at": row["created_at"],
    }


class ApiError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def require_string(body, key, min_len=1, max_len=None):
    if key not in body:
        raise ApiError(f"missing field: {key}")
    val = body[key]
    if not isinstance(val, str):
        raise ApiError(f"field must be a string: {key}")
    if len(val) < min_len:
        raise ApiError(f"field too short: {key}")
    if max_len is not None and len(val) > max_len:
        raise ApiError(f"field too long: {key}")
    return val


def require_id(body, key):
    if key not in body:
        raise ApiError(f"missing field: {key}")
    val = body[key]
    if isinstance(val, bool):
        raise ApiError(f"field must be an id: {key}")
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            raise ApiError(f"invalid id: {key}")
    raise ApiError(f"invalid id: {key}")


# ---- Actions ----

def action_create_event(body):
    name = require_string(body, "name", 1, 100)
    conn = get_conn()
    with _db_lock:
        cur = conn.execute(
            "INSERT INTO events (name, created_at) VALUES (?, ?)",
            (name, now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM events WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return event_to_dict(row)


def action_add_guest(body):
    event_id = require_id(body, "event_id")
    name = require_string(body, "name", 1, 80)
    conn = get_conn()
    with _db_lock:
        event = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if event is None:
            raise ApiError("event does not exist")
        cur = conn.execute(
            "INSERT INTO guests (event_id, name, attending, created_at) VALUES (?, ?, 1, ?)",
            (event_id, name, now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM guests WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return guest_to_dict(row)


def action_toggle_attending(body):
    guest_id = require_id(body, "id")
    conn = get_conn()
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM guests WHERE id = ?", (guest_id,)
        ).fetchone()
        if row is None:
            raise ApiError("guest does not exist")
        new_val = 0 if row["attending"] else 1
        conn.execute(
            "UPDATE guests SET attending = ? WHERE id = ?", (new_val, guest_id)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM guests WHERE id = ?", (guest_id,)
        ).fetchone()
    return guest_to_dict(row)


def action_remove_guest(body):
    guest_id = require_id(body, "id")
    conn = get_conn()
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM guests WHERE id = ?", (guest_id,)
        ).fetchone()
        if row is None:
            raise ApiError("guest does not exist")
        conn.execute("DELETE FROM guests WHERE id = ?", (guest_id,))
        conn.commit()
    return {"ok": True}


def action_delete_event(body):
    event_id = require_id(body, "id")
    conn = get_conn()
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise ApiError("event does not exist")
        conn.execute("DELETE FROM guests WHERE event_id = ?", (event_id,))
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()
    return {"ok": True}


ACTIONS = {
    "create_event": action_create_event,
    "add_guest": action_add_guest,
    "toggle_attending": action_toggle_attending,
    "remove_guest": action_remove_guest,
    "delete_event": action_delete_event,
}


# ---- Queries ----

def query_list_events(params):
    conn = get_conn()
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY id DESC"
        ).fetchall()
    return [event_to_dict(r) for r in rows]


def query_guests_for_event(params):
    event_id_list = params.get("event_id")
    if not event_id_list:
        raise ApiError("missing parameter: event_id")
    try:
        event_id = int(event_id_list[0])
    except ValueError:
        raise ApiError("invalid parameter: event_id")
    conn = get_conn()
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM guests WHERE event_id = ? ORDER BY id ASC",
            (event_id,),
        ).fetchall()
    return [guest_to_dict(r) for r in rows]


QUERIES = {
    "list_events": query_list_events,
    "guests_for_event": query_guests_for_event,
}


HTML_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Event RSVP</title>
<style>
  body { font-family: -apple-system, Arial, sans-serif; max-width: 800px; margin: 2em auto; padding: 0 1em; color: #222; }
  h1 { font-size: 1.5em; }
  .event { border: 1px solid #ccc; border-radius: 6px; padding: 1em; margin-bottom: 1.5em; }
  .event h2 { margin-top: 0; font-size: 1.2em; }
  ul.guests { list-style: none; padding: 0; }
  ul.guests li { display: flex; align-items: center; gap: 0.5em; padding: 0.3em 0; border-bottom: 1px solid #eee; }
  ul.guests li .gname { flex: 1; }
  .not-attending { color: #999; text-decoration: line-through; }
  form.inline { display: flex; gap: 0.5em; margin-top: 0.5em; }
  input[type=text] { flex: 1; padding: 0.4em; }
  button { padding: 0.4em 0.8em; cursor: pointer; }
  .danger { color: #b00; }
  .error { color: #b00; margin: 0.5em 0; }
  #create-event-form { display: flex; gap: 0.5em; margin-bottom: 1.5em; }
</style>
</head>
<body>
<h1>Event RSVP</h1>

<form id="create-event-form">
  <input type="text" id="new-event-name" placeholder="Event name" maxlength="100" required>
  <button type="submit">Create Event</button>
</form>
<div id="global-error" class="error"></div>

<div id="events"></div>

<script>
async function api(action, body) {
  const res = await fetch('/api/' + action, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {})
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || 'request failed');
  }
  return data;
}

async function apiGet(query, params) {
  const qs = params ? ('?' + new URLSearchParams(params).toString()) : '';
  const res = await fetch('/api/' + query + qs);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || 'request failed');
  }
  return data;
}

function setError(msg) {
  document.getElementById('global-error').textContent = msg || '';
}

async function loadEvents() {
  setError('');
  let events;
  try {
    events = await apiGet('list_events');
  } catch (e) {
    setError(e.message);
    return;
  }
  const container = document.getElementById('events');
  container.innerHTML = '';
  for (const ev of events) {
    const div = document.createElement('div');
    div.className = 'event';
    div.dataset.eventId = ev.id;

    const h2 = document.createElement('h2');
    h2.textContent = ev.name;
    div.appendChild(h2);

    const delBtn = document.createElement('button');
    delBtn.textContent = 'Delete Event';
    delBtn.className = 'danger';
    delBtn.onclick = async () => {
      try {
        await api('delete_event', {id: ev.id});
        loadEvents();
      } catch (e) {
        setError(e.message);
      }
    };
    div.appendChild(delBtn);

    const ul = document.createElement('ul');
    ul.className = 'guests';
    div.appendChild(ul);

    const guests = await apiGet('guests_for_event', {event_id: ev.id});
    for (const g of guests) {
      const li = document.createElement('li');

      const nameSpan = document.createElement('span');
      nameSpan.className = 'gname' + (g.attending ? '' : ' not-attending');
      nameSpan.textContent = g.name + (g.attending ? ' (attending)' : ' (not attending)');
      li.appendChild(nameSpan);

      const toggleBtn = document.createElement('button');
      toggleBtn.textContent = 'Toggle Attending';
      toggleBtn.onclick = async () => {
        try {
          await api('toggle_attending', {id: g.id});
          loadEvents();
        } catch (e) {
          setError(e.message);
        }
      };
      li.appendChild(toggleBtn);

      const removeBtn = document.createElement('button');
      removeBtn.textContent = 'Remove';
      removeBtn.className = 'danger';
      removeBtn.onclick = async () => {
        try {
          await api('remove_guest', {id: g.id});
          loadEvents();
        } catch (e) {
          setError(e.message);
        }
      };
      li.appendChild(removeBtn);

      ul.appendChild(li);
    }

    const form = document.createElement('form');
    form.className = 'inline';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Guest name';
    input.maxLength = 80;
    input.required = true;
    const btn = document.createElement('button');
    btn.type = 'submit';
    btn.textContent = 'Add Guest';
    form.appendChild(input);
    form.appendChild(btn);
    form.onsubmit = async (evt) => {
      evt.preventDefault();
      try {
        await api('add_guest', {event_id: ev.id, name: input.value});
        input.value = '';
        loadEvents();
      } catch (e) {
        setError(e.message);
      }
    };
    div.appendChild(form);

    container.appendChild(div);
  }
}

document.getElementById('create-event-form').onsubmit = async (evt) => {
  evt.preventDefault();
  const input = document.getElementById('new-event-name');
  try {
    await api('create_event', {name: input.value});
    input.value = '';
    loadEvents();
  } catch (e) {
    setError(e.message);
  }
};

loadEvents();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "RSVP/1.0"

    def log_message(self, format, *args):
        pass  # quiet

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
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

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send_html(200, HTML_PAGE)
            return
        if path.startswith("/api/"):
            name = path[len("/api/"):]
            if name in QUERIES:
                params = parse_qs(parsed.query)
                try:
                    result = QUERIES[name](params)
                    self._send_json(200, result)
                except ApiError as e:
                    self._send_json(400, {"error": e.message})
                except Exception as e:
                    self._send_json(400, {"error": str(e)})
                return
            self._send_json(400, {"error": "unknown query: " + name})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            name = path[len("/api/"):]
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
                if not isinstance(body, dict):
                    raise ApiError("body must be a JSON object")
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid JSON body"})
                return
            except ApiError as e:
                self._send_json(400, {"error": e.message})
                return

            if name in ACTIONS:
                try:
                    result = ACTIONS[name](body)
                    self._send_json(200, result)
                except ApiError as e:
                    self._send_json(400, {"error": e.message})
                except Exception as e:
                    self._send_json(400, {"error": str(e)})
                return
            self._send_json(400, {"error": "unknown action: " + name})
            return
        self._send_json(404, {"error": "not found"})


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Serving on http://127.0.0.1:{PORT} (DB_PATH={DB_PATH})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
