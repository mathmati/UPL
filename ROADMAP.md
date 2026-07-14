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

- **v0.4** — auth/permissions + `(unique)` ✓ shipped
- **v0.5** — migrations ✓ shipped (`miurac migrate`, deterministic diff + apply)
- **v0.6** — transactions + aggregates ✓ shipped (outbox deferred)
- **v0.7** — UI completeness (edit forms, detail views, pagination)
- **v0.8** — `fuzz` + `diff` tooling; agent-guide refresh + authoring
  experiments for each new dialect (the proven loop: agents author from
  the guide alone; their failures amend the language)
- **v1.0** — hardening + docs + the decisive experiment below

## v1 success criterion (falsifiable) — first result in

The auth+migration head-to-head has now been run
([experiments/2026-07-14-head-to-head-auth.md](experiments/2026-07-14-head-to-head-auth.md)).
Outcome: **both arms 88/88** on the hidden oracle — the predicted
correctness gap did **not** appear, and we report that as loudly as the
roadmap promised. The cost/effort/review-surface gaps held and widened
(direct arm: 1.47× tokens, 2.8× tool calls, 4.6× larger review surface,
and its verification was ephemeral while Miura's is carried in the bundle).

That run was then **rerun with the safety checklist withheld** (the
realistic condition). Result: **all four direct apps again passed 88/88** —
the correctness gap did not appear a third time. The agents chose secure
implementations from the contract's requirements alone. So the roadmap's
"the gap will show at the auth tier" prediction is, on this evidence,
**wrong**, and we say so.

Reframed thesis, now evidence-backed: at small-to-medium scale a capable
self-testing model writes correct auth/migrations by direct generation;
**Miura's measured value is cost (~1.5× tokens, ~2.8× tool calls), a 4.6×
smaller test-carrying review surface, and structural (compiler-enforced,
artifact-carried) rather than contingent (this-episode-tested)
correctness** — not fewer bugs. Miura's *correctness* advantage should be
proportional to how much the author would otherwise have to hold in its
head, so the conditions that would surface it are a **weaker author**
(Haiku direct arm) or a **much larger permission surface** — the honest
next experiments, replacing the auth-tier prediction that this benchmark
falsified.
