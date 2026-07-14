# Writing Miura — Guide for AI Agents

You are writing a **Miura bundle**: one `.upl` file that describes a complete
web application (data, logic, contracts, UI, and acceptance tests). A
deterministic compiler unpacks it into a runnable Python server, an HTML/JS
page, and a SQL schema. You never write Python/HTML/SQL — only the bundle.

Your loop:

```sh
PYTHONPATH=compiler python3 -m miurac check app.upl --json   # validate
PYTHONPATH=compiler python3 -m miurac test  app.upl --json   # run the bundle's own tests
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
(miura 0.1
  (intent "One paragraph: what the app does, in plain language.")
  (auth ...)          ; optional — only for multi-user apps
  (schema ...)
  (workflow ...)
  (ui ...)
  (tests ...))
```

## auth — users, roles, and permissions (optional section)

For multi-user apps, declare:

```
(auth
  (roles admin member)        ; role names, your choice
  (default-role member)       ; role new signups get (required if >1 role)
  (first-user-role admin))    ; role of the very first signup (optional)
```

What you get automatically: a built-in `User` entity (never declare your
own), signup/login/logout endpoints, sessions, and a login bar in the UI.
`User` cannot be the target of your actions or queries; you interact with
it through references and rules:

- **Ownership**: `(field owner (ref User) (auto @user))` — filled with
  the signed-in user's id on insert. Never assign it in an effect.
- **`@user`** in expressions = the signed-in user's id:
  `(where (= owner @user))`, `(ensures (= (. result owner) @user))`.
- **Permissions** on actions/queries, checked before anything runs.
  Multiple `allow` clauses are OR'd:

  ```
  (allow anyone)          ; no sign-in needed
  (allow signed-in)       ; any signed-in user (note: bare word, no parens)
  (allow (role admin))    ; specific role
  (allow (owner owner))   ; update/delete only: current row's (ref User)
                          ; field named 'owner' must equal @user
  ```

  When an `(auth ...)` section exists, **the default is `(allow signed-in)`**
  — anonymous visitors can do and see nothing unless you say
  `(allow anyone)` explicitly. `@user` and `(auto @user)` are only legal
  where sign-in is guaranteed (i.e. not with `(allow anyone)`).
- Rejections: anonymous → 401, signed-in but not allowed → 403.

Rules of thumb: put `(allow (owner field))` on update/delete of
user-owned rows; add `(allow (role admin))` alongside it if admins may
override; scope "my things" queries with `(where (= owner @user))`.

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
  used when an insert doesn't assign the field. A field can't have both, but
  `(default ...)` and `(require ...)` combine fine:
  `(field quantity (int) (default 0) (require (>= quantity 0)))`.
- `(require expr)`: an invariant checked on insert/update. It may reference
  **only the field's own name** (bound to the candidate value). Works for any
  type — text length checks and numeric bounds alike.
- `(unique)`: no two rows may share this field's value (e.g. emails,
  slugs). A conflicting write is rejected with 400.
- **Relations**: `(field post (ref Post))` stores the id of an existing `Post`
  row. Writes that point at a missing row are rejected (contract violation).
  Deleting a referenced row is rejected by default; add `(on-delete cascade)`
  to the ref field to delete the children instead:
  `(field post (ref Post) (on-delete cascade))`. Ref fields can't be `(auto)`
  or have a `(default)` — every insert must assign them (typically from an
  input of type `id`).

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
- An effect is `(insert Entity (field expr)...)`,
  `(update Entity id-expr (field expr)...)`, or `(delete Entity id-expr)`.
- `requires` and `ensures` may each appear **multiple times**; every clause
  must hold. `(ensures (and a b))` and two separate `ensures` are equivalent.
- **Transactions (multiple effects).** An action may have **more than one
  `(effect ...)`. They all run in a single transaction — either every
  effect commits or none does.** If any contract fails (a `requires`, a
  field `require`, an `ensures`, a missing id), the whole action rolls
  back, so a half-finished transfer can never persist. Use this for
  anything that must move together (debit one row, credit another).
- **Effect bindings.** Name an effect's rows so later effects and `ensures`
  can read them:
  - `(effect (update Account from_id (balance ...)) (was before) (as after))`
    — `(was before)` binds the row *before* the update, `(as after)` binds
    it *after*. `(was)` works on update/delete; `(as)` on insert/update.
  - Later effects' expressions and all `ensures` can reference these
    bindings: `(ensures (= (. after balance) (- (. before balance) amount)))`.
