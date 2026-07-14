# Notes for review

Running log of design decisions made while banking work, flagged for a
closer review pass. Not user-facing; delete entries once reviewed.

## v0.6 — multi-effect transactional actions (`model.py`, `emit_python.py`, `runner.py`)

- An action now holds `effects: list` (was singular `effect`). All effects
  run in ONE transaction; `ensures` are checked **before commit** and a
  failure rolls back every effect. Confirmed by `examples/ledger.miura`
  (`first_write_undone_when_second_effect_fails`, `overdraw_rolls_back_both_sides`).
- Effect bindings: `(as name)` binds the resulting row, `(was name)` binds
  the pre-image (update/delete). Later effects and `ensures` can reference
  them. **Decision:** `ensures`'s `result`/`current` refer to the *last*
  effect; earlier rows must be reached via explicit `(as/was name)`. Worth
  a sanity check that this is the least-surprising choice — an alternative
  would be to forbid bare `result` when there are multiple effects and
  force names throughout. Current behavior favors the common single-effect
  case staying unchanged.
- `(allow (owner ...))` is restricted to single-effect actions (a
  multi-effect action has no single owning row). Enforced in validation.

## v0.6 — aggregates (`expr.py`, `model.py`)

- `(count Entity pred?)` and `(sum Entity field pred?)`. Allowed ONLY in
  action `requires`, query `where`, and test `expect` (read-only, pre-state
  contexts). Explicitly disallowed in effects, `ensures`, and field
  `require` — because an aggregate over post-mutation state mid-transaction
  is a footgun. **Flag:** confirm we're happy that `ensures` can't use
  aggregates; the ledger conserves value via `(was/as)` bindings instead,
  which is arguably cleaner, but a "total never exceeds cap" postcondition
  currently can't be written as an `ensures` — only as a `requires`
  pre-check. Possibly acceptable, possibly a gap.
- Aggregate predicate scoping: bare names in the predicate resolve to the
  aggregated entity's fields first, then outer names. Runtime helpers
  `_agg_count`/`_agg_sum` do a full-table scan (fine for SQLite/one-box;
  would need indexing to scale — a documented non-goal).

## v0.5 — migrations (`migrate.py`, `cli.py`)

- Migrations are an **operator CLI tool**, deliberately NOT bundle syntax,
  to keep the authoring guide small. The plan is a pure function of the two
  schemas → deterministic.
- Severity policy: safe / verify / destructive / blocked (see module
  docstring). **Judgment calls to review:**
  - Added `(unique)` on an existing column is emitted as a
    `CREATE UNIQUE INDEX` (severity `verify`), whereas a freshly created
    table gets a column-level `UNIQUE`. Same enforcement in SQLite, two
    mechanisms — is the inconsistency acceptable, or should fresh tables
    also use named indexes for uniformity?
  - Renames are NOT inferred (a rename reads as drop+add). Documented.
    Could add explicit `(rename old new)` hints later; deferred to keep
    scope tight.
  - Adding an `(auto)` field (uuid/timestamp) to a table with existing
    rows is `blocked` (can't deterministically backfill unique ids /
    original timestamps). Correct, but means "add a created_at to an
    existing entity" needs a hand step — acceptable?
  - `--apply` runs the whole plan in one connection but each step via
    `executescript` (its own implicit txn boundary). For a multi-step
    destructive migration, partial application on error is possible. Safe
    steps are ordered first so a failure leaves additions applied and
    destructions not-yet-run, but this isn't a single atomic transaction.
    Worth deciding whether to wrap the whole apply in BEGIN/COMMIT.

## v0.7 — pagination + edit prefill (model.py, emit_python.py, emit_web.py)

- `(page-size N)` on queries + `(field x (from row-field))` prefill on
  list-item forms. Both verified end-to-end (HTTP pagination slices;
  browser prefill shows current value + "Save" button).
- **Honest limitation flagged by the correctness research (which read the
  emitter source):** pagination is implemented as OFFSET slicing in Python
  after a full-table fetch. Two consequences: (a) offset can drift under
  concurrent inserts/deletes (a row seen twice or skipped across pages);
  (b) it caps the *response size* but not server work — the full table is
  still scanned. The `(page-size N)` bundle SURFACE is forward-compatible:
  v0.8 should upgrade the implementation to KEYSET/seek pagination with SQL
  predicate + LIMIT push-down (the emitter already sorts by `(field, id)`,
  so keyset is nearly free) WITHOUT changing any bundle. Prioritized in the
  ROADMAP v0.8 list. Do not advertise pagination as solving the perf cliff
  until that lands.
- Also surfaced by the research and queued for v0.8: only 3 exception types
  are caught in generated servers and `log_message` is disabled → no
  observability + potential internal leakage on unexpected errors. This is
  a real current gap (error-boundary + structured logging).
