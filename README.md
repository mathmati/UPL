# Miura

One small file describes your whole application — the data, the rules, the
permissions, the acceptance tests. A deterministic compiler unfolds it into
a running app: Python server, web UI, SQL schema. The same bundle produces
the same bytes, every time. Named for the
[Miura fold](https://en.wikipedia.org/wiki/Miura_fold): the origami fold
engineered to collapse and deploy identically on every cycle.

**Why:** AI will write you any code you ask for, and for most of an app
that's what you want — layouts, copy, styling, the creative surface. But
every app has a core that must not break: who can see what, values that
must never go negative, records that must never collide or vanish. Miura
splits the job. The creative surface stays with whatever tool you like —
vibe-code it, iterate freely. The core is written as a **Miura bundle**:
a few dozen declarative lines where every rule is a compiled,
runtime-enforced contract, every permission is a checked `allow` clause,
and the bundle carries its own tests. Vibes where vibes belong;
guarantees where guarantees belong.

The bundle is designed to be **written by an AI and audited by you**: you
read ~100 lines of rules, and a compiler — not a model — deterministically
writes the ~700 lines of code, so nothing can be smuggled in between what
you approved and what runs.

## Quickstart

```sh
pip install -e .                          # gives you the `miurac` command

miurac check examples/team-tasks.miura    # validate (--json for agents)
miurac test  examples/team-tasks.miura    # run the bundle's own acceptance tests
miurac unpack examples/team-tasks.miura -o build

python3 build/server/app.py               # → http://127.0.0.1:8000
                                          # zero dependencies — stdlib only

python3 -m unittest discover -s tests     # compiler test suite
```

Start with [`examples/tasks.miura`](examples/tasks.miura) — a complete task
tracker in 36 lines — or [`examples/team-tasks.miura`](examples/team-tasks.miura),
the v0.4 flagship: a **multi-user** task board with roles, ownership rules,
`@user`-scoped queries, and unique slugs, where sign-up/login/sessions and
every permission check are compiled from ~100 lines of bundle. To write your
own, hand [`docs/miura-for-agents.md`](docs/miura-for-agents.md) to any
capable LLM with a paragraph describing your app.

## Layout

| Path | What |
|---|---|
| [`spec/SPEC.md`](spec/SPEC.md) | Miura language specification |
| [`compiler/miurac/`](compiler/miurac/) | The compiler: reader/canonical printer, expression language, validator, bundle test runner, and deterministic emitters (Python, web, SQL) |
| [`docs/miura-for-agents.md`](docs/miura-for-agents.md) | The authoring guide an LLM writes Miura from (spec-in-context) |
| [`examples/`](examples/) | Nine app bundles — most written by AI agents that had never seen the language, incl. `ledger.miura` (atomic transfers) and `team-tasks.miura` (auth) |
| [`experiments/`](experiments/) | Empirical results on AI authorship |
| [`tests/`](tests/) | Compiler tests + end-to-end runtime tests (44) |
| [`ROADMAP.md`](ROADMAP.md) · [`REVIEW-NOTES.md`](REVIEW-NOTES.md) | Path to v1; per-release review notes |
| [`research/`](research/) | The research reports that scoped the design, plus novelty/value audits |

## Does the core bet hold? First evidence: yes

Miura has zero training data in any model, which the research flagged as the
single biggest threat to any new language ("corpus gravity"). So we tested
the mitigation: four mid-tier (Claude Sonnet) agents, each given **only**
the authoring guide, wrote bundles for four different apps — guestbook,
inventory with a reject-below-zero contract, poll, habit tracker.
**All four produced fully correct, contract-carrying, test-passing bundles
on the first attempt — zero repair rounds** — and their feedback drove one
language feature (ordering assertions in tests) and five guide fixes the
same day. Details in [`experiments/2026-07-14-authoring.md`](experiments/2026-07-14-authoring.md).

## How novel and valuable is this, honestly?

Two adversarial research audits answer this
([`research/05-novelty-audit.md`](research/05-novelty-audit.md),
[`research/06-value-evidence.md`](research/06-value-evidence.md)):

- **Novelty: ~65%.** The exact four-property combination (whole-app bundle +
  deterministic compiler with hash identity + self-carried contracts and
  tests + LLM-native authorship) appears unclaimed. The closest product,
  Remy, matches the "spec is the program" shape but explicitly uses an LLM
  as its compiler and accepts non-determinism — the precise bet Miura refuses.
  Tessl folds on the same point. Wasp has the deterministic compiler but is
  human-oriented, contract-free, and retreating from its own DSL. Caveat:
  the field is visibly circling this gap — the loudest criticism of the
  spec-driven-development wave is exactly "your regeneration is
  non-deterministic" — so this is first-mover on an obvious-in-hindsight
  synthesis, not a moat.
- **Empirical value: partially tested — by us.** The decisive experiment
  (matched tasks, Miura-spec-plus-compiler vs. direct LLM codegen, graded by
  a hidden oracle) had never been run by anyone, so we ran it:
  [`experiments/2026-07-14-head-to-head.md`](experiments/2026-07-14-head-to-head.md).
  Result on 5 matched apps, same model both arms: **identical correctness
  (97/97 hidden-oracle checks each), but the Miura arm was 25% cheaper in
  tokens, 2.8x fewer tool calls, 3.5x faster, with a 4.25x smaller
  human-review surface** — and its assurance (contracts + tests) lives in
  the artifact, while the direct arm's testing evaporated with its shell
  session. Three of five direct-arm agents independently hit the same
  SQLite threading bug; that bug class cannot exist in compiled bundles.
  Honest caveats: n=5 small apps inside Miura's domain, one model, and the
  correctness gap the bet ultimately cares about didn't appear at this
  scale — the verified claim so far is *same correctness for ~3-4x less
  work, with durable verification*, not *fewer bugs*.

A second round ([`experiments/2026-07-14-limits.md`](experiments/2026-07-14-limits.md))
probed the edges: a **maintenance** round (extend an existing bundle without
breaking its contracts — the failure mode that killed model-driven
engineering) passed with zero repairs; **Haiku** matched Sonnet on
cold-start authoring, ruling out training-data leakage; and an intent
deliberately **beyond the language** (a blog needing post↔comment
relations) produced the best possible failure — a loud, precise wall report
with proposed syntax instead of hallucinated code, because whole-bundle
name resolution rejects anything invented. That proposal became the
relations feature set the same day: `(ref Entity)` fields with enforced
integrity and restrict/cascade deletes, parameterized queries, and
row-scoped nested UI ([`examples/blog.miura`](examples/blog.miura)).

## Design principles (from the research)

1. **AI at the boundaries, determinism in the middle.** An AI authors and edits the bundle; the unpacker is a plain deterministic compiler — the same bundle always produces byte-identical output (tested). Diffs stay reviewable, caching works, and "does the artifact match the bundle?" is decidable.
2. **Canonical form.** One valid serialization per bundle (`miurac fmt`); its sha256 is the program's identity and is stamped into every generated file.
3. **Contracts are the audit surface.** `requires`/`ensures`/field `require` compile into the targets and are enforced at runtime (400 for client contract violations, 500 for ensures failures — i.e., compiler bugs). Humans audit the bundle; machines check the code.
4. **Generated artifacts are cattle.** Every output carries a `DO NOT EDIT` header naming its source bundle and hash.

---

## Where this is going

The v1 strategy — own everything that must not break (auth, migrations,
transactions, uniqueness, aggregates), and leave high-variance creative
work to direct generation — is laid out in [ROADMAP.md](ROADMAP.md).

---

## The research archive

The idea was scoped by a set of research reports before a line of code was
written — two rival architectures, a feasibility study, a state-of-play
survey, adversarial audits of novelty and value, and the naming audit.
They live in [`research/`](research/), and the empirical results that
followed live in [`experiments/`](experiments/). The language has grown
primarily from precise failure reports — agents hitting its limits and
proposing what they needed — and that is the intended mechanism.

## Status

Working v0.4, trialable today: `pip install -e .`, then hand
[`docs/miura-for-agents.md`](docs/miura-for-agents.md) to any capable LLM
with a paragraph describing your app. Roadmap to v1: [ROADMAP.md](ROADMAP.md).

---

*Built with AI, for AI.* · *Made with [Claude Code](https://claude.com/claude-code).*
