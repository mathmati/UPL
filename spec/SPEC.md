# UPL v0.1 — Language Specification

UPL is a bundle format: one file describes a whole application (data,
logic, contracts, UI), and a **deterministic** compiler (`uplc`) unpacks
it into runnable targets. v0.1 targets: a zero-dependency Python server,
a self-contained HTML/JS page, and a SQLite schema.

Design rules (from the research in `research/`):

1. **AI at the boundaries, determinism in the middle.** An AI writes and
   edits the bundle; the unpacker is a plain compiler. The same bundle
   always produces byte-identical output.
2. **Canonical form.** `uplc fmt` produces the single valid
   serialization; `sha256(canonical)` is the bundle's identity and is
   stamped into every generated artifact.
3. **Contracts are load-bearing.** `requires`/`ensures`/`require` are
   compiled into the targets and enforced at runtime: a violated
   `requires` is a client error (400), a violated `ensures` means the
   generated code itself is wrong (500). Humans audit the bundle, not
   the output.
4. **Generated artifacts are cattle.** Every target file carries a
   `DO NOT EDIT` header naming the source bundle and its hash.

## Surface syntax

S-expressions. Atoms: symbols (`create_task`), string literals
(`"Tasks"`, escapes `\n \t \" \\`), integers, `true`, `false`.
Comments: `;` to end of line.

## Bundle structure

```
(upl 0.1
  (intent "one paragraph of natural-language intent")
  (schema (entity ...) ...)
  (workflow (action ...) (query ...) ...)
  (ui (page ...) ...)
  (tests (case ...) ...))
```

The first four sections are required, each exactly once; `tests` is
optional (but a bundle without tests can't self-verify — always include
it in practice).

### schema

```
(entity Name
  (field name (type) option...))
```

Types: `id`, `text`, `int`, `bool`, `timestamp`.

Field options:

- `(auto)` — value supplied by the runtime (`id` → UUIDv4,
  `timestamp` → UTC ISO-8601). Only for `id`/`timestamp`.
- `(default literal)` — used when an insert does not assign the field.
  Mutually exclusive with `(auto)`.
- `(require expr)` — invariant checked on every insert and on every
  update that assigns the field. May reference only the field's own
  name (which is bound to the candidate value).

Every entity must have exactly one `(field ... (id) (auto))`.

### workflow

**Actions** mutate exactly one entity:

```
(action name
  (input (name type)...)          ; optional
  (requires expr)...              ; optional, over inputs; 400 on failure
  (effect <effect>)               ; required, exactly one
  (ensures expr)...)              ; optional; 500 on failure
```

Effects:

- `(insert Entity (field expr)...)` — every non-auto field must be
  assigned or have a default. Exprs see the inputs.
- `(update Entity id-expr (field expr)...)` — exprs see the inputs and
  `current` (the row before the update). Unknown id → 400.
- `(delete Entity id-expr)` — unknown id → 400.

`ensures` sees the inputs, `result` (the row after insert/update), and
`current` (update/delete only). An action returns `result` as JSON
(`{"ok": true}` for delete).

**Queries** read exactly one entity:

```
(query name
  (from Entity)                   ; required
  (where expr)                    ; optional, over bare field names
  (order-by field asc|desc))      ; optional; id is the tiebreaker
```

### Expressions

```
expr := literal | name | (. row field) | (op expr...)
op   := = != < <= > >= and or not len + - *
```

`(. row field)` reads a field of a bound row (`result`, `current`).
Name resolution is validated at compile time; an unbound name is a
compile error, never a runtime surprise.

### ui

```
(page name "/route" component...)
```

Components:

- `(heading "text")`
- `(form (action name) (field input-name (label "text"))...)` — must
  cover all of the action's inputs.
- `(list (query name) (item item-component...))`

Item components (rendered per row):

- `(text field)`
- `(checkbox (bind field) (action name (input-name row-field)...))`
- `(button (label "text") (action name (input-name row-field)...))`

Component/action arg lists must supply every input of the referenced
action; args pull values from the current row's fields.

### tests

Acceptance cases carried by the bundle itself; `uplc test` runs them
against the bundle's own unpacked Python target (each case on a fresh
database), so the bundle is self-verifying.

```
(case name step...)
```

Steps:

- `(do action (input value)... (as name) (expect expr)...)` — run an
  action. Values are literals or `(. binding field)`. `(as name)` binds
  the result row for later steps. Each `expect` sees `result` (this
  step's row) plus all earlier bindings. A contract rejection fails the
  case.
- `(fail action (input value)...)` — assert the action is rejected by a
  contract (requires / field require). Success fails the case.
- `(check query part...)` — run a query. Parts are processed in order:
  `(expect expr)` (where `result` is the row list; `(len result)` counts
  it) and `(row N (as name))`, which binds the N-th row (0-based, in
  query order) for later expects and steps — the mechanism for
  asserting ordering. An out-of-range index fails the case.

All names (actions, queries, inputs, bindings) are resolved at compile
time; input lists must be covered exactly.

## Unpacking

`python -m uplc unpack app.upl -o build` writes:

| Target | Contents |
|---|---|
| `build/server/app.py` | stdlib-only HTTP server + SQLite; one function per action/query; contracts compiled in |
| `build/web/index.html` | self-contained page: UI model as JSON + a fixed renderer runtime |
| `build/db/schema.sql` | `CREATE TABLE IF NOT EXISTS` DDL |

API mapping: action → `POST /api/<name>` (JSON body = inputs),
query → `GET /api/<name>`, page routes serve the HTML.

Environment: `UPL_PORT` (default 8000), `UPL_DB` (default
`server/app.db`).

## CLI

| Command | Purpose |
|---|---|
| `uplc check bundle [--json]` | parse + validate; JSON diagnostics carry a `path` into the bundle |
| `uplc fmt bundle [--write]` | canonical form |
| `uplc test bundle [--json]` | run the bundle's `(tests ...)` cases against its unpacked app |
| `uplc unpack bundle -o dir` | write server/web/db targets |

## Not in v0.1 (deliberately)

Relations between entities, auth/sessions, migrations (schema is
create-if-not-exists only), pagination, client-side validation, the
AI edit-lift tool, WASM target, SMT-checked contracts. Each is scoped
in `research/03-building-it-now.md`.
