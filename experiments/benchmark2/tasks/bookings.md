# Task: Room bookings

A shared meeting-room booking board.

## Roles
- elevated role: `admin`
- basic role: `member`

## Data
Booking: `slot` (text, **unique** across all bookings, 3–40 chars — encodes
room+time), `purpose` (text, 1–120 chars), plus id, an owner (the user who
booked it), and a creation timestamp.

## Actions
- `book` — inputs `slot`, `purpose`. Any signed-in user; owned by the
  caller. Duplicate slot → 400 (the slot is taken); length violations → 400.
- `change_purpose` — inputs `id`, `purpose`. **Owner only.** Unknown id →
  400; not owner (and not admin) → 403.
- `cancel` — input `id`. **Owner, or an admin.** Deletes the booking.
  Unknown id → 400.

## Queries
- `all_bookings` — signed-in only; all bookings, newest first.
- `my_bookings` — signed-in only; only the caller's own, newest first.

## UI
A page with a booking form and the booking lists with change/cancel
controls.

## v2 change
Add field `attendees` (int, default `1`) to Booking.
