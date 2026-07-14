# Experiment: Can an LLM author UPL from the guide alone?

**Date:** 2026-07-14 · **Question:** UPL has zero training data in any
model. Can an AI agent that has never seen the language write correct,
contract-carrying, test-passing bundles using only
[`docs/upl-for-agents.md`](../docs/upl-for-agents.md) as in-context
reference?

This tests the central bet from the research
([`research/03-building-it-now.md`](../research/03-building-it-now.md)):
that spec-in-context authoring plus a machine-checkable toolchain
(`uplc check` / `uplc test`) beats the training-data cold-start problem
for a new language.

## Setup

Four independent Claude Sonnet agents (deliberately *not* the strongest
model — a mid-tier model is the harder and more economically relevant
test). Each agent:

- was told UPL is brand new and not to guess syntax from memory;
- was allowed to read **only** the authoring guide (not the spec, the
  examples, the compiler source, or the research);
- had to produce a bundle for a given app intent, with contracts and
  at least 3 test cases;
- ran the real loop: `uplc check --json` → `uplc test --json` → repair
  (max 8 rounds), logging every error verbatim.

Apps were chosen to force different language features: text validation,
computed updates (`(+ (. current n) 1)`), an inequality invariant that
must *reject* (not clamp), ensures-postconditions, and ordering.

## Results

| App | Key challenge | First `check` | First `test` | Repair rounds | Cases |
|---|---|---|---|---|---|
| Guestbook | two validated text fields | pass | pass | 0 | 3/3 |
| Inventory | reject decrement below zero | pass | pass | 0 | 3/3 |
| Poll | vote increment + exact-count ensures | pass | pass | 0 | 3/3 |
| Habit tracker | increment, reset, two ensures | pass | pass | 0 | 4/4 |

**4/4 bundles were fully correct on the first attempt — zero compile
errors, zero test failures, zero repair rounds.** All four were then
verified independently (fresh `uplc check` + `uplc test` runs) and
adopted into [`examples/`](../examples/).

Notably, the inventory agent independently discovered the *intended*
idiom for the hard contract: a field-level
`(require (>= quantity 0))` invariant, which rejects a decrement at
zero on the update path — rather than trying to guard it in the action,
which the expression contexts make impossible by design.

## Guide gaps reported (and what we did)

The agents' reports surfaced one real language gap and several
documentation gaps. All were addressed:

1. **Tests couldn't assert ordering** (guestbook agent): `check` steps
   could only count rows, so `order-by` behavior was untestable.
   → *Language change:* `(row N (as name))` bindings in check steps;
   the demo bundle now asserts newest-first ordering.
2. Whether multiple `ensures` clauses are allowed, and whether
   `and` can combine conditions (poll, habits agents). → Guide now states
   both explicitly.
3. Whether `(default)` and `(require)` combine on one field (habits
   agent). → Guide shows the combination.
4. Whether an update action's `requires` can see `current` — it can't,
   and the guide now explains *where to put a contract* (field
   `require` = invariant on every write path; action `requires` = input
   validation only), which was the inventory agent's exact question.
5. Whether `order-by` works on text fields (inventory agent). → It does
   (lexicographic); guide says so.

## Read-out

- **The cold-start problem looks beatable at this scale.** A ~200-line
  guide was sufficient in-context spec for a mid-tier model to write a
  new language flawlessly, first try, four times out of four. This is
  consistent with the research literature ("spec-in-context is the safe
  bet" for low-resource languages) but stronger than expected: we
  budgeted 8 repair rounds and used none.
- **Contracts did real work.** The agents didn't just satisfy syntax —
  they encoded the *semantic* requirements (rejection vs. clamping,
  exact-increment postconditions) correctly, because the language gave
  them a place to state those requirements and a runner that would have
  caught violations.
- **The loop generates its own improvement signal.** Every reported
  ambiguity became a guide fix or a language feature within the hour.
  This is the corpus flywheel at miniature scale: agent output → gap
  discovery → spec improvement → better agent output.
- **Caveats.** n=4, single language family of authoring model, and the
  apps are small and within a deliberately narrow v0.1 (one entity, no
  relations). The result says "the syntax and contract model are
  learnable from spec"; it does not yet say anything about 50-entity
  apps, adversarial intents, or long-lived maintenance (the thing that
  killed MDA). Those are the next experiments: (a) an app that needs a
  feature v0.1 lacks (relations) to observe failure behavior, (b) a
  maintenance round — hand the passing bundle back with a change
  request, (c) same test on a smaller/open-weights model.
