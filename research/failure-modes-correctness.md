# Non-Security Correctness, Robustness & Data-Integrity Failure Modes — What Miura Should Compile In Next

> Research input for v0.8 targeting (Sonnet agent, ~18 searches + a read of the
> emitter source). Classifies the empirically common NON-security bugs of
> AI-generated / vibe-coded apps against what Miura can eliminate by construction.
> Notably, this agent read `compiler/miurac/emit_python.py` directly and found
> real, current gaps — flagged inline.

## What Miura already eats

Miura already removes, for every app at once: leaked/missing permission checks, atomic multi-effect transactions with rollback, referential integrity (restrict/cascade), `(unique)` conflicts, input type/range/length contracts, deterministic non-destructive migrations, and self-carried acceptance tests. Two structural facts matter: the type system has **no float/decimal type** (`id`, `text`, `int`, `bool`, `timestamp`), so the "money as float" bug class is impossible by construction; and timestamps are always `datetime.now(timezone.utc).isoformat()` from one code path, closing the "naive local vs. UTC" class. Both are independently flagged as top-tier recurring bugs elsewhere — Miura has them for free.

## Ranked failure modes

| # | Failure mode | Freq × impact | Classification | How Miura could eat it |
|---|---|---|---|---|
| 1 | Missing/incomplete input validation, unhandled edge cases | Very high — most-cited AI-codegen defect category | **Already compiled** | `requires`/field `require`/`ensures` reject bad input at every write path |
| 2 | Unbounded queries / full table scans as data grows | High freq, high impact ("works in the demo, dies at 10k rows") | **Compiler-eatable — currently unaddressed** | Every query emits `SELECT * FROM {table}` with no WHERE pushdown, no LIMIT; filtering iterates the full Python row list. Push `where`/aggregate predicates into SQL; add **keyset** (not offset) pagination |
| 3 | N+1 queries | High freq — "the single most common cause of app-level DB perf issues" | **Compiler-eatable** | Row-scoped nested `(list (query ...))` issues one round trip per parent row; batch into one `IN (...)` fetch keyed on the parent id set |
| 4 | No idempotency / double-submit / double-charge on retries | High freq/impact on any client-retryable write | **Contract-expressible (partially reachable via `(unique)`)** | An `(idempotency-key)` input marker that dedupes a call server-side (store key+response, replay on repeat), on the transaction machinery already shipped |
| 5 | Money as floating point | High | **Already compiled** (no float type exists) | Nothing to add — structural |
| 6 | Timezone/date bugs (naive vs. UTC) | High | **Already compiled** (single UTC-ISO path) | Nothing server-side |
| 7 | Unhandled exceptions → leaked internals / crash / no logging | High freq | **Compiler-eatable — currently a real gap** | Only `PermissionDenied`/`ContractViolation`/`EnsuresViolation` are caught; any other exception propagates uncaught, and `log_message` is overridden to `pass` — **all request/error logging is currently suppressed.** Add a catch-all → generic 500 + request id, plus structured request/error logging |
| 8 | Race conditions: check-then-act, lost updates, double-booking | High freq | **Compiler-eatable (schematic) / contract-expressible (general)** | Aggregates already run inside the effect's transaction (right shape); but per-request fresh SQLite connection + untuned busy-timeout means contention surfaces as the uncaught-exception gap (#7). Add retry-on-`SQLITE_BUSY` + tuned timeout |
| 9 | Illegal state-machine transitions (close a closed ticket, out-of-turn move, self-approval) | High freq/impact in workflow apps | **Contract-expressible — already roadmapped (5a: enums + state-dependent requires)** | Research strongly supports prioritizing; tickets/approvals/games are one shape |
| 10 | Orphaned records / missing referential integrity | High | **Already compiled** (restrict/cascade) | — |
| 11 | Duplicate emails/usernames/slugs | High | **Already compiled** (`(unique)`) | — |
| 12 | Broken pagination (offset drift — rows vanish/duplicate as data shifts) | Medium-high once pagination exists | **Compiler-eatable — roadmapped (v0.7)** | Build as **keyset/seek** on `(order_by field, id)`; the emitter already emits the stable secondary sort key, so keyset is nearly free and sidesteps the offset-drift bug entirely |
| 13 | No rate limiting / resource exhaustion | Medium (mostly a security/DoS concern) | **Narrow case contract-expressible, mostly out-of-scope** | Per-user "N/window" cap needs a time-window predicate in the expr language; full rate limiting is infra |
| 14 | "Confirmation email must actually send" / at-least-once side effects | Medium freq, high impact | **Compiler-eatable — roadmapped (outbox)** | `(enqueue ...)` writing an outbox row in the effect's transaction |
| 15 | Copy-paste debt / clone growth over time | Very high at the maintenance layer (GitClear: copy-paste 8.3%→12.3%, refactor share 25%→<10%, 2020-24) | **Out-of-scope for a single-app compiler, structurally answered by the model** | The same bundle regenerates the same bytes — there is no diff to accumulate cruft in |
| 16 | Destructive agent action against production | Low freq, catastrophic (Replit July 2025: agent wiped a prod DB, fabricated status) | **Out-of-scope** (agent-tool problem) | Validates "AI at the boundaries, determinism in the middle" but needs no compiler feature |

