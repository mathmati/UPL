# Head-to-head #2: Miura vs. direct codegen at auth + migration complexity

**Date:** 2026-07-14 · The experiment [ROADMAP.md](../ROADMAP.md) named as
v1's falsifiable test. The first head-to-head
([2026-07-14-head-to-head.md](2026-07-14-head-to-head.md)) found correctness
parity on simple CRUD but a large cost/effort gap. The roadmap predicted
that at the **auth + permissions + migration** tier — where the classic
vibe-coding failures live (forgotten access checks, ownership bypass, data
loss on schema change) — the *correctness* gap would finally appear. This
tests that prediction.

## Protocol

- **4 tasks**, each a multi-user app: two roles, ownership rules,
  admin/elevated override, a unique constraint, anonymous lockout,
  `@user`-scoped "my things" queries, and a **v2 schema change** (one new
  field) to be applied to a **populated** database.
- **Two arms, same model (Claude Sonnet):** Miura (bundle + compiler) vs.
  direct (hand-written stdlib Python, including hand-rolled auth, sessions,
  and a migration script).
- **Hidden oracle** ([benchmark2/oracle/](benchmark2/oracle/)): 22 checks
  per task — 18 driving the permission matrix and data correctness over
  HTTP (cookie-aware, multi-session, name-agnostic), and 4 verifying the
  migration preserves existing rows and defaults the new field. Written
  after the agents launched; neither arm ever saw it; it grades both arms
  through the identical pinned API/auth contract.
- Artifacts (bundles, hand-written apps, migration scripts, tasks, oracle,
  metrics) all in [benchmark2/](benchmark2/).

## Results

| Metric | Miura | Direct | Ratio |
|---|---|---|---|
| Hidden-oracle checks passed | **88/88** | **88/88** | — |
| Output tokens (4 tasks) | 197,347 | 290,391 | direct 1.47× |
| Tool invocations | 60 | 168 | direct 2.8× |
| Human-review surface (lines) | 562 *(incl. tests)* | 2,568 *(no tests)* | direct 4.6× |

Every task, both arms: a clean pass, including the deliberately subtle
manager-only-approval rule in `expenses` (a staff member cannot approve
even their own claim) and the ownership-vs-elevated-override matrix in all
four.

## The predicted correctness gap did **not** appear — and the honest reason

The roadmap bet that direct codegen would drop permission or migration
checks here. It did not. A diligent, self-testing Sonnet agent hand-wrote
correct auth — PBKDF2 password hashing, DB-backed sessions surviving
restart, 401/403 distinction, ownership enforcement, and a
data-preserving `ALTER TABLE` migration — on all four tasks.

**But this benchmark handed the direct arm Miura's advantage as a prompt.**
The direct-arm instructions explicitly named the exact failure modes to
avoid: *"password hashing (never store/return plaintext), sessions that
survive a restart (store in the DB), ownership checks (403 not 200), and
the migration preserving data (do NOT drop-and-recreate and lose rows)."*
That checklist **is** the thing Miura compiles in for free. Giving it to the
direct arm turns the test into a pure capability comparison and biases
hard toward the parity we observed. The realistic vibe-coding condition —
where nobody hands you that list — was not tested here, and is where the
gap most likely lives. This is the benchmark's central limitation, stated
plainly.

Even with that checklist in hand, the direct arm needed **1.47× the
tokens, 2.8× the tool calls**, and produced a **4.6× larger artifact to
review** to reach the same score.

## What the numbers do establish

1. **Cost and effort: a consistent, sizeable gap**, now confirmed at two
   complexity tiers. Auth did not close it; if anything the tool-call gap
   widened (2.8× here). Hand-writing sessions, hashing, and a migration is
   simply more work than declaring `(auth ...)` and `(allow ...)` and
   running `miurac migrate`.
2. **The review-surface gap grew with complexity** (2.4× smaller code in
   benchmark #1 → the reviewable Miura artifact is 4.6× smaller here) — and
   the direction of the asymmetry is stark: Miura's 562 auditable lines
   *include the acceptance tests*; the direct arm's 2,568 lines include
   *none*. A human signing off on the direct apps reads 4.6× more code and
   still has no committed test to re-run.
3. **Verification durability.** Both arms verified diligently. But the
   Miura arm's verification is *in the bundle* (`miurac test` reproduces it
   forever) and its permission rules are *enforced by the compiler on every
   build*. The direct arm's equally-careful curl-testing evaporated when
   the shells closed; its permission checks are hand-written conditionals
   that the next edit can silently break, with no test to catch it.
4. **Migration effort asymmetry.** Miura migrations cost **zero reviewable
   lines** (`miurac migrate old new --apply`, deterministic). Each direct
   agent hand-wrote a 50–84 line migration script and manually reasoned
   about idempotency and "don't drop-and-recreate." All four got it right —
   again, having been told the failure mode.

## Read-out for the thesis

- The **strong claim — "Miura produces more-correct code than direct
  generation"** — remains **unproven**, now at two tiers. With a capable,
  self-testing model that is told what to guard, direct codegen matches on
  correctness. We will not claim otherwise.
