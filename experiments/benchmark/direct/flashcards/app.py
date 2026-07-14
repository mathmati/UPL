#!/usr/bin/env python3
"""Flashcards app: decks of flashcards with review counting.

Python 3 standard library only. Serves a JSON API per the shared
API contract plus a small HTML UI.
"""

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
_conn = None


def get_conn():
    # A single shared connection guarded by _db_lock everywhere it is used.
    # (Required because ":memory:" databases are per-connection, and
    # thread-local connections would otherwise see empty/divergent data.)
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        if DB_PATH != ":memory:":
            _conn.execute("PRAGMA journal_mode=WAL")
    return _conn


def init_db():
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS decks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id INTEGER NOT NULL,
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            reviews INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        )
        """
    )
    conn.commit()


class ApiError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def deck_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
    }


def card_to_dict(row):
    return {
        "id": row["id"],
        "deck_id": row["deck_id"],
        "front": row["front"],
        "back": row["back"],
        "reviews": row["reviews"],
        "created_at": row["created_at"],
    }


def require_str(body, key):
    if key not in body or not isinstance(body[key], str):
        raise ApiError(f"'{key}' must be a string")
    return body[key]


def require_id(body, key):
    val = body.get(key)
    if isinstance(val, bool) or not isinstance(val, (int, float, str)):
        raise ApiError(f"'{key}' must be an id")
    if isinstance(val, str):
        try:
            val = int(val)
        except ValueError:
            raise ApiError(f"'{key}' must be an id")
    if isinstance(val, float):
        if not val.is_integer():
            raise ApiError(f"'{key}' must be an id")
        val = int(val)
    return val


# ---- Actions ----

def action_create_deck(body):
    name = require_str(body, "name")
    if not (1 <= len(name) <= 60):
        raise ApiError("name must be 1-60 characters")
    conn = get_conn()
    with _db_lock:
        now = time.time()
        cur = conn.execute(
            "INSERT INTO decks (name, created_at) VALUES (?, ?)", (name, now)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM decks WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return deck_to_dict(row)


def action_add_card(body):
    deck_id = require_id(body, "deck_id")
    front = require_str(body, "front")
    back = require_str(body, "back")
    if not (1 <= len(front) <= 200):
        raise ApiError("front must be 1-200 characters")
    if not (1 <= len(back) <= 200):
        raise ApiError("back must be 1-200 characters")
    conn = get_conn()
    with _db_lock:
        deck = conn.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
        if deck is None:
            raise ApiError("deck_id does not exist")
        now = time.time()
        cur = conn.execute(
            "INSERT INTO cards (deck_id, front, back, reviews, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (deck_id, front, back, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM cards WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return card_to_dict(row)


def action_review_card(body):
    card_id = require_id(body, "id")
    conn = get_conn()
    with _db_lock:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise ApiError("id does not exist")
        conn.execute(
            "UPDATE cards SET reviews = reviews + 1 WHERE id = ?", (card_id,)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return card_to_dict(row)


def action_delete_card(body):
    card_id = require_id(body, "id")
    conn = get_conn()
    with _db_lock:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise ApiError("id does not exist")
        conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        conn.commit()
    return {"ok": True}


def action_delete_deck(body):
    deck_id = require_id(body, "id")
    conn = get_conn()
    with _db_lock:
        row = conn.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
        if row is None:
            raise ApiError("id does not exist")
        conn.execute("DELETE FROM cards WHERE deck_id = ?", (deck_id,))
        conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        conn.commit()
    return {"ok": True}


ACTIONS = {
    "create_deck": action_create_deck,
    "add_card": action_add_card,
    "review_card": action_review_card,
    "delete_card": action_delete_card,
    "delete_deck": action_delete_deck,
}


# ---- Queries ----

def query_list_decks(params):
    conn = get_conn()
    with _db_lock:
        rows = conn.execute("SELECT * FROM decks ORDER BY id DESC").fetchall()
    return [deck_to_dict(r) for r in rows]


def query_cards_for_deck(params):
    deck_id_list = params.get("deck_id")
    if not deck_id_list:
        raise ApiError("deck_id is required")
    try:
        deck_id = int(deck_id_list[0])
    except ValueError:
        raise ApiError("deck_id must be an id")
    conn = get_conn()
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM cards WHERE deck_id = ? ORDER BY id ASC", (deck_id,)
        ).fetchall()
    return [card_to_dict(r) for r in rows]


QUERIES = {
    "list_decks": query_list_decks,
    "cards_for_deck": query_cards_for_deck,
}


HTML_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Flashcards</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 800px; margin: 2em auto; padding: 0 1em; color: #222; }
  h1 { margin-bottom: 0.2em; }
  .deck { border: 1px solid #ccc; border-radius: 8px; padding: 1em; margin-bottom: 1.5em; }
  .deck h2 { margin-top: 0; }
  .card { border-bottom: 1px solid #eee; padding: 0.5em 0; display: flex; justify-content: space-between; align-items: center; gap: 1em; }
  .card:last-child { border-bottom: none; }
  .card .content { flex: 1; }
  .card .front { font-weight: bold; }
  .card .back { color: #555; }
  .card .reviews { font-size: 0.85em; color: #888; }
  button { cursor: pointer; }
  form.inline { display: flex; gap: 0.5em; margin-top: 0.8em; flex-wrap: wrap; }
  input[type=text] { padding: 0.3em; }
  .error { color: #b00020; margin: 0.5em 0; }
  #create-deck-form { margin-bottom: 2em; display: flex; gap: 0.5em; }
</style>
</head>
<body>
<h1>Flashcards</h1>

<form id="create-deck-form">
  <input type="text" id="new-deck-name" placeholder="New deck name" maxlength="60" required>
  <button type="submit">Create deck</button>
</form>
<div id="global-error" class="error"></div>

<div id="decks"></div>

<script>
async function api(path, opts) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) {
    const msg = (data && data.error) ? data.error : ('Request failed: ' + res.status);
    throw new Error(msg);
  }
  return data;
}

function el(tag, attrs, children) {
  const e = document.createElement(tag);
  if (attrs) for (const k in attrs) {
    if (k === 'text') e.textContent = attrs[k];
    else e.setAttribute(k, attrs[k]);
  }
  (children || []).forEach(c => e.appendChild(c));
  return e;
}

async function loadDecks() {
  document.getElementById('global-error').textContent = '';
  let decks;
  try {
    decks = await api('/api/list_decks');
  } catch (e) {
    document.getElementById('global-error').textContent = e.message;
    return;
  }
  const container = document.getElementById('decks');
  container.innerHTML = '';
  for (const deck of decks) {
    container.appendChild(await renderDeck(deck));
  }
}

async function renderDeck(deck) {
  const wrap = el('div', {class: 'deck', 'data-deck-id': deck.id});
  wrap.appendChild(el('h2', {text: deck.name}));

  const deleteDeckBtn = el('button', {text: 'Delete deck'});
  deleteDeckBtn.onclick = async () => {
    try {
      await api('/api/delete_deck', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: deck.id})
      });
      loadDecks();
    } catch (e) { showDeckError(wrap, e.message); }
  };
  wrap.appendChild(deleteDeckBtn);

  const cardsDiv = el('div', {class: 'cards'});
  wrap.appendChild(cardsDiv);

  let cards = [];
  try {
    cards = await api('/api/cards_for_deck?deck_id=' + encodeURIComponent(deck.id));
  } catch (e) {
    showDeckError(wrap, e.message);
  }
  for (const card of cards) {
    cardsDiv.appendChild(renderCard(card, wrap));
  }

  const form = el('form', {class: 'inline'});
  const frontInput = el('input', {type: 'text', placeholder: 'Front', maxlength: '200', required: 'required'});
  const backInput = el('input', {type: 'text', placeholder: 'Back', maxlength: '200', required: 'required'});
  const addBtn = el('button', {type: 'submit', text: 'Add card'});
  form.appendChild(frontInput);
  form.appendChild(backInput);
  form.appendChild(addBtn);
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api('/api/add_card', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({deck_id: deck.id, front: frontInput.value, back: backInput.value})
      });
      loadDecks();
    } catch (e) { showDeckError(wrap, e.message); }
  };
  wrap.appendChild(form);

  const errDiv = el('div', {class: 'error'});
  wrap.appendChild(errDiv);

  return wrap;
}

function showDeckError(deckEl, msg) {
  const err = deckEl.querySelector('.error');
  if (err) err.textContent = msg;
}

function renderCard(card, deckEl) {
  const row = el('div', {class: 'card', 'data-card-id': card.id});
  const content = el('div', {class: 'content'});
  content.appendChild(el('div', {class: 'front', text: card.front}));
  content.appendChild(el('div', {class: 'back', text: card.back}));
  content.appendChild(el('div', {class: 'reviews', text: 'Reviews: ' + card.reviews}));
  row.appendChild(content);

  const reviewBtn = el('button', {text: 'Review'});
  reviewBtn.onclick = async () => {
    try {
      await api('/api/review_card', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: card.id})
      });
      loadDecks();
    } catch (e) { showDeckError(deckEl, e.message); }
  };
  row.appendChild(reviewBtn);

  const deleteBtn = el('button', {text: 'Delete'});
  deleteBtn.onclick = async () => {
    try {
      await api('/api/delete_card', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: card.id})
      });
      loadDecks();
    } catch (e) { showDeckError(deckEl, e.message); }
  };
  row.appendChild(deleteBtn);

  return row;
}

document.getElementById('create-deck-form').onsubmit = async (ev) => {
  ev.preventDefault();
  const nameInput = document.getElementById('new-deck-name');
  document.getElementById('global-error').textContent = '';
  try {
    await api('/api/create_deck', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: nameInput.value})
    });
    nameInput.value = '';
    loadDecks();
  } catch (e) {
    document.getElementById('global-error').textContent = e.message;
  }
};

loadDecks();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "FlashcardsHTTP/1.0"

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
        if parsed.path == "/":
            self._send_html(200, HTML_PAGE)
            return
        if parsed.path.startswith("/api/"):
            name = parsed.path[len("/api/"):]
            params = parse_qs(parsed.query)
            handler = QUERIES.get(name)
            if handler is None:
                self._send_json(400, {"error": f"unknown query '{name}'"})
                return
            try:
                result = handler(params)
                self._send_json(200, result)
            except ApiError as e:
                self._send_json(400, {"error": e.message})
            except Exception as e:
                self._send_json(400, {"error": str(e)})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._send_json(404, {"error": "not found"})
            return
        name = parsed.path[len("/api/"):]
        handler = ACTIONS.get(name)
        if handler is None:
            self._send_json(400, {"error": f"unknown action '{name}'"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            body = json.loads(raw) if raw else {}
            if not isinstance(body, dict):
                raise ApiError("request body must be a JSON object")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body"})
            return
        except ApiError as e:
            self._send_json(400, {"error": e.message})
            return
        try:
            result = handler(body)
            self._send_json(200, result)
        except ApiError as e:
            self._send_json(400, {"error": e.message})
        except Exception as e:
            self._send_json(400, {"error": str(e)})


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Serving flashcards app on http://127.0.0.1:{PORT} (db={DB_PATH})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
