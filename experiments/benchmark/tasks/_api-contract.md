# Common API contract (applies to every task)

Your app must serve this HTTP API:

- `POST /api/<action_name>` with a JSON object body holding the action's
  inputs → on success: HTTP 200 with a JSON object of the created/updated
  record (all its fields, including its id); for delete actions: `{"ok": true}`.
- Any invalid request — a validation rule broken, a missing/wrong-typed
  input, or an id that doesn't exist — must return **HTTP 400** with a JSON
  body `{"error": "<message>"}`. Never 500, never silent acceptance.
- `GET /api/<query_name>` (with query-string parameters where specified)
  → HTTP 200 with a JSON **array** of record objects, in the specified order.
- `GET /` → HTTP 200 with an HTML page for the app (a usable UI for the
  behaviors below).

Record conventions:
- Every record has an `id` (opaque — string or number, your choice) and the
  fields named in the task. Extra fields are fine.
- Boolean fields may be returned as `true`/`false` or `1`/`0`.
- "Newest first" must hold for records created in sequence (calls may be
  ~10ms apart).

Runtime requirements:
- The server must listen on the port given by the environment variable
  `PORT` (or `UPL_PORT`), defaulting to 8000, bound to 127.0.0.1.
- Persist data in SQLite at the path given by env var `DB_PATH` (or
  `UPL_DB`) if set.
- Python 3 standard library only. No pip installs.
