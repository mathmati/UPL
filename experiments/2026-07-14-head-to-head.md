# Head-to-head: UPL bundle + compiler vs. direct LLM codegen

**Date:** 2026-07-14 · The experiment the value-evidence review
([`../research/06-value-evidence.md`](../research/06-value-evidence.md))
identified as missing from the literature: matched app tasks, one model,
two arms, graded by a hidden behavioral oracle neither arm ever saw.

## Protocol

- **5 tasks** (bookmarks, support tickets, event RSVP, flashcards,
  wishlist — two of them relational), each specified once in a shared
  requirements doc with a pinned HTTP API contract
  ([`benchmark/tasks/`](benchmark/tasks/)) so a single oracle can grade
  both arms.
- **Two arms, same model (Claude Sonnet):**
  - *UPL arm:* write a `.upl` bundle; only language reference is
    [`docs/upl-for-agents.md`](../docs/upl-for-agents.md); self-verify
    with `uplc check`/`uplc test`.
  - *Direct arm:* write a stdlib-only Python server (`app.py`) by hand;
    free to test however it likes. Python is maximally in-distribution —
    this arm gets the training-data advantage.
- **Hidden oracle** ([`benchmark/oracle/`](benchmark/oracle/)): 97
  behavioral checks across the 5 tasks (validations → 400, orderings,
  scoping, cascades, state transitions), written after the agents
  launched and run against each delivered app over HTTP. One oracle bug
  was found and fixed during grading (an "8-char url" mislabeled as 7);
  the fix advantaged neither arm.
- Full artifacts committed under [`benchmark/`](benchmark/); metrics in
  [`benchmark/results.json`](benchmark/results.json).

## Results

| Metric | UPL arm | Direct arm | Ratio |
|---|---|---|---|
| Hidden-oracle checks passed | **97/97** | **97/97** | — |
| Output tokens (5 tasks) | 181,944 | 243,020 | direct 1.34x |
| Tool invocations | 40 | 112 | direct 2.8x |
| Wall-clock build time | 4m 49s | 16m 42s | direct 3.5x |
| Lines a human must review | 572 (bundles) | 2,430 (code) | direct 4.25x |

Per-task, the pattern is uniform: every UPL build took 44–71 seconds and
6–10 tool calls; every direct build took 176–235 seconds and 20–26 tool
calls, converging on the same behavioral correctness.

## What actually differed

**1. Correctness didn't differentiate — at this scale.** A strong
mid-tier model, allowed to self-test, ships correct 500-line CRUD servers.
The "fewer errors" half of UPL's pitch is *not supported* by this run at
this app size. (The research literature predicts the gap opens with
complexity; these tasks were deliberately small and inside UPL's domain.)

**2. The bug classes were entirely different.** UPL-arm errors (4 total
across 5 builds) were all compile-time and syntactic — e.g. `(heading
name)` where only a string literal is allowed — caught in seconds by
`uplc check`, zero of them reachable at runtime. Direct-arm bugs were
infrastructure semantics: **three of five direct agents independently
hit the SQLite thread-local/in-memory connection bug** (each
request-thread silently seeing its own empty database under
`ThreadingHTTPServer`), and one had to rework its persistence model.
They found these themselves — through code review and stress tests that
consumed a large share of their 3.5x time overhead. That bug class
*cannot exist* in the UPL arm: the compiler emits the plumbing once, and
it is the same audited plumbing in every app.

**3. Verification is carried vs. transient.** The UPL artifacts contain
their own contracts and acceptance tests: anyone can re-run `uplc test`
and reproduce the assurance forever. The direct arm's (genuinely
diligent) testing evaporated when its shell sessions ended — its app.py
carries no tests. Post-benchmark, the assurance asymmetry is permanent.

**4. Operational surface.** Direct-arm agents spent effort on port
collisions, background-process lifetimes, and in one case a broad
`pkill` that killed *other arms' servers*. The UPL arm's toolchain
(compile + in-process test runner) had no processes to manage.

## Honest limitations

- n=5 tasks, one model family, one run each — directional, not
  statistical.
- Tasks were chosen to be expressible in UPL v0.3; the benchmark cannot
  say anything about the (much larger) space of apps UPL can't express,
  where the direct arm wins by default.
- The oracle, tasks, and one arm's language were authored by the same
  project — mitigated by the fixed API contract, hidden-until-launch
  oracle, and full artifact publication, but a truly independent
  replication would be stronger.
- Sonnet at this task size never failed behaviorally in either arm, so
  the benchmark measures cost/process, not the correctness gap the bet
  ultimately cares about. Scaling task complexity until the direct arm
  starts failing the oracle is the natural follow-up.

## Read-out for the thesis

Updating [`../research/06-value-evidence.md`](../research/06-value-evidence.md)'s
~25% empirical confidence: this run **confirms the economics and
review-surface claims** (25% cheaper tokens, 3.5x faster, 4.25x smaller
audit surface, at equal correctness) and **fails to confirm the
correctness claim at toy scale** while revealing its likely true shape:
the compiler doesn't prevent bugs the model would ship — the model
self-tests those away — it prevents *whole bug classes from existing*
and converts debugging time into compile errors. The strongest verified
formulation of UPL's value after this experiment: **same correctness,
~3-4x less work, and assurance that persists in the artifact instead of
dying with the session.**
