# Writing UPL — Guide for AI Agents

You are writing a **UPL bundle**: one `.upl` file that describes a complete
web application (data, logic, contracts, UI, and acceptance tests). A
deterministic compiler unpacks it into a runnable Python server, an HTML/JS
page, and a SQL schema. You never write Python/HTML/SQL — only the bundle.

Your loop:

```sh
PYTHONPATH=compiler python3 -m uplc check app.upl --json   # validate
PYTHONPATH=compiler python3 -m uplc test  app.upl --json   # run the bundle's own tests
```

Repair until both report `"ok": true`. Compile errors carry a `path` into
the bundle (e.g. `"action create_task"`) telling you where to look.

## Syntax

S-expressions. Atoms: symbols (`create_task`), strings (`"Tasks"`), integers,
`true`, `false`. Comments start with `;`. **Symbols and strings are distinct:**
names/references are symbols (no quotes), display text and literal values are
strings (quotes).

## Bundle skeleton (section order is fixed)

```
(upl 0.1
  (intent "One paragraph: what the app does, in plain language.")
  (schema ...)
  (workflow ...)
  (ui ...)
  (tests ...))
```

## schema — entities and fields

```
(entity Task
  (field id (id) (auto))
  (field title (text) (require (and (>= (len title) 1) (<= (len title) 200))))
  (field done (bool) (default false))
  (field created_at (timestamp) (auto)))
```

Rules:
- Types: `id`, `text`, `int`, `bool`, `timestamp`. The type goes in parens: `(text)`.
- Every entity needs **exactly one** `(field id (id) (auto))`.
- `(auto)`: runtime-generated (only `id` and `timestamp`). `(default literal)`:
  used when an insert doesn't assign the field. A field can't have both.
- `(require expr)`: an invariant checked on insert/update. It may reference
  **only the field's own name** (bound to the candidate value).
- v0.1 has **no relations** between entities. Model within one entity, or use
  multiple independent entities.

## workflow — actions (writes) and queries (reads)

```
(action create_task
  (input (title text))                          ; all inputs, typed
  (requires (>= (len title) 1))                 ; precondition over inputs -> 400
  (effect (insert Task (title title) (done false)))
  (ensures (= (. result title) title)))         ; postcondition -> 500 if violated

(action toggle_task
  (input (id id))
  (effect (update Task id (done (not (. current done)))))
  (ensures (!= (. result done) (. current done))))

(action delete_task
  (input (id id))
  (effect (delete Task id)))

(query list_tasks
  (from Task)
  (order-by created_at desc))
```

Rules:
- An action has **exactly one effect**: `(insert Entity (field expr)...)`,
  `(update Entity id-expr (field expr)...)`, or `(delete Entity id-expr)`.
- Insert must assign every field that is not `(auto)` and has no `(default)`.
  Never assign `(auto)` fields.
- Expression contexts: `requires` sees inputs. Insert exprs see inputs.
  Update exprs see inputs + `current` (the row before the update).
  `ensures` sees inputs + `result` (row after) + `current` (update/delete only).
- `(. row field)` reads a field from a bound row: `(. current done)`,
  `(. result title)`. Bare names are inputs (or, in `where`/field `require`,
  the row's own fields).
- Queries: one `(from Entity)`, optional `(where expr)` over bare field names,
  optional `(order-by field asc|desc)`.
- Counters/increments work via update: `(update Counter id (n (+ (. current n) 1)))`.

Operators: `= != < <= > >= and or not len + - *`. `len` works on text (and on
`result` in test `check` steps, where result is the row list). There is no
division, no string concatenation, no if/else.

## ui — pages and components

```
(page home "/"
  (heading "Tasks")
  (form
    (action create_task)
    (field title (label "New task")))
  (list
    (query list_tasks)
    (item
      (checkbox (bind done) (action toggle_task (id id)))
      (text title)
      (button (label "Delete") (action delete_task (id id))))))
```

Rules:
- A form must have a `(field ...)` for **every input** of its action.
- Inside `(item ...)`: `(text field)`, `(checkbox (bind field) (action name args...))`,
  `(button (label "…") (action name args...))`. Action args are
  `(input-name row-field)` pairs — they pull values from the current row and
  must cover **all** inputs of the action.
- Labels are strings; everything else is symbols.

## tests — acceptance cases (always include these)

```
(tests
  (case lifecycle
    (do create_task (title "hello") (as t)
      (expect (= (. result title) "hello"))
      (expect (= (. result done) false)))
    (do toggle_task (id (. t id)) (expect (= (. result done) true)))
    (check list_tasks (expect (= (len result) 1)))
    (do delete_task (id (. t id)))
    (check list_tasks (expect (= (len result) 0))))
  (case rejects_empty
    (fail create_task (title ""))))
```

Rules:
- Each case runs on a **fresh empty database**.
- `(do action (input value)... (as name) (expect expr)...)` — runs an action.
  `(as t)` binds the result row; later steps reference it as `(. t field)`.
  `expect` sees `result` (this step's row) plus earlier bindings.
- `(fail action (input value)...)` — asserts the action is **rejected by a
  contract** (requires / field require). If it succeeds, the case fails.
- `(check query (expect expr)...)` — runs a query; `result` is the row list,
  so use `(len result)`. You cannot index into the list.
- Input values are literals or `(. binding field)`. Write at least 3 cases:
  a happy-path lifecycle, a contract rejection, and one more specific to the app.

## Common mistakes (each of these is a real compile error)

1. Quoting a symbol: `(action "create_task")` — action names are symbols.
2. Missing the auto id field, or assigning `id`/`created_at` in an insert.
3. A form that omits one of the action's inputs.
4. Referencing an input in `ensures` that doesn't exist, or using `current`
   in an insert action (there is no `current` on insert).
5. Field `require` mentioning other fields — it may only use its own name.
6. Booleans as strings: use `true`/`false`, not `"true"`.
7. `(default)` on an `(auto)` field.
8. Using an unbound name in a test step — bind rows with `(as name)` first.

## Style

- Bundle everything for one app in one file. Keep intent honest — it should
  match what the schema/workflow actually do.
- Prefer contracts over hope: every action that takes user text should have
  a `requires` or field `require`; state transitions should have `ensures`.
