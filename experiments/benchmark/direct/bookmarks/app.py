#!/usr/bin/env python3
"""Bookmarks manager - single-file stdlib-only Python app."""

import json
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT") or os.environ.get("UPL_PORT") or 8000)
DB_PATH = os.environ.get("DB_PATH") or os.environ.get("UPL_DB") or ":memory:"

_db_lock = threading.Lock()
_CONN = None


def get_conn():
    # A single shared connection guarded by _db_lock everywhere it's used.
    # (Important: with DB_PATH=":memory:" each new connection would be an
    # independent, empty database, so we must not open one per thread.)
    return _CONN


def init_db():
    global _CONN
    _CONN = sqlite3.connect(DB_PATH, check_same_thread=False)
    _CONN.row_factory = sqlite3.Row
    _CONN.execute(
        """
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            favorite INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        )
        """
    )
    _CONN.commit()


def row_to_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "url": row["url"],
        "favorite": bool(row["favorite"]),
        "created_at": row["created_at"],
    }


class ApiError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def action_add_bookmark(payload):
    title = payload.get("title")
    url = payload.get("url")

    if not isinstance(title, str):
        raise ApiError("title is required and must be a string")
    if not isinstance(url, str):
        raise ApiError("url is required and must be a string")
    if not (1 <= len(title) <= 100):
        raise ApiError("title must be 1-100 characters")
    if not (8 <= len(url) <= 500):
        raise ApiError("url must be 8-500 characters")

    with _db_lock:
        conn = get_conn()
        now = time.time()
        cur = conn.execute(
            "INSERT INTO bookmarks (title, url, favorite, created_at) VALUES (?, ?, 0, ?)",
            (title, url, now),
        )
        conn.commit()
        new_id = cur.lastrowid
        row = conn.execute("SELECT * FROM bookmarks WHERE id = ?", (new_id,)).fetchone()
    return row_to_dict(row)


def _get_id(payload):
    if "id" not in payload:
        raise ApiError("id is required")
    raw_id = payload.get("id")
    if isinstance(raw_id, bool):
        raise ApiError("id must be an integer")
    if isinstance(raw_id, int):
        return raw_id
    if isinstance(raw_id, str):
        try:
            return int(raw_id)
        except ValueError:
            raise ApiError("id must be an integer")
    raise ApiError("id must be an integer")


def action_toggle_favorite(payload):
    bid = _get_id(payload)
    with _db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM bookmarks WHERE id = ?", (bid,)).fetchone()
        if row is None:
            raise ApiError("bookmark not found")
        new_val = 0 if row["favorite"] else 1
        conn.execute("UPDATE bookmarks SET favorite = ? WHERE id = ?", (new_val, bid))
        conn.commit()
        row = conn.execute("SELECT * FROM bookmarks WHERE id = ?", (bid,)).fetchone()
    return row_to_dict(row)


def action_delete_bookmark(payload):
    bid = _get_id(payload)
    with _db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM bookmarks WHERE id = ?", (bid,)).fetchone()
        if row is None:
            raise ApiError("bookmark not found")
        conn.execute("DELETE FROM bookmarks WHERE id = ?", (bid,))
        conn.commit()
    return {"ok": True}


def query_list_bookmarks(params):
    with _db_lock:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM bookmarks ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def query_list_favorites(params):
    with _db_lock:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM bookmarks WHERE favorite = 1 ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [row_to_dict(r) for r in rows]


ACTIONS = {
    "add_bookmark": action_add_bookmark,
    "toggle_favorite": action_toggle_favorite,
    "delete_bookmark": action_delete_bookmark,
}

QUERIES = {
    "list_bookmarks": query_list_bookmarks,
    "list_favorites": query_list_favorites,
}


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bookmarks</title>
<style>
  :root {
    color-scheme: light dark;
  }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    max-width: 720px;
    margin: 2rem auto;
    padding: 0 1rem;
    line-height: 1.4;
  }
  h1 { font-size: 1.5rem; }
  form {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 1.5rem;
  }
  form input[type=text] {
    flex: 1 1 200px;
    padding: 0.4rem 0.6rem;
  }
  form button {
    padding: 0.4rem 1rem;
    cursor: pointer;
  }
  #error {
    color: #b00020;
    margin-bottom: 1rem;
    min-height: 1.2em;
  }
  ul#list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  li.bookmark {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid #8884;
  }
  li.bookmark .info {
    flex: 1;
    min-width: 0;
  }
  li.bookmark .title {
    font-weight: 600;
  }
  li.bookmark .url {
    font-size: 0.85rem;
    opacity: 0.75;
    word-break: break-all;
  }
  button.fav {
    background: none;
    border: 1px solid #8888;
    border-radius: 4px;
    cursor: pointer;
    font-size: 1.1rem;
    padding: 0.2rem 0.5rem;
  }
  button.fav.active {
    color: #d4a017;
    border-color: #d4a017;
  }
  button.del {
    background: none;
    border: 1px solid #b00020;
    color: #b00020;
    border-radius: 4px;
    cursor: pointer;
    padding: 0.2rem 0.6rem;
  }
  .filters {
    margin-bottom: 1rem;
  }
  .filters button {
    margin-right: 0.5rem;
    padding: 0.3rem 0.8rem;
    cursor: pointer;
  }
  .filters button.active {
    font-weight: bold;
    text-decoration: underline;
  }
