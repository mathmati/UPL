# Adversarial review — v0.8 and the positioning (2026-07-15)

A deliberately hostile review, commissioned after v0.8 shipped: two
independent adversarial passes (language design; market positioning) plus
a direct re-audit of the flagship artifacts. Nothing here is softened.
Where the criticism is wrong, we say so; where it lands, it lands.

## Finding 0 (the smoking gun): tictactoe.miura does not implement the game

`examples/tictactoe.miura` cannot detect a win. The only writers of a
decisive `winner` are `resign_x`/`resign_o`. Three-in-a-row is a
disjunction-of-conjunctions over cells feeding a *computed* value, and the
language has no if/else in effects and no computed fields — so it is
inexpressible, not merely missing. Consequences:

- Fill the board legally: `winner` stays `"none"`, and after nine moves
  every `play_*` fails its empty-cell requires — the game deadlocks.
  There is no draw detection either.
- The schema declares `(enum none x o draw)`: **three of the four
  advertised outcomes are structurally unreachable.** An auditor reading
  the bundle would conclude the app detects wins. It does not. The audit
  artifact — the thing whose honesty is the entire selling point —
  is misleading.
- The tests confirm the ceiling: every case asserts move *legality*;
  none asserts that winning produces a winner, because none can.
- The `ensures` clauses on the play actions are tautologies
  (`(update ... (cell_0 "x"))` … `(ensures (= (. result cell_0) "x"))`
  asserts only that the assignment assigned). Valuable as compiler-fuzz
  oracles; zero application-correctness value.