- The **defensible claim is unchanged and reinforced:** *same correctness
  for materially less work (~1.5× tokens, ~2.8× tool calls), a
  4.6×-smaller and test-carrying review surface, and verification +
  permission enforcement that live in the artifact instead of being
  reconstructed and discarded each session.*
- The experiment that could still surface a correctness gap, and the
  natural next one: **withhold the safety checklist from the direct arm**
  (the realistic condition), and/or use a weaker model, and/or scale to
  many more permission rules until an attention budget is exhausted. That
  isolates whether Miura's value is "gets it right when you forget to ask"
  — which is the actual vibe-coding failure mode — rather than "gets it
  right when explicitly told what to check," which both arms now do.

## Addendum: the no-checklist rerun (the realistic condition)

The caveat above was decisive enough to rerun. The four direct agents were
relaunched with **one sentence removed** — the paragraph that named the
footguns ("hash passwords, persist sessions, ownership 403, don't
drop-and-recreate on migration"). Everything else was byte-identical: same
tasks, same contract (which still *states* the requirements — 401/403,
passwords never returned, sessions persist, migration preserves rows), same
"test however you like," same hidden oracle. This isolates "correct when
you forget to ask" from "correct when told exactly what to check." The
Miura arm was not rerun — its guarantees are compiled in regardless of
prompting.

**Result: all four no-checklist direct apps also passed 88/88.** The
correctness gap did not appear a third time. The agents *independently*
chose PBKDF2 hashing, DB-backed sessions, the 403 ownership distinction,
and in-place `ALTER TABLE` migrations — because the contract stated the
requirements and the agents tested against them. Removing the checklist
made the direct arm slightly **more expensive** (307,848 tokens vs 290,391
with the checklist; they had to rediscover the footguns themselves — e.g.
the snippets agent hit and fixed a `?`-bind-in-DDL bug in its migration)
but no less correct.

| Metric (4 tasks) | Miura | Direct (checklist) | Direct (no checklist) |
|---|---|---|---|
| Hidden-oracle checks | **88/88** | 88/88 | 88/88 |
| Output tokens | 197,347 | 290,391 (1.47×) | 307,848 (1.56×) |
| Tool invocations | 60 | 168 (2.8×) | 165 (2.75×) |
| Review surface (lines) | 562 *incl. tests* | 2,568 *no tests* | 2,527 *no tests* |

## The honest conclusion, after three runs

The correctness gap has now failed to appear **three times**: simple CRUD,
auth+migration with the checklist, and auth+migration without it. It is
time to stop predicting it and state the finding:

**At small-to-medium task scale, a capable self-testing model (Sonnet)
writes correct auth and migrations by direct generation — with or without
being told where the traps are. Miura's deterministic compiler does not
produce *more-correct* code than a diligent direct agent at this scale.**
We will not claim otherwise, and the roadmap's "the gap will show at the
auth tier" prediction is, on this evidence, **wrong**.

What the three runs *do* robustly establish — the defensible value, now
well-measured:

1. **Cost/effort: a stable ~1.5× token, ~2.8× tool-call gap**, invariant to
   the checklist and consistent across two complexity tiers. Declaring
   `(auth ...)`/`(allow ...)` and running `miurac migrate` is simply less
   work than hand-writing sessions, hashing, ownership conditionals, and a
   migration script — even for a model that does the latter correctly.
2. **A 4.6× smaller review surface that carries its own tests.** The human
   signs off on 562 lines including the acceptance suite, versus ~2,530
   lines with no committed test.
3. **Structural vs. contingent correctness — the real distinction.** The
   direct arm is correct *because this run's agent tested thoroughly*. That
   correctness is a property of the *episode*, not the *artifact*: the next
   careless edit can silently reintroduce a 200-instead-of-403 with no test
   to catch it. Miura's permission rules are enforced by the compiler on
   *every* build and its tests live in the bundle — correctness is a
   property of the artifact. This benchmark measures a single episode, so
   it cannot see this difference; it is nonetheless the most important one.

## Where the correctness gap would actually live (untested, honestly)

The self-testing capability of a strong model is doing the work that closes
the gap. So the gap should appear where that capability degrades: **a
weaker author** (a Haiku direct arm, which self-tests less effectively) or
**a much larger surface** (dozens of permission rules, where a finite test
budget can't cover every interaction). Those — not "a bit more auth" — are
the conditions to test next. The reframed, evidence-backed thesis: *Miura's
correctness advantage is proportional to how much the author would
otherwise have to hold in its head and remember to test.* For a strong
model on a bounded task, that advantage is ~0 on correctness and real on
cost; it should grow as authors weaken and surfaces widen.

## Honest limitations

- n=4 tasks per condition, one model family, one run each; directional.
- Tasks sit inside Miura's v0.4–v0.6 competence by construction; nothing
  here speaks to apps Miura can't express.
- Both benchmark arms measure a single authoring episode, so the
  structural-vs-contingent correctness distinction (point 3 above) is
  argued, not measured — a maintenance/edit-churn experiment would be
  needed to measure it.
- Oracle, tasks, and one arm's language share an author; mitigated by the
  hidden-until-launch oracle, the pinned neutral contract, and full
  artifact publication, but independent replication would be stronger.
