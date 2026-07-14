# Miura v1 Roadmap — the reliability layer

## Positioning

The head-to-head benchmark ([`experiments/2026-07-14-head-to-head.md`](experiments/2026-07-14-head-to-head.md))
established that at small scale, direct LLM codegen matches Miura on
correctness. So Miura does not compete on app generation broadly. It owns
the stratum of software where **a bug is a real loss** — lost records,
wrong balances, leaked data, broken permissions — which is also the
stratum that is schematic enough to carry contracts. High-variance
creative work (design, marketing sites) goes to direct generation;
invariant-holding work goes to Miura; an HTTP seam joins them.

**Vibes from the vibe tool, reliability from Miura.**

Strategy: eat everything that must not break first; expand outward later.

- **Tier 1 (v1 owns):** internal tools and registries — intake forms,
  approvals, inventories, waitlists, trackers. Highest breakage cost per
  line, most schematic, least styled.
- **Tier 1.5 (v1 stretch):** turn-based games and game backends. Game
  rules are state machines with guarded transitions — the same shape as
  approval workflows — and game economies (inventories, currencies,
  leaderboards) are the money tier wearing a hat (the classic
  catastrophic game bug is item duplication, i.e. a transactions
  failure). Determinism is a feature here: server-authoritative rules,
  fair play, auditable replays. Real-time action games (frame loops,
  physics, rendering) stay out — engine/vibes tier, seam-joined.
- **Tier 2 (v1 stretch):** customer-facing accounts — bookings, orders,
  memberships.
- **Tier 3 (v2):** content/marketing via a theme dialect; the official v1
  answer for fancy front-ends is the hybrid pattern (styled shell posts to
  a Miura backend).

## The v1 feature cut (build order)

| # | Feature | Must-not-break it covers | Shape |
|---|---------|--------------------------|-------|
| 1 | **Auth & permissions** | leaked data, missing access checks — the canonical vibe-coding failure | `User` identities + sessions; `(allow action (signed-in) / (role admin) / (owner))`; `(field owner (ref User) (auto @user))`; row-scoped queries `(where (= owner @user))`. Permissions compile into every target and are testable in bundle tests. |
| 2 | **`(unique)` field constraint** | duplicate emails/usernames | field option; enforced in schema + runtime with 400 on conflict |
| 3 | **Deterministic migrations** | data loss on schema change; the bundle staying authoritative over time | `miurac migrate old.miura new.miura` diffs bundles → deterministic migration plan; destructive steps refused unless the bundle explicitly acknowledges them |
| 4 | **Transactions + cross-entity contracts** | the money shape: move value atomically or not at all; item-duping in game economies | multi-effect actions in one transaction; `ensures` spanning affected rows |
| 5 | **Aggregates** (`count`, `sum`) | capacity limits, balance invariants | usable in `where`, contracts, and test expects |
| 5a | **Enums + state-dependent `requires`** | illegal state transitions: out-of-turn moves, closing a closed ticket, self-approving an expense | `(field phase (enum lobby playing finished))`; `requires` gains access to `current` and simple state reads, so legality rules are compiled and testable. Today even tic-tac-toe is inexpressible — `requires` can't see the board. Games are the forcing function; workflows share the primitive. |
| 5b | **Seeded randomness as data** | unfair/unauditable outcomes (dice, shuffles) | a `(roll ...)` effect draws from a seeded server-side source and records the result in a row — compilation stays byte-identical, every game is replayable from its stored rolls |
| 6 | **Transactional outbox** | "the confirmation email must actually send" | `(enqueue ...)` effect writes to an outbox entity in the same transaction; delivery is external |
| 7 | **UI completeness for tools** | usable internal apps, not beauty | edit-forms prefilled from a row, detail view, pagination. No themes in v1. |
| 8 | **Toolchain force-multipliers** | trust at review time | `miurac fuzz` (contracts as free fuzz oracles — generated inputs against every action; any 500 is a compiler bug) and `miurac diff` (semantic bundle delta rendered as English) |

## Explicit v1 non-goals

Custom styling/themes, real-time/websockets, file uploads, external API
calls, background jobs beyond the outbox, multi-node scale, WASM target
(right endgame per `research/03`, wrong wedge). SQLite on one box serves
the target tier.

## Version sequencing

- **v0.4** — auth/permissions + `(unique)`
- **v0.5** — migrations
- **v0.6** — transactions, aggregates, outbox
- **v0.7** — UI completeness (edit forms, detail views, pagination)
- **v0.8** — `fuzz` + `diff` tooling; agent-guide refresh + authoring
  experiments for each new dialect (the proven loop: agents author from
  the guide alone; their failures amend the language)
- **v1.0** — hardening + docs + the decisive experiment below

## v1 success criterion (falsifiable)

One prompt → a multi-user, role-guarded internal tool with unique
constraints, ownership, and a schema migration applied to live data —
where the only human review is reading the bundle. Then rerun the
head-to-head benchmark at this complexity tier. The bet predicts the
direct arm starts dropping hidden-oracle checks (auth and migration
mistakes) while Miura does not. If the gap still doesn't appear, that is
evidence against the thesis and gets reported just as loudly.
