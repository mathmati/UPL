# Task: Shared docs

A shared document index.

## Roles
- elevated role: `editor`
- basic role: `author`

## Data
Doc: `slug` (text, **unique**, 3–50 chars), `title` (text, 1–150 chars),
plus id, an owner (the user who created it), and a creation timestamp.

## Actions
- `create_doc` — inputs `slug`, `title`. Any signed-in user; owned by the
  caller. Duplicate slug → 400; length violations → 400.
- `rename_doc` — inputs `id`, `title`. **Owner only.** Unknown id → 400;
  not owner (and not an editor) → 403.
- `delete_doc` — input `id`. **Owner, or an editor.** Unknown id → 400.

## Queries
- `all_docs` — signed-in only; all docs, newest first.
- `my_docs` — signed-in only; only the caller's own, newest first.

## UI
A page with a create form and the doc lists with rename/delete controls.

## v2 change
Add field `archived` (bool, default `false`) to Doc.
