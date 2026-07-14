# Task: Expense claims

A team expense-claim tracker.

## Roles
- elevated role: `manager`
- basic role: `staff`

## Data
Claim: `reference` (text, **unique**, 3–40 chars), `amount` (int, must be
between 1 and 1000000 inclusive), `approved` (bool, starts false), plus id,
an owner (the user who submitted it), and a creation timestamp.

## Actions
- `submit_claim` — inputs `reference`, `amount`. Any signed-in user; owned
  by the caller. Duplicate reference → 400; amount out of range → 400.
- `approve_claim` — input `id`. **Manager role only** (not the owner unless
  they are a manager). Sets approved = true; after it, approved must be
  true. Unknown id → 400; non-manager → 403.
- `withdraw_claim` — input `id`. **Owner only** (managers may also withdraw
  any). Deletes the claim. Unknown id → 400.

## Queries
- `all_claims` — signed-in only; all claims, newest first.
- `my_claims` — signed-in only; only the caller's own, newest first.

## UI
A page with a submit form and the claim lists with approve/withdraw
controls.

## v2 change
Add field `category` (text, default `"general"`) to Claim.
