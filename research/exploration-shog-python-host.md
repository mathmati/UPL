# Exploration: Shog — Miura's semantics hosted in a Python subset (2026-07-15)

Status: exploration, not a roadmap commitment. Prompted by the adversarial
review ([adversarial-review-2026-07-15.md](adversarial-review-2026-07-15.md)),
whose two fatal findings — corpus gravity and the expressiveness wall —
are both properties of Miura's *grammar*, not its semantics.

## The question

Python is the inverse of Miura: maximal corpus, maximal expressiveness,
zero guarantees. What can't Python do, and could the gaps be built in?

## What full Python fundamentally lacks (and cannot be given)

1. **Determinism** — arbitrary code reads clocks, networks, thread timing.
2. **Closed-world static analysis** — Rice's theorem: you cannot verify
   "every mutation checks ownership" over arbitrary Python (monkey-patching,
   `getattr`, `eval`, dynamic import). Miura's BOLA-linter idea is only
   possible because the world is closed.
3. **Effect containment** — no capability model; Python sandboxing against
   adversarial code is a graveyard (pysandbox: abandoned, "broken by design").
4. **Canonical form / identity** — no single serialization, no sha256-of-rules.
5. **Carried contracts and tests** — conventions, not artifact properties.

"Truly universal" in the strong sense is impossible: universality and
guarantees trade off exactly. That impossibility is the *specification*
for the fix.

## The move: don't extend Python — fence it

Shog = Miura's semantics re-hosted in a statically checked Python subset:

- Declarative schema / actions / permissions (dataclass/decorator-shaped
  registrations — the part that today is S-expressions).
- **Pure functions as the expression language**: no imports, no I/O, no
  attribute magic, AST-whitelist enforced at bundle load. Optionally
  Starlark-strict (no `while`, no recursion → guaranteed termination).
- Checker + trusted runtime replace parser + emitting compiler. The
  trusted computing base is audited once either way; "byte-identical
  emitted artifact" becomes "hash-identified bundle executed by a
  versioned runtime" (black-canonicalized source, AST sha256).

Threat model is the crux: runtime sandboxing fails against *malicious*
code, but our author is an LLM — **fallible, not adversarial**. A static
checker that loudly rejects `import requests` is exactly the correction
loop the authoring experiments showed models handle well.

## Prior art proving each piece is buildable

- **Starlark** (Bazel): Python syntax, closed semantics — deterministic,
  hermetic, guaranteed termination. Existence proof that Python *syntax*
  carries the corpus while semantics stay fenced.
- **Temporal Python SDK**: enforces a deterministic subset inside workflow
  functions, in production, today.
- **Convex** (TypeScript): schema + transactional mutations + pure
  functions in a deterministic runtime — essentially shog-for-TS. Both
  validation of the category and direct competition.
- **black + AST hashing**: canonical form and identity nearly for free.
- **Django models/admin**: the declarative-core-plus-framework ratio —
  small auditable rules, framework-owned plumbing — proven for decades.

## What it does to the adversarial review's kill-list

- Win detection: a ~10-line pure `winner(game)` function — expressible,
  auditable, testable. The 18 `play_N_m` actions collapse to one
  `play(cell, mark)` with a guard: **abstraction restored**.
- Computed/derived values (incl. UI display), datetime arithmetic, money
  math, search predicates: all pure functions over rows, inside the fence.
- Corpus gravity: the guide stops teaching a grammar and teaches only
  *the fence* — a much shorter document, and the syntax itself is maximally
  in-distribution.

## Honest costs

1. **Prior-pull inverts**: Miura's model didn't know the language; shog's
   model knows full Python too well and will drift outside the subset.
   Loud checker rejection (vs silent wrongness) is the better failure
   mode, but expect a constant rejection tax.
2. **Weaker artifact story**: trusted runtime executing fenced functions,
   not a compiler emitting everything. Still audit-once, slightly less
   pure.
3. **Review-surface claim must be re-measured**: shog bundles are bigger
   than Miura bundles (they contain real functions), still far smaller
   than full apps.
4. **Semantic correctness of pure functions is still unverified** — a
   wrong `winner()` is wrong. Contracts + carried tests remain the
   mitigation, unchanged.

## Read-out

Stronger position than Miura-the-grammar, and an evolution rather than a
restart: the deterministic runtime, contract machinery, permission model,
carried-test runner, migration engine, and sha256 identity all port; the
S-expression parser — the thinnest layer, and the layer causing both
fatal review findings — is what gets replaced (Python-AST ingestion +
fence checker). The decisive experiment if pursued: re-run the authoring
tests with a fence checker and measure the rejection tax vs Miura's
zero-repair runs, and re-run tic-tac-toe — which must come out *complete*
this time (win + draw detection), or the thesis fails again.

Name: Shog. Deliberately not-quite-Python signalling, same as Starlark.
