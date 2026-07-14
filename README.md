# UPL — A Universal Programming Language, by AI, for AI

Research into the idea sparked by this tweet:

> "I wonder if we will ever see a new programming language go mainstream. If one does, it might serve the opposite purpose of every programming language humans have ever seen. Instead of making programming more accessible to humans it will be less accessible."

This repo contains both the research that scoped the idea and a **working v0.1 implementation**: a bundle language + deterministic compiler that unpacks one `.upl` file into a runnable Python server, an HTML/JS frontend, and a SQL schema, with contracts enforced at runtime.

## Quickstart

```sh
# validate a bundle (add --json for machine-readable diagnostics)
PYTHONPATH=compiler python3 -m uplc check examples/tasks.upl

# run the bundle's own acceptance tests against its unpacked app
PYTHONPATH=compiler python3 -m uplc test examples/tasks.upl

# unpack it into runnable targets
PYTHONPATH=compiler python3 -m uplc unpack examples/tasks.upl -o build

# run the generated app (zero dependencies — stdlib only)
python3 build/server/app.py     # → http://127.0.0.1:8000

# run the test suite (20 tests, incl. end-to-end against the generated server)
python3 -m unittest discover -s tests
```

The demo bundle ([`examples/tasks.upl`](examples/tasks.upl)) is a complete task tracker — schema, actions with `requires`/`ensures` contracts, a query, and a UI — in 36 lines of UPL. It unpacks into ~340 lines of Python, HTML/JS, and SQL.

## Layout

| Path | What |
|---|---|
| [`spec/SPEC.md`](spec/SPEC.md) | UPL v0.1 language specification |
| [`compiler/uplc/`](compiler/uplc/) | The compiler: reader/canonical printer, expression language, validator, and deterministic emitters (Python, web, SQL) |
| [`examples/tasks.upl`](examples/tasks.upl) | Demo bundle |
| [`tests/`](tests/) | Compiler tests + end-to-end runtime tests |
| [`research/`](research/) | The four research reports that scoped the design |

## Design principles (from the research)

1. **AI at the boundaries, determinism in the middle.** An AI authors and edits the bundle; the unpacker is a plain deterministic compiler — the same bundle always produces byte-identical output (tested). Diffs stay reviewable, caching works, and "does the artifact match the bundle?" is decidable.
2. **Canonical form.** One valid serialization per bundle (`uplc fmt`); its sha256 is the program's identity and is stamped into every generated file.
3. **Contracts are the audit surface.** `requires`/`ensures`/field `require` compile into the targets and are enforced at runtime (400 for client contract violations, 500 for ensures failures — i.e., compiler bugs). Humans audit the bundle; machines check the code.
4. **Generated artifacts are cattle.** Every output carries a `DO NOT EDIT` header naming its source bundle and hash.

---

## The research

Two rival concepts were explored, plus a feasibility study and a survey of who's already building in this space. The full reports live in [`research/`](research/); the rest of this README is the synthesis.

| Report | Question |
|---|---|
| [01 — The bundled meta-language](research/01-bundled-meta-language.md) | One artifact that *unpacks* into Python, HTML/JS, SQL, infra |
| [02 — The single universal language](research/02-single-universal-language.md) | One language that *replaces* them all |
| [03 — Could we build it now?](research/03-building-it-now.md) | Practical roadmap from today's components |
| [04 — State of play](research/04-state-of-play.md) | Who's already building this; dead-language revival candidates |

---

## The headline findings

