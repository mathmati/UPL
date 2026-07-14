# Task: Event RSVP

Events with per-event guest lists.

## Data
Event: `name` (text), plus id and creation timestamp.
Guest: belongs to exactly one Event; `name` (text), `attending` (boolean,
starts true), plus id and creation timestamp.

## Actions
- `create_event` — input `name`. Rule: name 1–100 chars. Violations → 400.
- `add_guest` — inputs `event_id`, `name`. Rules: name 1–80 chars; the
  referenced event must exist (adding a guest to a nonexistent event → 400).
- `toggle_attending` — input `id` (guest id). Flips attending. Unknown → 400.
- `remove_guest` — input `id` (guest id). Unknown id → 400.
- `delete_event` — input `id` (event id). Deleting an event also deletes
  all of its guests. Unknown id → 400.

## Queries
- `list_events` — all events, newest first.
- `guests_for_event` — parameter `event_id`; only that event's guests,
  oldest first.

## UI
A page with a form to create an event and, for each event, its own guest
list, a per-event form to add a guest, and controls to toggle attending /
remove guests / delete the event.
