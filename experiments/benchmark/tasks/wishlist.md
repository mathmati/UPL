# Task: Wishlist

A prioritized wishlist.

## Data
Item: `name` (text), `priority` (integer), `purchased` (boolean, starts
false), plus id and creation timestamp.

## Actions
- `add_item` — inputs `name`, `priority`. Rules: name 1–100 chars;
  priority between 1 and 10 inclusive. Violations → 400.
- `mark_purchased` — input `id`. After it, purchased must be true.
  Unknown id → 400.
- `unmark_purchased` — input `id`. After it, purchased must be false.
  Unknown id → 400.
- `delete_item` — input `id`. Unknown id → 400.

## Queries
- `list_items` — all items, highest priority first.
- `list_unpurchased` — only items with purchased = false, highest
  priority first.

## UI
A page with a form to add an item, the full list with purchase toggles
and delete buttons, and a "Still to buy" section showing unpurchased
items by priority.