**1. The tweet is half right — but the "less accessible" language is probably a proof language, not a glyph language.** The strongest real-world evidence for AI reviving human-hostile languages isn't APL or Forth — it's Lean (formal theorem prover: AlphaProof, Harmonic at $1.45B valuation), Dafny (82% LLM success rate at generating *formally verified* code, used inside AWS), and Prolog (resurging in research as the LLM's faithful-reasoning backend). The pattern: when AI generation is nearly free, **verification becomes the product**. The languages winning are the ones humans found too tedious to write but machines can be *checked* against.

**2. Most historic failure modes of universal languages really were human failure modes — but a new one takes their place: corpus gravity.** Learning curves, ecosystem migration cost, style wars, committee bloat — the things that killed PL/I, Ada, and executable UML — largely dissolve when AI is the author. But LLMs are measurably worst at exactly the languages with the least training data, and models pick Python in 58% of cases even when it's unsuitable. Ecosystem gravity didn't disappear; **it moved into the model weights**. Any new language starts from zero there. The mitigation is proven but industrial-scale: transpile existing Python/JS corpora into the new language, validate mechanically by running the tests, fine-tune (the MultiPL-T recipe).

**3. The two concepts converge on the same architecture.** Explored independently, both the "bundle" and the "single language" agents arrived at nearly the same design:

- A **typed, effect-annotated, contract-carrying semantic IR** as the source of truth (MLIR-style stack of dialects: schema, UI tree, workflow, compute) — not one flat general-purpose language.
- **AI at the boundaries, determinism in the middle.** The AI compresses intent into the IR; a boring, *deterministic* compiler lowers it to targets (Python, TS/DOM, SQL, and WASM where exact cross-target semantics matter). AI returns only for repair and for "lifting" human hand-patches back into the source. Nondeterministic unpacking destroys diffs, caching, and auditability — this is the single most important architectural decision.
- **Verification designed in**: every unit carries machine-checkable contracts, so humans audit the spec while machines audit the code. This is also the answer to "how do you trust code nobody reads."
- A **canonical form** (exactly one way to serialize any program) — hostile to humans, ideal for machines.

So "bundle vs. single language" turns out to be a go-to-market question, not an architecture question: the bundle (transpile to incumbents) is the viable first decade because it rides existing ecosystems and model competence; the single language is the better end state because you can't verify or optimize across a Python/SQL/JS seam. Feasibility ratings landed at ~6/10 for the bundle in constrained domains within 5 years, ~4/10 for full replacement within 10 — but 7/10 if bootstrapped IR-first.

**4. You could start building it today, and the first version is months, not years.** Every component exists off the shelf: MLIR for the compiler spine, WASM + WASI + Component Model as the universal runtime (67% of surveyed users now run WASM in production; typed language-neutral component boundaries via WIT), grammar-constrained decoding to *guarantee* LLMs emit only syntactically valid programs, tree-sitter for tooling, Dafny/Verus-style verifiers for the contract loop. A credible v0.1 — natural-language intent → UPL → verified → runnable WASM + readable Python/TS — is a small-team, 3–9 month project. See report 03 for the staged roadmap.

**5. People are already circling this, but nobody has landed it.** MoonBit is the flagship self-declared "AI-native" language; a 2025–26 wave of experimental agent languages (Vercel's zerolang, Sigil, Mog, Jacquard) is testing individual ideas (program-as-graph, canonical form, capability systems); the big money ($125M Tessl, GitHub Spec Kit, Amazon Kiro) is going to the *spec layer above* the language rather than a new language; and the labs' revealed preference is verifiers-as-reward (Lean, Dafny) rather than new syntax. The niche this project describes — a verified, canonical, multi-target semantic IR as the AI's native output format — is genuinely unoccupied.

## The three hardest problems (consistent across all reports)

1. **Corpus bootstrap** — a new language has no training data; breaking the chicken-and-egg requires transpile-and-validate at industrial scale, and even then you bootstrap *competence*, not ecosystem lore.
2. **Semantic equivalence across targets** — proving the Python, JS, and SQL unpackings of one program mean the same thing is unsolved in general; WASM + differential testing gives confidence, not proof.
3. **Intent → spec determinism** — the language can guarantee AI output is valid, typed, and checked, but not that it's *what you meant*. Natural-language intent is irreducibly ambiguous; this is the open research frontier ("intent formalization").

## Most likely outcome by ~2030

A layered hybrid rather than a coup: Python/TS/Go remain the dominant *generated* languages (corpus gravity is the best-evidenced force found); the human-authored artifact migrates up to English specs and agent harnesses; and a formal verification substrate grows underneath for domains where correctness pays. A purpose-built universal AI language breaks through only if a major lab adopts one as its agents' default output target — the one event that could beat data gravity.

## Where a project like this one could start

The minimal viable version both concept reports converged on: a typed, layered `.upl` bundle format for **one narrow vertical** (internal business web apps — schema + workflows + UI + infra), with a deterministic compiler to exactly two stacks (e.g. FastAPI+Postgres and React, shared logic as a WASM component), mandatory contracts checked in the generation loop, generated code marked non-editable, and an AI "lift" tool that folds hand-patches back into the bundle. The success criterion that killed every predecessor: survive two years of real *maintenance* and one framework migration without anyone abandoning the bundle. Demos always worked; maintenance is the game.
