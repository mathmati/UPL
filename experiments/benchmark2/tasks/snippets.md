# Task: Snippet locker

A shared code-snippet locker.

## Roles
- elevated role: `admin`
- basic role: `member`

## Data
Snippet: `title` (text, **unique** across all snippets, 1–80 chars),
`body` (text, 1–4000 chars), plus id, an owner (the user who created it),
and a creation timestamp.

## Actions
- `save_snippet` — inputs `title`, `body`. Any signed-in user. The snippet
  is owned by the caller. Duplicate title → 400; length violations → 400.
- `edit_snippet` — inputs `id`, `body`. **Owner only.** Sets a new body
  (same length rule). Unknown id → 400; not owner (and not admin) → 403.
- `delete_snippet` — input `id`. **Owner, or an admin.** Unknown id → 400.

## Queries
- `all_snippets` — signed-in only; all snippets, newest first.
- `my_snippets` — signed-in only; only the caller's own snippets, newest
  first.

## UI
A page with a save form and the snippet lists with edit/delete controls.

## v2 change
Add field `language` (text, default `"text"`) to Snippet.