## Evidence-quality note

CodeRabbit's 470-PR study (1.7× overall, 75% more logic bugs) is real but modest-sample — treat multipliers as directional. GitClear's 211M-line study is the most methodologically solid and its copy-paste/refactor-decline trend is well-corroborated. "45% of AI code fails security tests", "8,000 of 10,000 startups needed a rebuild", "88% of Supabase apps have RLS disabled" style figures are low-rigor marketing content — directionally plausible, not measured fact. Escape.tech's 5,600-app scan (2,000+ high-impact vulns) is a real methodology and the strongest evidence that "the failure rate is typical, not exceptional."

## Prioritized v0.8 target list

1. **Push query/aggregate filtering + limits into SQL; add keyset pagination.** Today every query fetches the whole table into Python and filters there — the textbook "works at 50 rows, dies at 50,000" cliff, 100% schematic, highest-value fix. Build pagination as **keyset/seek** from the start using the sort key the compiler already emits, sidestepping offset-drift. *(v0.7 shipped offset pagination as a UI feature; this is the correctness upgrade underneath the same `(page-size N)` surface.)*
2. **Catch-all exception handling + structured logging.** Only three exception types are caught; everything else propagates uncaught and logging is hard-disabled, so generated apps have zero observability today. Top-level handler → generic message + request id to client, full detail + per-request structured log server-side. Pure compiler work, every app identically.
3. **Idempotency keys for actions.** Top payment/retry bug class (double-charge, duplicate booking); nearly free on the transaction machinery; serves the money tier the roadmap targets.
4. **Enums + state-dependent `requires`.** Already roadmap 5a and strongly evidenced (illegal-transition bugs across tickets/approvals/games). The most-requested missing primitive.
5. **Batch nested-list queries** to kill UI-level N+1 (`IN (...)` on the parent id set).
6. **SQLite write-contention hardening** — tuned busy-timeout + bounded retry-on-`SQLITE_BUSY`, so concurrent writes degrade to a clean rejection rather than the uncaught OperationalError of #7.

The research most supports prioritizing **keyset pagination + SQL pushdown** and **enums + state-dependent requires** (both evidenced as top real-world bug classes), then **idempotency keys** and the **error-boundary + logging** fix (a genuine current gap found by reading the source). Rate limiting is mainly a security concern and belongs with that thread.

## Sources

- [State of AI vs Human Code Generation — CodeRabbit](https://www.coderabbit.ai/blog/state-of-ai-vs-human-code-generation-report) · [AI Code Quality 2025 — GitClear](https://www.gitclear.com/ai_assistant_code_quality_2025_research) · [Maintainability Gap 2026 — GitClear](https://www.gitclear.com/the_ai_code_quality_maintainability_gap)
- [A Survey of Bugs in AI-Generated Code — arXiv:2512.05239](https://arxiv.org/abs/2512.05239) · [Bugs in LLM-Generated Code — arXiv:2403.08937](https://arxiv.org/abs/2403.08937)
- [N+1 Query Problem — thecodingmachine](https://thecodingmachine.io/solving-n-plus-1-problem-in-orms) · [Why OFFSET fails and cursors win — Sentry](https://blog.sentry.io/paginating-large-datasets-in-production-why-offset-fails-and-cursors-win/)
- [Floats Don't Work For Storing Cents — Modern Treasury](https://www.moderntreasury.com/journal/floats-dont-work-for-storing-cents) · [Idempotent requests — Stripe](https://docs.stripe.com/api/idempotent_requests)
- [Race conditions — PortSwigger](https://portswigger.net/web-security/race-conditions) · [Workflow state-change validator — symfony/symfony#23863](https://github.com/symfony/symfony/issues/23863)
- [Replit AI wiped a production database — Fortune](https://fortune.com/2025/07/23/ai-coding-tool-replit-wiped-database-called-it-a-catastrophic-failure/) · [The 70% problem — Addy Osmani](https://addyo.substack.com/p/the-70-problem-hard-truths-about) · [Escape.tech methodology](https://escape.tech/blog/methodology-how-we-discovered-vulnerabilities-apps-built-with-vibe-coding/)
