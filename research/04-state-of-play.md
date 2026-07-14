# Who's Building the Post-Human Programming Language? A State-of-Play Survey

**Research question:** Now that AI writes an increasing share of code, (1) who is already building AI-native/AI-first programming languages, and (2) could languages that "died" on human ergonomics — terse, symbol-heavy, formal, or paradigm-alien — come roaring back when the author is a model, not a person? Below: the evidence, the counter-case, and a scorecard.

---

## 1. Active AI-Native Language Efforts

### Purpose-built "AI-native" languages

- **MoonBit** is the flagship example: a general-purpose language (Wasm/JS/C targets) explicitly marketed as an "AI-native language toolchain," launched Oct 2022 alongside ChatGPT. Its team published *"MoonBit: Explore the Design of an AI-Friendly Programming Language"* at the LLM4Code workshop (ACM), arguing for mandatory top-level type signatures, structural interfaces, and clear top-level/local separation — features chosen so that partial file context is enough for an LLM to generate correct code. They claim internal tests where "thousands of lines run first-try with zero modifications."
- **Mojo** (Modular) is often lumped in but is a different beast: "AI-first" means *for AI workloads* (GPU kernels, Python superset), not *for AI authorship*. Worth distinguishing — VentureBeat's "Mojo Rising" coverage is about ML performance, not LLM ergonomics.
- **A 2025–26 wave of small agent-oriented languages** hit Hacker News: **Vercel Labs' zerolang** ("The Programming Language for Agents" — graph-native; agents query a semantic graph and submit checked edits, humans ask for outcomes), **Sigil** (one canonical textual form per AST, conventions become compiler rules), **Mog** (capability system so an agent can enforce its own I/O permissions), **Jacquard** ("AI-written, human-reviewed": effects visible in function signatures), **Nanolang** (tiny target language so weak models can act as pseudocode-to-code translators), and **B-IR** (an "LLM-optimized" intermediate language). None has meaningful adoption yet, but the density of independent attempts in a ~12-month window is itself a signal.
- **Design discourse is consolidating.** Armin Ronacher's *"A Language For Agents"* (Feb 2026) marks a notable flip: he previously believed existing code would cement incumbent languages, and now argues the opposite — because agents make coding cheap, ecosystem breadth matters less (agents can port missing libraries), and what matters is: readability without LSP tooling, explicit non-whitespace syntax, greppable/traceable dependencies (Go-style), declared effects for mockability, and *local reasoning from partial context*. He notes training-data prevalence isn't destiny: Swift is well-represented but agents struggle with its tooling; Zig is underrepresented but workable with good docs.

### Token-efficiency and grammar research

Academic work is directly probing "what grammar should an LLM write?": *"AI Coders Are Among Us: Rethinking Programming Language Grammar Towards Efficient Code Generation"* (arXiv 2404.16333) proposes SimPy, a token-minimized Python grammar; *"Token Sugar"* (arXiv 2512.08266) does token-efficient shorthand for source code. Practitioner measurements (Martin Alderson; UBOS ranking) find array/functional languages like **J and Clojure** among the most token-efficient, with a key twist covered below in §2.

### The "specs are the source" layer

The most-funded activity isn't a new language at all — it's moving the human-authored artifact *up* a level:

- **Karpathy**: "The hottest new programming language is English" (Jan 2023), then "Software 3.0" and "vibe coding" (2025) — the thesis that natural language becomes the human-facing programming interface.
- **GitHub Spec Kit** (93k+ stars, works with 30+ coding agents) and **Amazon Kiro** (spec-driven IDE: spec → design → tasks → implementation) have made spec-driven development arguably the fastest methodology adoption in recent memory (Martin Fowler's site now catalogs the tool category).
- **Tessl** (Guy Podjarny, ex-Snyk) raised **$125M at ~$750M valuation** explicitly to make software "spec-centric rather than code-centric" — specs as the maintained artifact, code as a build product.

### What the labs signal

DeepMind's trajectory is instructive: **AlphaCode** (competitive programming), **AlphaDev** (discovering faster *assembly* sorting routines), **FunSearch** (evolving *Python* functions for open math problems), and **AlphaProof** (IMO silver 2024, *Lean 4*). The labs haven't shipped an AI-native language — instead they gravitate toward **languages with machine-checkable feedback**, using "the compiler as a perfect, hallucination-free reward mechanism." Anthropic and OpenAI similarly optimize for existing high-resource languages (Python/TS) in their coding agents while the verification-adjacent startups (below) pick formal targets. That is the clearest lab-level signal: *the AI-native "language" so far is a verifier, not a syntax*.

---

## 2. Revival Candidates: Evidence vs. Speculation

### Lean — the one genuine, documented AI-driven boom (strong evidence)

Lean failed no one, but it was a niche academic prover; AI made it a strategic asset. DeepMind chose Lean 4 for AlphaProof; the ecosystem now includes Seed-Prover 1.5 (11/12 Putnam 2025), AxiomProver, Numina-Lean-Agent, and **Harmonic** (Vlad Tenev/Tudor Achim), whose Lean-based Aristotle hit IMO 2025 gold-medal performance and raised **$295M total ($120M Series C at $1.45B valuation)** — with an explicit roadmap toward *verified software synthesis* for aerospace, finance, and autonomous systems. The vericoding benchmark (arXiv 2509.22908) contains 7,141 Lean specs. This is the template for the whole thesis: a formally rigorous language whose human learning curve was brutal, now growing because the machine absorbs that curve and the human keeps the guarantees.

### Dafny / Verus — verification-aware programming, quietly industrial (strong evidence)

Dafny (Microsoft Research origin, now supported by Amazon's Automated Reasoning group, used to verify Cedar and AWS authorization infrastructure) is the best-performing target for "vericoding": **82% success generating formally verified code in Dafny vs. 44% in Verus/Rust and 27% in Lean** with off-the-shelf LLMs. A stream of 2025–26 papers (AlphaVerus, AxDafny, ATLAS, Formal Disco) treats verified synthesis as the answer to "trust me bro, the AI wrote it." This is a *revival by reframing*: contracts (`requires`/`ensures`) were tedious for humans but are exactly the machine-checkable spec an agent loop needs.

### Prolog — real research resurgence, no industrial wave yet (moderate evidence)

A dense cluster of 2025–26 work uses Prolog as the LLM's reasoning substrate: LoRP, NeuroProlog, Thought-Like-Pro, PrologMCP (a standardized Prolog tool interface for LLM agents), and the finding that "intermediate language choice drives neurosymbolic LLM reasoning" — LLM translates natural language to Prolog, an external solver executes it faithfully. Prolog's failure mode (humans find declarative logic alien) is irrelevant when the LLM is the translator. Still confined to papers and benchmarks, not production stacks.

### APL / J / K / BQN / Forth — mostly speculation, one fun twist (weak evidence)

The token-efficiency argument sounds tailor-made for array languages, but measurement complicates it: **APL's glyphs tokenize terribly** (each exotic symbol splits into multiple tokens), while ASCII-only **J** is among the *most* token-efficient languages tested (~70 tokens/task in one comparison). So the honest reading: J-style terseness is a live design input for future languages, but there is no evidence of an actual APL/Forth revival — IEEE Spectrum-adjacent coverage puts them firmly in "more remembered than used," and the tokenizer, plus microscopic training corpora, cuts against them. Forth's implicit stack state is also hostile to Ronacher's "local reasoning" criterion.

### Haskell / OCaml — counter-evidence outweighs the theory (weak, contested)

The purity/determinism argument ("types + purity = machine-checkable guardrails") runs into empirical trouble: a 2026 holistic evaluation found LLM **error rates significantly higher in Haskell and OCaml** than in Scala or Java, and generated FP code is often non-idiomatic imperative-in-disguise. The pro-case is softer: LLMs lower Haskell's learning curve for humans, which could slowly widen the corpus. Lisp/Clojure's homoiconicity ("programs as manipulable data") remains theoretically attractive for agents that refactor ASTs rather than text — zerolang's graph-native design is essentially this idea reborn — but no measurable Lisp resurgence exists.

---

## 3. The Counter-Signal: Nothing New Wins

The strongest case that the next mainstream language is *still Python*:

1. **Training-data gravity is self-reinforcing and measured.** *"LLMs Love Python"* (arXiv 2503.17181) found models choose Python in **58% of cases even when it's unsuitable**; LLMs now act as gatekeepers that "amplify incumbent ecosystems regardless of technical merit." Every AI-generated Python repo becomes tomorrow's training data.
2. **New languages face a colder start than ever.** Pre-LLM, a tutorial and evangelism could bootstrap human adopters; a statistical model needs a corpus. IEEE Spectrum's 2025 analysis argues AI is redefining popularity itself around what models generate well.
3. **The "language" layer may simply be absorbed.** If Karpathy is right that English + specs + agent harnesses (Spec Kit, Kiro, Tessl) become the human-facing layer, the target language beneath becomes an implementation detail — and implementation details default to whatever the model is best at, i.e., Python/TypeScript. Innovation energy visibly flows to the spec layer (where the $125M rounds are), not to syntax.
4. **Best-of-boring beats best-of-alien.** The pragmatic HN consensus candidate for agents isn't APL — it's **Go**: huge stable corpus, one way to write it, static types, greppable. The winning "AI language" may be the most statistically boring one we already have.

The rebuttal (Ronacher, Flix blog): agents make ecosystems cheap to port, docs-in-context can offset corpus gaps, so gravity is weaker than it looks — but as of mid-2026 this remains argument, not evidence.

---

## 4. Scorecard

### Who's building what

| Actor | Artifact | Bet |
|---|---|---|
| MoonBit team | AI-native general-purpose language + toolchain | New syntax designed for LLM generation |
| Vercel Labs (zerolang), Sigil, Mog, Jacquard, Nanolang | Experimental agent languages | Program-as-graph, capabilities, canonical form |
| GitHub (Spec Kit), Amazon (Kiro), Tessl ($125M) | Spec-driven dev tooling | English specs are the new source |
| DeepMind (AlphaProof/AlphaDev/FunSearch), Harmonic ($295M) | RL + provers | Verifier-as-reward; Lean as substrate |
| AWS Automated Reasoning + vericoding researchers | Dafny/Verus pipelines | Verified synthesis at industrial scale |
| Academia (SimPy, Token Sugar, intermediate-language studies) | Grammar/token research | Optimize syntax for the tokenizer |

### Top 3 revival candidates

1. **Lean** — the only candidate with money, benchmarks, IMO medals, and a unicorn behind it. AI didn't just revive it; AI is its growth engine, and it's expanding from math into verified software.
2. **Dafny (and Verus)** — best empirical LLM-verification success rate (82%), real industrial deployment at AWS, and a paper trail of agentic synthesis systems. Contracts-as-specs is the natural interface between English intent and machine-checked code.
3. **Prolog** — genuine research resurgence as the LLM's faithful-reasoning backend (PrologMCP, LoRP, NeuroProlog). Furthest from production of the three, but the "human-alien, machine-friendly" thesis fits it perfectly.

*(APL/J get an honorable mention as design DNA — token-terse, ASCII-clean J-style notation may be stolen by new languages — but there's no evidence of revival of the languages themselves.)*

### Most likely scenario by ~2030

A **layered hybrid, not a coup**: (a) Python/TypeScript/Go remain the dominant *generated* languages — training-data gravity is the best-evidenced force in this survey; (b) the human-authored artifact migrates up to English specs and agent harnesses (Karpathy's thesis, already industrializing via Spec Kit/Kiro/Tessl); (c) a formal verification substrate — Lean- and Dafny-shaped — grows *underneath* for domains where "the compiler as hallucination-free reward" pays (finance, aerospace, security, math). Purpose-built AI-native languages (MoonBit, zerolang et al.) stay niche unless a major lab adopts one as its agents' default target — the single event that could break data gravity. The tweet's instinct is half-right: the next important "language" is indeed less accessible to humans, but it's more likely to be a proof language humans can't write than a glyph language humans can't read.

---

## Sources

- MoonBit AI-native design: https://www.moonbitlang.com/blog/moonbit-ai · https://dl.acm.org/doi/10.1145/3643795.3648376 · https://www.moonbitlang.com/blog/beta-preview
- Agent languages: https://github.com/vercel-labs/zerolang · https://news.ycombinator.com/item?id=47652386 (Sigil) · https://news.ycombinator.com/item?id=47279263 (Mog) · https://news.ycombinator.com/item?id=48894630 (Jacquard) · https://news.ycombinator.com/item?id=46684958 (Nanolang) · https://news.ycombinator.com/item?id=46583581 (B-IR)
- Ronacher, "A Language For Agents": https://lucumr.pocoo.org/2026/2/9/a-language-for-agents/
- Grammar/token research: https://arxiv.org/pdf/2404.16333 (SimPy) · https://arxiv.org/pdf/2512.08266 (Token Sugar) · https://martinalderson.com/posts/which-programming-languages-are-most-token-efficient/ · https://ubos.tech/news/programming-languages-ranked-by-token-efficiency-for-ai%E2%80%91assisted-development/
- Spec layer: https://x.com/karpathy/status/1617979122625712128 · https://www.latent.space/p/s3 · https://github.com/github/spec-kit · https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html · https://techcrunch.com/2024/11/14/tessl-raises-125m-at-at-500m-valuation-to-build-ai-that-writes-and-maintains-code/
- Lean/AI math: https://deepmind.google/blog/ai-solves-imo-problems-at-silver-medal-level/ · https://www.nature.com/articles/s41586-025-09833-y · https://www.businesswire.com/news/home/20251125727962/en/Harmonic-Builds-Momentum-Towards-Mathematical-Superintelligence-with-$120-Million-Series-C
- Vericoding/Dafny/Verus: https://arxiv.org/pdf/2509.22908 · https://arxiv.org/html/2604.22601v1 · http://www.contrib.andrew.cmu.edu/~bparno/papers/alpha-verus.pdf · https://blog.icme.io/vericoding-the-end-of-trust-me-bro-the-ai-wrote-it/
- Prolog/neurosymbolic: https://arxiv.org/pdf/2606.14935 (PrologMCP) · https://www.sciencedirect.com/science/article/abs/pii/S0950705125011815 (LoRP) · https://arxiv.org/html/2603.02504 (NeuroProlog) · https://arxiv.org/pdf/2502.17216
- Functional-language evidence: https://arxiv.org/abs/2601.02060v1 · https://arxiv.org/html/2502.07928v1
- Counter-signal: https://arxiv.org/html/2503.17181v1 (LLMs Love Python) · https://spectrum.ieee.org/top-programming-languages-2025 · https://thenewstack.io/ai-programming-languages-future/ · https://www.mjlivesey.co.uk/2025/02/01/llm-prog-lang.html · https://blog.flix.dev/blog/will-llms-help-or-hurt-new-programming-languages/ · https://news.ycombinator.com/item?id=47222270 (Go for agents) · https://venturebeat.com/ai/mojo-rising-the-resurgence-of-ai-first-programming-languages
