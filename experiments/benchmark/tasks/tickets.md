# Task: Support tickets

A tiny support-ticket tracker.

## Data
Ticket: `title` (text), `priority` (integer), `open` (boolean, starts true),
plus id and a creation timestamp.

## Actions
- `open_ticket` — inputs `title`, `priority`. Rules: title 1–120 chars;
  priority must be between 1 and 5 inclusive. Violations → 400.
- `close_ticket` — input `id`. After it, the ticket's open flag must be
  false. Unknown id → 400.
- `reopen_ticket` — input `id`. After it, open must be true. Unknown id → 400.
- `delete_ticket` — input `id`. Unknown id → 400.

## Queries
- `list_tickets` — all tickets, newest first.
- `list_open` — only tickets with open = true, highest priority first.

## UI
A page with a form to open a ticket, the full ticket list with
close/reopen and delete controls, and an "Open tickets" section showing
the open ones by priority.
