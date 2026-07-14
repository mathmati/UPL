# Common API + auth contract (applies to every task)

Your app is **multi-user**. It must serve this HTTP API.

## Auth (identical across all tasks)

- `POST /api/auth/signup` with JSON `{"email": "...", "password": "..."}`
  → **200** with JSON user object `{"id", "email", "role"}`, and sets a
  session cookie so the caller is now logged in.
  - The **first successful signup on a fresh database** gets the task's
    **elevated role**; every signup after that gets the task's **basic
    role**. (The two role names are given per task.)
  - Reject `email` without `@` or `password` shorter than 8 chars → **400**.
  - Reject a duplicate email → **400**.
- `POST /api/auth/login` with `{"email","password"}` → **200** + session
  cookie on success; **400** on wrong email/password.
- `POST /api/auth/logout` → **200** and clears the session cookie.
- Sessions are carried by an HTTP cookie (any cookie name). The session
  must survive a server restart (i.e. persist in the database), because the
  database is the source of truth.
- Passwords must never be returned by any endpoint.

## Actions and queries

- `POST /api/<action_name>` with a JSON object body of the action's inputs.
- `GET /api/<query_name>` (query-string params where specified) → JSON
  **array** of records.
- Records have an `id` and the fields named in the task (extra fields ok;
  never expose password data). Booleans may be `true`/`false` or `1`/`0`.
- `GET /` → **200** HTML app page.

## Permission rules (this is the core of these tasks)

- A request that is **not signed in** but hits an action/query that
  requires sign-in → **401**.
- A request that **is signed in but not permitted** (e.g. acting on
  another user's record without being an admin/elevated role) → **403**.
- Ownership: where a task says "owner only," the acting user must be the
  user who created the record; the elevated role may act regardless.
- Never silently allow a forbidden action. Never 500 on a bad request —
  use 400 (bad input / rule broken), 401 (not signed in), 403 (forbidden).

## Runtime

- Listen on `PORT` (or `MIURA_PORT`), default 8000, bound to 127.0.0.1.
- Persist to SQLite at `DB_PATH` (or `MIURA_DB`) when set.
- Python 3 standard library only.

## The v2 migration (every task has one)

Each task names a **v2 change**: exactly one new field added to one entity,
with a default. You must deliver BOTH v1 and v2, plus a way to migrate a
**populated v1 database** to v2 **without losing existing rows** (existing
rows take the new field's default). Delivery details are in your arm's
instructions.