</style>
</head>
<body>
<h1>Bookmarks</h1>

<form id="add-form">
  <input type="text" id="title" placeholder="Title" maxlength="100" required>
  <input type="text" id="url" placeholder="https://example.com" maxlength="500" required>
  <button type="submit">Add bookmark</button>
</form>

<div id="error"></div>

<div class="filters">
  <button id="show-all" class="active">All</button>
  <button id="show-favorites">Favorites</button>
</div>

<ul id="list"></ul>

<script>
let currentFilter = 'all';

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

async function api(path, opts) {
  const res = await fetch(path, opts);
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

function showError(msg) {
  document.getElementById('error').textContent = msg || '';
}

async function refresh() {
  showError('');
  const path = currentFilter === 'favorites' ? '/api/list_favorites' : '/api/list_bookmarks';
  let items;
  try {
    items = await api(path);
  } catch (e) {
    showError(e.message);
    return;
  }
  const list = document.getElementById('list');
  list.innerHTML = '';
  for (const b of items) {
    const li = document.createElement('li');
    li.className = 'bookmark';

    const info = document.createElement('div');
    info.className = 'info';
    const titleDiv = document.createElement('div');
    titleDiv.className = 'title';
    titleDiv.textContent = b.title;
    const urlDiv = document.createElement('div');
    urlDiv.className = 'url';
    const a = document.createElement('a');
    a.href = b.url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = b.url;
    urlDiv.appendChild(a);
    info.appendChild(titleDiv);
    info.appendChild(urlDiv);

    const favBtn = document.createElement('button');
    favBtn.className = 'fav' + (b.favorite ? ' active' : '');
    favBtn.textContent = b.favorite ? '★' : '☆';
    favBtn.title = 'Toggle favorite';
    favBtn.onclick = async () => {
      try {
        await api('/api/toggle_favorite', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({id: b.id})
        });
        refresh();
      } catch (e) {
        showError(e.message);
      }
    };

    const delBtn = document.createElement('button');
    delBtn.className = 'del';
    delBtn.textContent = 'Delete';
    delBtn.onclick = async () => {
      try {
        await api('/api/delete_bookmark', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({id: b.id})
        });
        refresh();
      } catch (e) {
        showError(e.message);
      }
    };

    li.appendChild(info);
    li.appendChild(favBtn);
    li.appendChild(delBtn);
    list.appendChild(li);
  }
}

document.getElementById('add-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  showError('');
  const title = document.getElementById('title').value;
  const url = document.getElementById('url').value;
  try {
    await api('/api/add_bookmark', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title, url})
    });
    document.getElementById('title').value = '';
    document.getElementById('url').value = '';
    refresh();
  } catch (e) {
    showError(e.message);
  }
});

document.getElementById('show-all').addEventListener('click', () => {
  currentFilter = 'all';
  document.getElementById('show-all').classList.add('active');
  document.getElementById('show-favorites').classList.remove('active');
  refresh();
});

document.getElementById('show-favorites').addEventListener('click', () => {
  currentFilter = 'favorites';
  document.getElementById('show-favorites').classList.add('active');
  document.getElementById('show-all').classList.remove('active');
  refresh();
});

refresh();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "BookmarksHTTP/1.0"

    def log_message(self, format, *args):
        pass

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
            else:
                self._send_json(400, {"error": "unknown query"})
                return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not path.startswith("/api/"):
            self._send_json(404, {"error": "not found"})
            return

        name = path[len("/api/"):]
        if name not in ACTIONS:
            self._send_json(400, {"error": "unknown action"})
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length > 0 else b""

        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            if not isinstance(payload, dict):
                raise ValueError("body must be a JSON object")
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "invalid JSON body"})
            return

        try:
            result = ACTIONS[name](payload)
            self._send_json(200, result)
        except ApiError as e:
            self._send_json(400, {"error": e.message})
        except Exception as e:
            self._send_json(400, {"error": str(e)})


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Bookmarks app listening on http://127.0.0.1:{PORT} (db={DB_PATH})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
