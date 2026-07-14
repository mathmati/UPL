# Task: Flashcards

Decks of flashcards with review counting.

## Data
Deck: `name` (text), plus id and creation timestamp.
Card: belongs to exactly one Deck; `front` (text), `back` (text),
`reviews` (integer, starts 0), plus id and creation timestamp.

## Actions
- `create_deck` — input `name`. Rule: name 1–60 chars. Violations → 400.
- `add_card` — inputs `deck_id`, `front`, `back`. Rules: front and back
  each 1–200 chars; the referenced deck must exist (nonexistent → 400).
- `review_card` — input `id` (card id). Increments the card's review count
  by exactly 1. Unknown id → 400.
- `delete_card` — input `id`. Unknown id → 400.
- `delete_deck` — input `id`. Deleting a deck also deletes all of its
  cards. Unknown id → 400.

## Queries
- `list_decks` — all decks, newest first.
- `cards_for_deck` — parameter `deck_id`; only that deck's cards, oldest
  first.

## UI
A page with a form to create a deck and, for each deck, its own card list
(front, back, review count), a per-deck form to add a card, and controls
to review/delete cards and delete the deck.
