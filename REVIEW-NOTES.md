# Review notes — v0.6 (transactions + aggregates)

Context: the multi-effect + aggregates work was designed by Fable (the
validator in `model.py`) and the codegen/runner half was completed by
Opus 4.8 in the same session, at the user's request, to avoid leaving a
half-migrated tree. Everything below is green (44 compiler tests, 9
example bundles incl. `ledger.miura` with an atomic-transfer proof), but
these are the spots most worth a second look.

## What changed
- `Action.effect` (singular) → `Action.effects` (list). All effects run
  in one transaction, no intermediate commit; one `conn.commit()` at the
  end, after `ensures`.
- Effect bindings: `(as name)` (post-insert/update row), `(was name)`
  (pre-image of update/delete). Threaded through `names` so later effects
  and `ensures` resolve them. Per-effect locals are `_row{i}`/`_upd{i}`/
  `_res{i}`/`_cur{i}` to avoid clobbering across effects.
- Aggregates `(count E pred?)` / `(sum E field pred?)` in requires / where
  / test expects only. `expr.py` emits `_agg_count(_aggconn, ...)`.

## Points that most warrant scrutiny

1. **Rollback on the ContractViolation path is implicit.** On an `ensures`
   failure I emit an explicit `conn.rollback()`. But on a *field-require*
   or *missing-id* `ContractViolation` mid-transaction, rollback relies on
   `finally: conn.close()` discarding the uncommitted sqlite transaction
   (default `isolation_level=""`). Verified empirically by
   `ledger.miura::first_write_undone_when_second_effect_fails` (debit
   executes, credit fails on a missing account, debit is undone). Worth
   confirming this holds if we ever change the connection's isolation
   settings, and consider making rollback explicit on every exit path for
   clarity.

2. **Aggregate connection semantics.** `_aggconn = conn` inside actions,
   so aggregates in `requires`/`ensures`... wait — aggregates are *not*
   allowed in `ensures` (validator: `allowed=False`), only `requires`.
   Inside an action, requires run before any write, so `_aggconn=conn`
   sees committed state = correct. In queries and the test runner,
   `_aggconn=None` so the helper opens a fresh connection (committed
   state). This split is deliberate but subtle; double-check there's no
   context where an aggregate should see uncommitted state and doesn't.

3. **Cascade-then-fail not directly tested.** I tested "first update
   succeeds, second effect fails → rollback." I did *not* add a test where
   the first effect is a `delete` with `(on-delete cascade)` and a later
   effect fails — the cascade deletes should roll back too (same
   transaction, no commit), but it's unverified. Cheap test to add.

4. **`owner` allow restricted to single-effect actions** (validator). The
   emitter only emits the owner check when `single` is true. Reasonable
   (which row owns a multi-effect action is ambiguous), but if we later
   want per-effect ownership that's a design question.

5. **`result` when the last effect is a delete** returns `{"ok": true}`;
   `ensures` then can't reference `result` (validator omits it). Confirm
   that matches the intended contract for delete-terminal actions.

None of these are known bugs — they're the seams where the design intent
and the codegen meet, and where a fresh read is most valuable.
