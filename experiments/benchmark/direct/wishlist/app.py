#!/usr/bin/env python3
"""Wishlist app: prioritized wishlist with add/mark/unmark/delete actions.

Serves a JSON API per the common API contract plus an HTML UI, using only
the Python standard library. Persists data to SQLite.
"""
import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT") or os.environ.get("UPL_PORT") or 8000)
_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "wishlist.db"
)
DB_PATH = os.environ.get("DB_PATH") or os.environ.get("UPL_DB") or _DEFAULT_DB_PATH

_db_lock = threading.Lock()
_local = threading.local()


def get_conn():
    """Return a SQLite connection for the current thread.

    Each thread gets its own connection to the same file-backed database;
    a global lock serializes all writes/reads to avoid "database is
    locked" errors under ThreadingHTTPServer.
    """
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn


def init_db():
    conn = get_conn()
    with _db_lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                priority INTEGER NOT NULL,
                purchased INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now'))
            )
            """
        )
        conn.commit()


def row_to_item(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "priority": row["priority"],
        "purchased": bool(row["purchased"]),
        "created_at": row["created_at"],
    }


class ApiError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def validate_name(name):
    if not isinstance(name, str):
        raise ApiError("name must be a string")
    if len(name) < 1 or len(name) > 100:
        raise ApiError("name must be between 1 and 100 characters")
    return name


def validate_priority(priority):
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ApiError("priority must be an integer")
    if priority < 1 or priority > 10:
        raise ApiError("priority must be between 1 and 10")
    return priority


def parse_id(raw_id):
    if isinstance(raw_id, bool):
        raise ApiError("id must be an integer")
    if isinstance(raw_id, int):
        return raw_id
    if isinstance(raw_id, str):
        try:
            return int(raw_id)
        except ValueError:
            raise ApiError("id must be an integer")
    raise ApiError("id is required")


def get_item_or_400(conn, item_id):
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise ApiError(f"no item with id {item_id}")
    return row


# ---- Actions (POST) ----

def action_add_item(body):
    if "name" not in body:
        raise ApiError("name is required")
    if "priority" not in body:
        raise ApiError("priority is required")
    name = validate_name(body["name"])
    priority = validate_priority(body["priority"])
    conn = get_conn()
    with _db_lock:
        cur = conn.execute(
            "INSERT INTO items (name, priority, purchased) VALUES (?, ?, 0)",
            (name, priority),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM items WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return row_to_item(row)


def action_mark_purchased(body):
    if "id" not in body:
        raise ApiError("id is required")
    item_id = parse_id(body["id"])
    conn = get_conn()
    with _db_lock:
        get_item_or_400(conn, item_id)
        conn.execute("UPDATE items SET purchased = 1 WHERE id = ?", (item_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return row_to_item(row)


def action_unmark_purchased(body):
    if "id" not in body:
        raise ApiError("id is required")
    item_id = parse_id(body["id"])
    conn = get_conn()
    with _db_lock:
        get_item_or_400(conn, item_id)
        conn.execute("UPDATE items SET purchased = 0 WHERE id = ?", (item_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return row_to_item(row)


def action_delete_item(body):
    if "id" not in body:
        raise ApiError("id is required")
    item_id = parse_id(body["id"])
    conn = get_conn()
    with _db_lock:
        get_item_or_400(conn, item_id)
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()
    return {"ok": True}


ACTIONS = {
    "add_item": action_add_item,
    "mark_purchased": action_mark_purchased,
    "unmark_purchased": action_unmark_purchased,
    "delete_item": action_delete_item,
}


# ---- Queries (GET) ----

def query_list_items(params):
    conn = get_conn()
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM items ORDER BY priority DESC, id DESC"
        ).fetchall()
    return [row_to_item(r) for r in rows]


def query_list_unpurchased(params):
    conn = get_conn()
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM items WHERE purchased = 0 ORDER BY priority DESC, id DESC"
        ).fetchall()
    return [row_to_item(r) for r in rows]


QUERIES = {
    "list_items": query_list_items,
    "list_unpurchased": query_list_unpurchased,
}


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wishlist</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 700px; margin: 2rem auto; padding: 0 1rem; color: #222; }
  h1 { margin-bottom: 0.2rem; }
  h2 { margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: 0.3rem; }
  form.add-form { display: flex; gap: 0.5rem; margin: 1rem 0; flex-wrap: wrap; }
  form.add-form input[type=text] { flex: 1; min-width: 150px; padding: 0.4rem; }
  form.add-form input[type=number] { width: 5rem; padding: 0.4rem; }
  form.add-form button { padding: 0.4rem 1rem; }
  ul.item-list { list-style: none; padding: 0; }
  ul.item-list li { display: flex; align-items: center; gap: 0.6rem; padding: 0.4rem 0; border-bottom: 1px solid #eee; }
  .item-name { flex: 1; }
  .item-name.purchased { text-decoration: line-through; color: #999; }
  .priority-badge { background: #eef; color: #335; border-radius: 4px; padding: 0.1rem 0.5rem; font-size: 0.85rem; }
  .error { color: #b00020; margin: 0.5rem 0; min-height: 1.2rem; }
  button.small { padding: 0.2rem 0.6rem; cursor: pointer; }
  button.delete { background: #fde; border: 1px solid #c99; color: #900; }
</style>
</head>
<body>
<h1>Wishlist</h1>
<p class="error" id="error"></p>

<form class="add-form" id="add-form">
  <input type="text" id="name" placeholder="Item name" maxlength="100" required>
  <input type="number" id="priority" placeholder="Priority (1-10)" min="1" max="10" required>
  <button type="submit">Add item</button>
</form>

<h2>Still to buy</h2>
<ul class="item-list" id="unpurchased-list"></ul>

<h2>All items</h2>
<ul class="item-list" id="all-list"></ul>

<script>
async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || ('Request failed: ' + res.status));
  }
  return data;
}

function setError(msg) {
  document.getElementById('error').textContent = msg || '';
}

function renderItem(item, list, showPriority) {
  const li = document.createElement('li');

  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = !!item.purchased;
  cb.addEventListener('change', async () => {
    setError('');
    try {
      if (cb.checked) {
        await api('/api/mark_purchased', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({id: item.id})
        });
      } else {
        await api('/api/unmark_purchased', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({id: item.id})
        });
      }
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  });
  li.appendChild(cb);

  const name = document.createElement('span');
  name.className = 'item-name' + (item.purchased ? ' purchased' : '');
  name.textContent = item.name;
  li.appendChild(name);

  const badge = document.createElement('span');
  badge.className = 'priority-badge';
  badge.textContent = 'P' + item.priority;
  li.appendChild(badge);

  const del = document.createElement('button');
  del.className = 'small delete';
  del.textContent = 'Delete';
  del.addEventListener('click', async () => {
    setError('');
    try {
      await api('/api/delete_item', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: item.id})
      });
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  });
  li.appendChild(del);

  list.appendChild(li);
}

async function refresh() {
  setError('');
  let all = [], unpurchased = [];
  try {
    all = await api('/api/list_items');
    unpurchased = await api('/api/list_unpurchased');
  } catch (e) {
    setError(e.message);
    return;
  }
  const allList = document.getElementById('all-list');
  const unpurchasedList = document.getElementById('unpurchased-list');
  allList.innerHTML = '';
  unpurchasedList.innerHTML = '';
  if (all.length === 0) {
    allList.innerHTML = '<li>No items yet.</li>';
  }
  if (unpurchased.length === 0) {
    unpurchasedList.innerHTML = '<li>Nothing left to buy.</li>';
  }
  all.forEach(item => renderItem(item, allList));
  unpurchased.forEach(item => renderItem(item, unpurchasedList));
}

document.getElementById('add-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  setError('');
  const nameEl = document.getElementById('name');
  const priorityEl = document.getElementById('priority');
  const name = nameEl.value;
  const priority = parseInt(priorityEl.value, 10);
  try {
    await api('/api/add_item', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name, priority: priority})
    });
    nameEl.value = '';
    priorityEl.value = '';
    await refresh();
  } catch (e) {
    setError(e.message);
  }
});

refresh();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "WishlistHTTP/1.0"

    def log_message(self, format, *args):
        pass  # keep stdout quiet

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
            self._send_json(400, {"error": f"unknown query {name}"})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            name = path[len("/api/"):]
            if name in ACTIONS:
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    if raw:
                        body = json.loads(raw.decode("utf-8"))
                    else:
                        body = {}
                    if not isinstance(body, dict):
                        raise ApiError("request body must be a JSON object")
                except ApiError:
                    raise
                except Exception:
                    self._send_json(400, {"error": "invalid JSON body"})
                    return
                try:
                    result = ACTIONS[name](body)
                    self._send_json(200, result)
                except ApiError as e:
                    self._send_json(400, {"error": e.message})
                except Exception as e:
                    self._send_json(400, {"error": str(e)})
                return
            self._send_json(400, {"error": f"unknown action {name}"})
            return
        self._send_json(404, {"error": "not found"})


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Wishlist app listening on http://127.0.0.1:{PORT} (db={DB_PATH})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