- **What `ensures` sees:** the inputs, every `(as ...)`/`(was ...)` binding,
  plus `result` (the last effect's resulting row) and `current` (the last
  effect's pre-image, for update/delete). With multiple effects, prefer the
  explicit bindings — they're unambiguous.
- Insert must assign every field that is not `(auto)` and has no `(default)`.
  Never assign `(auto)` fields.
- Expression contexts: `requires` sees inputs. Insert exprs see inputs.
  Update exprs see inputs + `current` (the row before the update).
  `ensures` sees inputs + `result` (row after) + `current` (update/delete only).
- `(. row field)` reads a field from a bound row: `(. current done)`,
  `(. result title)`. Bare names are inputs (or, in `where`/field `require`,
  the row's own fields).
- Queries: one `(from Entity)`, optional `(where expr)` over bare field names,
  optional `(order-by field asc|desc)`. `order-by` works on any field type
  (text sorts lexicographically, so alphabetical listings are fine).
- In auth apps, `@user` works in a query `where` exactly as in actions:
  `(query my_tasks (allow signed-in) (from Task) (where (= owner @user)))`.
- **Parameterized queries**: a query may declare `(input (name type)...)` and
  use those names in its `where` — this is how you scope rows to a parent,
  e.g. "comments for one post":

  ```
  (query comments_for_post
    (input (post_id id))
    (from Comment)
    (where (= post post_id))      ; post = field, post_id = the parameter
    (order-by created_at asc))
  ```

  Input names must not collide with the entity's field names — rename the
  parameter if they would (`post_id`, not `post`).
- Counters/increments work via update: `(update Counter id (n (+ (. current n) 1)))`.
- **Where to put a contract:** a field `(require ...)` is the invariant — it
  rejects bad values on *every* write path (insert and update), which is the
  only way to guard computed updates like a decrement (the guard
  `(require (>= quantity 0))` rejects decrementing past zero). An action
  `requires` only sees inputs (never `current`), so use it for input
  validation; duplicating a field invariant there is optional and purely for
  a clearer error message.

Operators: `= != < <= > >= and or not len + - *`. `len` works on text (and on
`result` in test `check` steps, where result is the row list). There is no
division, no string concatenation, no if/else.

**Aggregates** count or sum across an entity's rows:

- `(count Entity)` or `(count Entity pred)` — number of rows (matching pred).
- `(sum Entity int-field)` or `(sum Entity int-field pred)` — sum of an
  `(int)` field over matching rows.
- Inside the predicate, bare names are the aggregated entity's own fields:
  `(count Booking (= event event_id))`, `(sum Ledger amount (= account @user))`.
- Allowed **only** in action `requires`, query `where`, and test `expect`
  steps — the read-only contexts. Not in effects, field `require`, or
  `ensures` of a mutation's own written rows. Use them for capacity limits
  (`(requires (< (count Seat) 100))`) and balance invariants.

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
- A form must cover **every input** of its action, via `(field ...)` (visible,
  user-typed) and/or `(bind ...)` (hidden, row-supplied — see below).
- Inside `(item ...)`: `(text field)`, `(checkbox (bind field) (action name args...))`,
  `(button (label "…") (action name args...))`. Action args are
  `(input-name row-field)` pairs — they pull values from the current row and
  must cover **all** inputs of the action.
- **Row-scoped nesting** — a list item may also contain `(heading ...)`, a
  nested `(form ...)`, and a nested `(list ...)`:
  - A nested form may use `(bind input row-field)` to fill an action input
    from the current row invisibly, e.g. a per-post comment form:
    `(form (action create_comment) (bind post_id id) (field text (label "Add a comment")))`.
    `bind` is only allowed inside an item; visible fields + binds together
    must cover the action's inputs exactly.
  - A nested list passes the row's fields into a parameterized query:
    `(list (query comments_for_post (post_id id)) (item (text text)))` —
    the `(post_id id)` pair maps the query input `post_id` from the row's
    `id` field, and must cover all the query's inputs.
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
    (fail create_task (title "")))
  (case newest_first
    (do create_task (title "older"))
    (do create_task (title "newer"))
    (check list_tasks
      (expect (= (len result) 2))
      (row 0 (as top))
      (expect (= (. top title) "newer")))))
```

Rules:
- Each case runs on a **fresh empty database**.
- **Auth apps**: create users with `(user name role)` steps, then act as
  them with `(by name)` on do/fail/check steps. The binding is a row —
  `(. alice id)` works. A step without `(by ...)` runs anonymously (use
  this to test that anonymous access is rejected). Example:

  ```
  (case ownership
    (user alice member)
    (user bob member)
    (do create_task (title "hers") (by alice) (as t))
    (fail delete_task (id (. t id)) (by bob))
    (fail create_task (title "anon"))
    (check my_tasks (by alice) (expect (= (len result) 1))))
  ```
- `(do action (input value)... (as name) (expect expr)...)` — runs an action.
  `(as t)` binds the result row; later steps reference it as `(. t field)`.
  `expect` sees `result` (this step's row) plus earlier bindings.
  **Within the same step, always use `result` — the `(as t)` binding only
  exists for *later* steps.**
- `(fail target (input value)...)` — asserts the target is **rejected**: by
  a contract (`requires` / field `require`) or by a permission rule. The
  target may be an action or a query — `(fail my_tasks)` with no `(by ...)`
  asserts anonymous callers can't run that query. If it succeeds, the case
  fails.
- `(check query part...)` — runs a query. For a parameterized query, pass its
  inputs: `(check (comments_for_post (post_id (. p id))) (expect ...))`.
  Parts are processed in order:
  - `(expect expr)` — `result` is the row list; `(len result)` counts it.
  - `(row N (as name))` — binds the N-th row (0-based, in query order) for
    later expects and steps: this is how you assert ordering, as in the
    `newest_first` case above. Out-of-range N fails the case.
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
9. A query input named the same as one of the entity's fields.
10. `(bind ...)` on a top-level form — binds need a row, so they only work on
    forms inside a list item.
11. `(allow (signed-in))` — it's the bare word: `(allow signed-in)`.
    Only `role` and `owner` take parens.
12. Declaring your own `User` entity, or assigning an `(auto @user)` field
    in an insert — both are automatic.
13. Using `@user` or `(auto @user)` on an action that has `(allow anyone)` —
    there's no user to refer to.
14. Forgetting that with `(auth ...)` present everything defaults to
    `(allow signed-in)` — public pages need `(allow anyone)` on their
    queries explicitly.
15. Referencing an `(as name)` binding within the *same* effect that
    defines it — bindings are visible to *later* effects and to `ensures`,
    not to their own effect.
16. Putting an aggregate in an `ensures`, effect, or field `require` —
    they belong only in `requires`, `where`, and test `expect`.

## Style

- Bundle everything for one app in one file. Keep intent honest — it should
  match what the schema/workflow actually do.
- Prefer contracts over hope: every action that takes user text should have
  a `requires` or field `require`; state transitions should have `ensures`.