The experiment write-up ("the app that defined the language's limit is
now authorable first-try") overstated what happened: the *bookkeeping*
became expressible; the game did not. A ~40-line vanilla-JS tic-tac-toe
plays a complete game; this 281-line bundle plays bookkeeping.
**Action:** re-scope or caveat the example and the experiment addendum.

## Finding 1: the root disease is no means of abstraction

Every structural complaint is one symptom. Miura cannot parameterize
anything — no functions, no loops, no action generic over which field it
touches, no computed values. So any logic a real language would *factor*
must be **unrolled** into the bundle, and bundle size grows with the
unrolled size of the logic, not the factored size. That inverts the
"small and auditable" thesis the moment computation appears:

- 18 near-identical `play_N_m` actions (cells × marks), because enums
  can't be inputs and there's no if/else. The bundle *is* the copy-paste
  surface the project exists to remove — an auditor must eyeball that
  `play_5_x` touches `cell_5`, and a zero-prior LLM emitting 18 blocks is
  a natural off-by-one source.
- Connect-4 is already inexpressible (landing row is computed). The
  compression story holds only where there is nothing to compress
  (pure CRUD).

## Finding 2: the missing primitives are not the ones on the roadmap

The v0.8 remaining list (keyset pagination, error boundary, BOLA linter,
CSRF, idempotency) is all operational/security plumbing. The gaps that
actually wall off real apps are expressiveness, and none are on the
roadmap:

1. **Nullable/optional** — no null anywhere; a `(ref ...)` must be
   assigned on every insert. The optional foreign key (unassigned ticket,
   nullable `assignee`, `completed_at`-until-done) — present in half of
   all real schemas — is inexpressible without sentinels.
2. **Computed/derived values, including in UI** — aggregates are allowed
   only in requires/where/expect. "12 comments", an unread badge, a cart
   count, a leaderboard total **cannot even be displayed**.
3. **Date/time arithmetic + `now()`** — "due in 7 days", "overdue",
   TTL, business hours: all impossible (auto ISO strings compare
   lexicographically; there is no duration and no relative-to-now).
4. **Money/decimal/division** — `*` exists so `qty * price` in integer
   cents works, but tax, discount, proration, splitting a bill need
   division/rates. No division, no floats, no money type.
5. **String ops / search** — no LIKE/contains; a search box over titles
   is impossible.
6. **Enums as inputs** — a status *dropdown* is N buttons and N
   hand-written actions.

That the roadmap lists hardening instead of any of these is a tell: the
project has implicitly conceded the expression model and retreated to
hardening the CRUD tier. That retreat may be correct — but it should be
explicit, not implicit.

## Finding 3: v0.8's novelty is thin; its usefulness is real but narrow

State-dependent `requires` is a guarded command (Dijkstra 1975),
operationally `UPDATE ... WHERE status='draft'` + rows-affected — every
ORM has had it for decades. `(enum ...)` is a CHECK constraint. The
genuine ergonomic win — a guarded transition as a *named, contracted,
separately-testable action* — is real, and `documents.miura` uses it
cleanly. It is an ergonomic wrapper over a 50-year-old idea, not a novel
primitive. Verdict on "novel or overcomplicated": **neither — it is
conventional and useful**; the overcomplication (21 actions) is not the
primitive's fault but the missing-abstraction wall behind it.

## Finding 4: corpus gravity is a scissors

Every feature must live in the in-context guide (no training data), and
the guide is already spending budget teaching **anti-patterns** ("one
action per resulting value", a 16-item mistakes list). To fit real apps
the language must grow (null, dates, money, computed fields); each
addition must be fully documented in-context; the documentation competes
with the app for the same window. The operating range is a closing gap:
big enough to need the guide, small enough that the guide still fits.
Meanwhile every model upgrade improves Django/Rails/Next for free.

## Finding 5: "centre of LLM web build-outs" — no, on our own evidence

- The correctness wedge is empirically dead at the claimed tier: 88/88
  vs 88/88, three times, checklist withheld. "Structural vs contingent
  correctness" is currently **argued, not measured** — the edit-churn /
  maintenance experiment that would measure it has not been run. And the
  direct arm's real deficit (no committed tests) was a property of the
  benchmark setup; a direct agent told to commit a pytest suite closes
  most of the review-surface gap.
- The surviving advantages (~1.5× tokens, ~2.8× tool calls, 4.6× review
  surface) are denominated in model effort — the fastest-deflating cost
  in the industry. An efficiency edge that shrinks as models improve is
  a depreciating asset. And the 4.6× figure compares
  bundles-with-tests to code-without-tests, and inverts on any app with
  real logic (281 incomplete-tic-tac-toe lines vs ~40 complete JS ones).
- "Models are only going one way" cuts **against** Miura: a better model
  needs the guardrails less and reviews plain code better. The guardrail
  value is largest for weak authors and huge permission surfaces — a
  niche, and the opposite of "centre".
- "Mandate one way" is the classic 4GL/MDA/low-code death sentence; the
  v1 non-goals list (no styling, uploads, external APIs, realtime,
  background jobs, multi-node) is that sentence in writing. The first
  file upload or Slack webhook exits the language.
- The HTTP-seam hybrid is load-bearing for the whole positioning and has
  zero evidence: not benchmarked, not exampled end-to-end. The seam is
  where the two-system tax lives (contract drift, two deploys, two auth
  flows); the likely outcome is people pick one system.

## The one surviving steelman

**Miura as the deterministic, audit-carrying substrate for
high-consequence schematic backends authored by agent fleets at scale —
buyer is a platform, not a developer.** At n=1 with a strong model and a
careful human, structural correctness is worth ~0 (the benchmark proved
it). At n=10,000 generated apps with no human per app, "this episode's
agent tested diligently" doesn't scale and by-construction properties
(compiler-enforced permissions on every build, sha256-provenance,
artifact-carried tests, eliminated bug classes like the SQLite threading
bug 3/5 direct agents hit) are the only thing that does. Narrow,
unproven, real. Also genuinely differentiated: turn-based games /
server-authoritative replayable state (determinism is the feature there,
not a consolation) — small market, but the most distinctive idea in the
roadmap.

## Verdicts (one line each)

- **Language:** not converging on a general application language — a
  well-engineered **CRUD-with-guarded-transitions compiler** that works
  precisely up to the first line of genuine computation.
- **v0.8:** useful, conventional, not novel; tic-tac-toe was the wrong
  flag to plant — it stands on the far side of the expressiveness wall
  and the bundle misrepresents what it implements.
- **Positioning:** niche reliability substrate (fleet-scale agent
  codegen; turn-based/replayable state), not the centre of LLM web
  build-outs — and one honest experiment (edit-churn maintenance;
  direct-arm-with-committed-tests) away from being confirmed into that
  niche or out of it.

## What this review implies for next steps (not commitments)

1. Fix the record: caveat or re-scope `tictactoe.miura` and the
   experiment addendum (the schema should not advertise unreachable
   outcomes).
2. Decide the identity question explicitly: harden the CRUD+transitions
   tier (current roadmap) **or** attack the expressiveness wall
   (null/optional, computed-derived fields incl. UI display, datetime,
   enum inputs). These pull in opposite directions under the guide-length
   budget; choosing both is choosing neither.
3. Run the experiment that the whole surviving thesis rests on:
   edit-churn maintenance, Miura vs direct-with-committed-tests. It is
   the falsifiable test of "structural vs contingent", and everything
   else is argument.
