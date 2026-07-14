# Task: Bookmarks manager

A personal bookmarks manager.

## Data
Bookmark: `title` (text), `url` (text), `favorite` (boolean, starts false),
plus id and a creation timestamp.

## Actions
- `add_bookmark` — inputs `title`, `url`. Rules: title must be 1–100
  characters; url must be 8–500 characters. Violations → 400.
- `toggle_favorite` — input `id`. Flips the favorite flag. Unknown id → 400.
- `delete_bookmark` — input `id`. Unknown id → 400.

## Queries
- `list_bookmarks` — all bookmarks, newest first.
- `list_favorites` — only bookmarks with favorite = true, newest first.

## UI
A page with a form to add a bookmark, and the bookmark list with a
favorite toggle and a delete button per row.
