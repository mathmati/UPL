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

## Honest limitations

- n=4 tasks, one model, one run; directional, not statistical.
- The decisive fairness caveat above: the direct arm was prompted with
  Miura's built-in guarantees as an explicit checklist.
- Tasks sit inside Miura's v0.4–v0.6 competence by construction; nothing
  here speaks to apps Miura can't express.
- Oracle, tasks, and one arm's language share an author; mitigated by the
  hidden-until-launch oracle, the pinned neutral contract, and full
  artifact publication, but independent replication would be stronger.
