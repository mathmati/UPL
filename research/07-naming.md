# Renaming UPL: A Naming Research Report

**Context:** UPL is a declarative "bundle" language authored by AI agents. One file holds schema, contracted actions, UI, and acceptance tests. A deterministic compiler **unpacks/expands** it into disposable, reproducible (sha256-identical) Python/HTML/SQL. Core motifs: expand/collapse, pack/unpack, fold/unfold, seed→plant, compression, determinism, contracts, bundle, single source of truth.

---

## 1. Naming History — What Actually Works

A handful of patterns repeat across 60+ years of language naming:

- **Single evocative words beat acronyms, almost every time.** Python (named for *Monty Python*, chosen to be "short, unique, and slightly mysterious"), Rust (named after the indestructible, "over-engineered for survival" fungus — Graydon Hoare liked the metaphor of something that persists), Ruby, Go — all one word, all pronounceable, all metaphor-first rather than description-first. Acronyms (COBOL, BASIC, FORTRAN) read as institutional and dated once the language leaves its origin era; **PHP** survived only because it was re-glossed from "Personal Home Page" into a recursive in-joke ("PHP: Hypertext Preprocessor"), which is a rare save. An acronym like "UPL" (Universal Programming Language) inherits this problem immediately, and also invites the obvious rebuttal: *no language is actually universal*, so the name overpromises in a way sophisticated adopters will needle.
- **Short + a distinctive metaphor is the sweet spot.** Rust, Zig, Go, Swift, Kotlin (an island near St. Petersburg, echoing Java-as-island-Indonesia naming humor), Julia (co-founder's mother's name, also musical), Gleam. One or two syllables, easy to say aloud in a meeting, easy to type as a CLI verb (`go build`, `cargo`), and a natural file extension.
- **Searchability is a real, load-bearing constraint, not a nice-to-have.** "Go" is the canonical cautionary tale: the name was fine, but Google in 2009 could not disambiguate "go" from the board game, the verb, or travel sites. The team had to mint "Golang" (from the forced `golang.org` domain, since `go.org` was taken) purely to give the community something SEO-searchable, and "Golang" is still the dominant tag on Stack Overflow/GitHub even though `go` is the real name. A brand-new AI-authored-code language should not need a parallel "shadow name" — pick something with a clean, low-noise search surface from day one.
- **Named-after-a-person/place is a legitimate, durable pattern**, distinct from generic-word or acronym naming: Ada (Ada Lovelace), Pascal (Blaise Pascal), Julia (partly a person's name). It reads as a tribute and carries built-in a story, which is good for docs/talks.
- **Symbol-heavy or unpronounceable names actively hurt adoption.** C++'s operator-based name is a running joke about how hard it is to say and type in prose; Brainfuck is deliberately hostile (it's an esolang, that's the point, but it's a lesson in what *not* to do for a serious project). A name needs to survive being said out loud in a founder pitch, a conference talk, and a toddler-proof Slack channel.
- **Trademark and namespace collision is the single most common late-stage naming failure** in software generally — not just languages. Companies routinely have to rename mid-flight (domain squatted, another product with the same name in the same space, a much bigger company owns the mark). For a language specifically, the collision that matters most is *other languages or dev tools with the same name*, because that's where your actual audience (engineers searching GitHub/npm/PyPI/Stack Overflow) will collide first.
- **What makes a name durable, synthesized:** short (1–3 syllables), pronounceable in English and ideally not embarrassing in a few major world languages, a clean unclaimed search surface, a natural short file extension, a metaphor that a newcomer can be told once and never forget, and no existing programming-language or major-dev-tool bearing the same name.

Sources: [dev.to — How programming languages got their names](https://dev.to/scottydocs/how-programming-languages-got-their-names-207e) · [Rust — Wikipedia](https://en.wikipedia.org/wiki/Rust_(programming_language)) · [Medium — How Programming Languages Got Their Names](https://kylehigginson.medium.com/how-programming-languages-got-their-names-df85277de4c3) · [Zig — Wikipedia](https://en.wikipedia.org/wiki/Zig_(programming_language)) · [Go vs Golang: The Only Difference Is How You Google It](https://discover.oreateai.com/discover/go-vs-golang-the-only-difference-is-how-you-google-it) · [Search Engine Journal — Go(lang) and SEO](https://www.searchenginejournal.com/golang-for-seo/497263/)

---

## 2. "UPL" Collision Report

The current name is **not** available in any meaningful sense:

- **UPL Ltd** is a $5B+ global agrochemical company (fertilizers, pesticides), and its "UPL" mark was recognized by the Indian Trademark Registry as a **"well-known trademark"** in 2023 — a formal legal status that extends protection against confusingly-similar use *outside* its own product category. This is the single biggest reason to leave the name: this is a large, litigious-capable, brand-protective public company holding a well-known mark on the exact three letters.
- **At least three unrelated software projects already use "UPL" / "Universal Programming Language":**
  - [bpupadhyaya/UPL on GitHub](https://github.com/bpupadhyaya/UPL) — a "Universal Programming Language" project.
  - A Devpost hackathon project literally called "Universal Programming Language," using symbols instead of English keywords.
  - "Unilang" projects (`markusbkk/unilang-1`, `luxe/unilang`) explicitly self-describe as a "universal programming language (UPL)."
- Old-timers may also associate "UPL" with **Univac's UPL** and other 1970s/80s "universal"-branded systems languages — the acronym has been reused so many times across computing history that it carries no distinctive signal at all.
- Net effect: "UPL" fails on trademark risk, fails on search distinctiveness (collides with a $5B company and multiple GitHub repos), and fails the "durable acronym" test from Section 1 — it reads as a placeholder, not a brand.

Sources: [AcronymFinder — UPL](https://www.acronymfinder.com/Universal-Programming-Language-(UPL).html) · [UPL Ltd — World Trademark Review](https://www.worldtrademarkreview.com/organisation/upl-ltd) · [UPL Recognized as 'Well-Known Trademark' — AgriBusiness Global](https://www.agribusinessglobal.com/markets/upl-recognized-as-well-known-trademark-by-the-indian-trademark-registry/) · [github.com/bpupadhyaya/UPL](https://github.com/bpupadhyaya/UPL)

---

## 3. Evaluating "Shoga"

**Shoga** (生姜, *shōga*) is simply the Japanese word for **ginger**.

**What it collides with:** exclusively food/kitchenware — pickled ginger (beni-shoga), powdered ginger, ginger graters (shoga oroshi), and specialty-grocery SKUs. No search result surfaced any technology company, framework, or programming language called Shoga. (There's a near-miss on **Shogun** — the well-known C++/Python machine-learning toolbox — which sounds adjacent but is a different word and not a true collision.) This is a very clean namespace for a piece of developer tooling: nobody searching "shoga" is looking for a compiler, and nobody searching for your compiler will stumble into ginger products.

**Fit to the metaphor:** Genuinely better than it first appears, if you lean into the *rhizome* rather than the *flavor*:
- Ginger propagates from a small underground rhizome — you plant a compact "seed piece" of ginger and it sends up shoots and multiplies into the full plant. That maps directly onto the brief's own **seed→plant** motif and onto "one small file expands into a whole running app."
- It does *not* map onto **fold/unfold** or **compression** at all — ginger isn't a folded or packed thing, so the metaphor only covers one of the four/five motifs in the brief (seed→plant), not expand/collapse or pack/unpack.
- It's warm, human, and un-technical-sounding in a way that's refreshing after a wave of Rust/Zig/Go hard-consonant names — but that same softness means it doesn't *advertise* determinism or compilation the way a fold/compression word would on first hearing.

**Practical notes:** short, easy to say, easy to spell, a clean `.shoga` or `.sho` extension, no trademark collision found, mild risk of being read as "just a cute word" rather than a technical signal — similar to how "Python"/"Ruby" needed the language itself to do the work of making the name mean something technical. That's a fully survivable trade-off (it worked for Python and Ruby), but it means Shoga would rely more on marketing/docs to teach the metaphor than a name like Miura or Furoshiki would.

**Verdict:** Shoga is safe and pleasant but metaphor-partial. It's a legitimate finalist, not a slam dunk — see the recommendation in Section 5.

Sources: [Terrasana — Shoga oroshi ginger grater](https://www.terrasana.com/product/shoga-oroshi-ginger-grater-1-st/) · [Specialty Produce — Shoga Ginger](https://specialtyproduce.com/produce/Shoga_Ginger_17852.php) · [Shogun Toolbox — GitHub](https://github.com/shogun-toolbox/shogun)

---

## 4. Candidate Names

All fit the expand/collapse · pack/unpack · fold/unfold · seed→plant · compression · determinism motif set to varying degrees. Fit score is 1–10 for *this specific language's* semantics and practical usability.

| Candidate | Evocation | Ext. | Searchability | Collision check | Fit |
|---|---|---|---|---|---|
| **Miura** | Named for the *Miura-ori* fold — a real, deterministic, rigid-origami fold used to compactly pack and reversibly, repeatably unfold sheets (solar panel arrays, maps). The physics literally guarantees "the same unfolding every time," which is your sha256-determinism story made physical. | `.miura` / `.mr` | Clean — a surname/car-model, no dominant tech meaning. | **None found** as a language or major dev tool (only the unrelated Lamborghini Miura). | **9** |
| **Furoshiki** | A single square of cloth that *wraps/bundles* one item, then unwraps deterministically back to exactly that item — an almost literal description of "one bundle file, unpacked losslessly." | `.furo` / `.fsk` | Clean, no software use found. | **None found** as a language or dev tool. | **8** |
| **Shoga** | Ginger rhizome: plant a small seed piece, it sprouts into the whole plant. Strong on seed→plant, silent on fold/pack. See §3. | `.shoga` / `.sho` | Clean (food/kitchenware only). | **None found.** | **7** |
| **Skein** | A skein is literally a *bundled, wound* length of yarn — "bundle" almost by dictionary definition — and one is folded/unwound in a single continuous pull. | `.skein` / `.skn` | Moderate — shares mindshare with the crypto hash function. | **Collision**: Skein, a SHA-3 finalist hash function (Ferguson/Schneier et al.). Different domain, but same audience (systems/security-adjacent devs) may pattern-match. | 6.5 |
| **Bract** | Botanically, a bract is a leaf-like wrapper that folds around and protects a bud until it opens/blooms — wrapper-that-unfolds-into-the-real-thing is a strong fit. | `.bract` | Moderate — obscure word, low general recognition. | **Collision**: Bract, an existing Clojure app-initialization framework. Not a language, but same "dev tool" namespace. | 6 |
| **Bale** | A bale is a compressed, bound bundle (hay, cotton) — direct hit on "compression" + "bundle." | `.bale` | Weak — homophone with "bail" causes confusion. | **Collision**: `bale_classic` (parallel-computing/PGAS research project) and Bale Messenger (a large Iranian messaging/payments app). | 5.5 |
| **Cocoon** | Wraps a small package that undergoes a fixed, deterministic transformation into something fully formed. | `.cocoon` | Moderate. | **Collision**: Apache Cocoon, a well-known 2000s-era XML web-publishing framework — dated, but real prior art in exactly the "framework" space. | 5 |
| **Rhizome** | Underground stem that stores compact "seed" nodes and sends up new growth deterministically at each node — good seed→plant fit. | `.rhz` | Weak. | **Collision**: multiple existing "Rhizome" software projects (a Java clustering framework, a feature-modeling/codegen platform, plus Rhizome.org, a well-known digital-art nonprofit). | 4.5 |
| **Kelp** | Underwater fronds that unfurl/expand from a compact holdfast. | `.kelp` | Weak. | **Collision**: `kelp-lang/kelp` is an actual, currently-developed functional programming language on GitHub. Direct language-name collision — avoid. | 3 |
| **Husk** | The compact outer wrapper that's stripped away to reveal the kernel/grain — very on-theme for "the bundle is disposable scaffolding around the real payload." | `.husk` | Weak. | **Collision**: two existing languages — Husk Scheme (Haskell-hosted Scheme implementation) and Husk (an esoteric Haskell-derived code-golf language). Direct language-name collision — avoid. | 2 |
| **Fern** | Fiddlehead ferns unfurl from a tight coil — a clean visual for expand/unfold. | `.fern` | Weak — dominated by a major existing product. | **Collision**: Fern (buildwithfern.com) is a well-funded, widely-used API/SDK/docs generator with real traction among AI-tooling companies (Cohere, ElevenLabs, Webflow) — the exact adjacent space (spec-to-code generation) your language occupies. High confusion risk. Avoid. | 2 |
| **Loom** | Weaves disparate inputs into one deterministic output; unpacking is like reading off a woven pattern. | `.loom` | Very weak. | **Heavy collision**: Loom (the massively popular screen-recording/collab app), `tokio-rs/loom` (Rust concurrency-testing tool), and at least one AI coding-agent already named Loom. Avoid. | 1.5 |
| **Ravel / Plait** | Braiding/weaving = bundling; unraveling = deterministic unpacking. | — | Weak. | **Collision**: Plait is an actual teaching language built on Racket/ML by Matthew Flatt; Ravel is an APL primitive, a Python meta-framework, and a Cadence EDA training product. Avoid both. | 1.5 |
| **Involute** | The mathematically exact curve traced when unwinding a taut string — deterministic unfolding, literally. | `.inv` | Weak. | No language collision, but the common-English meaning of "involute" is "complicated, intricate" — actively contradicts a determinism/simplicity pitch. Avoid despite clean namespace. | 3 |
| **Bud / Sprout** | Direct seed→plant hit. | `.bud` | Weak (generic marketing words). | **Collision**: "Bud" was the actual working name of Berkeley's Bloom/BOOM distributed-programming runtime; "Sprout" collides with Sprout Social and past Google hardware. Generic enough to be low-distinctiveness either way. | 3 |

**Landscape note:** the current AI-native-language wave (mid-2026) leans toward short, almost abstract technical words — e.g. Vercel Labs' new **Zero**, a systems language built explicitly for AI agents to read/repair/ship, emphasizing machine-checkable diagnostics over human prose. That's a useful data point: your competitive set is trending toward *terse and literal* rather than *poetic*, which slightly favors Miura/Shoga (crisp, single concept) over multi-syllable metaphor words like Furoshiki.

Sources: [kelp-lang/kelp — GitHub](https://github.com/kelp-lang/kelp) · [barbuz/Husk — GitHub](https://github.com/barbuz/Husk) · [justinethier/husk-scheme](https://github.com/justinethier/husk-scheme) · [Fern — buildwithfern.com](https://buildwithfern.com/) · [Loom (tokio-rs) — GitHub](https://github.com/tokio-rs/loom) · [Skein (hash function) — Wikipedia](https://en.wikipedia.org/wiki/Skein_(hash_function)) · [Plait — Racket package](https://pkgs.racket-lang.org/package/plait) · [Ravel — APL Wiki](https://aplwiki.com/wiki/Ravel) · [Bract — bract.github.io](https://bract.github.io/about.html) · [bale (parallel computing) — GitHub](https://github.com/jdevinney/bale) · [Rhizome — geekbeast/rhizome](https://github.com/geekbeast/rhizome) · [Miura fold — Wikipedia](https://en.wikipedia.org/wiki/Miura_fold) · [Vercel Zero — MarkTechPost](https://www.marktechpost.com/2026/05/17/vercel-labs-introduces-zero-a-systems-programming-language-designed-so-ai-agents-can-read-repair-and-ship-native-programs/)

---

## 5. Top-3 Recommendation

**1. Miura — top pick.** It is the only candidate that encodes *determinism* directly in its origin story, not just "unfolding" in general: the Miura-ori fold is famous specifically because it collapses and deploys the *same way every time*, by physical construction — that's a near-perfect analogue for "sha256-identical expansion." It's short, a real surname (durable pattern, see Ada/Pascal/Julia), has zero language/dev-tool collisions, and reads as quietly technical rather than cutesy — it will not embarrass anyone in a systems-engineering conversation. Main risk: the metaphor (rigid origami / satellite deployables) needs one sentence of explanation the first time; after that it sticks hard, the same way "Rust — the metal that survives" needed one sentence and then never needed re-explaining.

**2. Shoga — strong, safer runner-up.** Cleanest namespace of anything researched (zero tech collisions at all), effortless to say and spell worldwide, and the user already has affinity for it — which matters, since founder attachment to a name is itself a durability asset (see Python/Guido, Ruby/Matz). Its weakness is real, though: it only covers seed→plant, not fold/unfold/compress, so the compiler's core "expand a bundle deterministically" behavior isn't pre-loaded into the name the way it is with Miura or Furoshiki. Recommend pairing it with product language that leans on "planting"/"rhizome" imagery in docs to close that gap, or accept that — like Python and Ruby — the name will need the product to teach its own meaning over time.

**3. Furoshiki — best pure semantic fit, higher pronunciation/spelling friction.** Nothing else researched maps this literally onto "bundle" — a furoshiki *is* a single wrapped bundle that unwraps to reveal exactly its contents, with no loss. Zero collisions found. The cost is three syllables and a spelling English speakers will get wrong on first attempt (a real tax on word-of-mouth and typing a file extension), so it's better as a nickname/theme (e.g., naming the compiler's unpack step "furoshiki" internally) than as the primary brand, unless the team is comfortable with a longer on-ramp the way "Kubernetes" and "PostgreSQL" both required.

**If forced to choose one:** **Miura**, because it's the only name where the metaphor *is* the technical claim (deterministic fold ⇒ deterministic compile), rather than a decoration on top of it — and it has a completely clear field with no existing language or major dev tool to collide with.

---

## Sources

- [dev.to — How programming languages got their names](https://dev.to/scottydocs/how-programming-languages-got-their-names-207e)
- [Rust (programming language) — Wikipedia](https://en.wikipedia.org/wiki/Rust_(programming_language))
- [Zig (programming language) — Wikipedia](https://en.wikipedia.org/wiki/Zig_(programming_language))
- [Go vs Golang: The Only Difference Is How You Google It](https://discover.oreateai.com/discover/go-vs-golang-the-only-difference-is-how-you-google-it)
- [Search Engine Journal — Go(lang) and SEO](https://www.searchenginejournal.com/golang-for-seo/497263/)
- [AcronymFinder — UPL / Universal Programming Language](https://www.acronymfinder.com/Universal-Programming-Language-(UPL).html)
- [github.com/bpupadhyaya/UPL](https://github.com/bpupadhyaya/UPL)
- [UPL Ltd — World Trademark Review](https://www.worldtrademarkreview.com/organisation/upl-ltd)
- [UPL Recognized as 'Well-Known Trademark' — AgriBusiness Global](https://www.agribusinessglobal.com/markets/upl-recognized-as-well-known-trademark-by-the-indian-trademark-registry/)
- [Miura fold — Wikipedia](https://en.wikipedia.org/wiki/Miura_fold)
- [Terrasana — Shoga oroshi ginger grater](https://www.terrasana.com/product/shoga-oroshi-ginger-grater-1-st/)
- [Shogun Toolbox — GitHub](https://github.com/shogun-toolbox/shogun)
- [kelp-lang/kelp — GitHub](https://github.com/kelp-lang/kelp)
- [barbuz/Husk — GitHub](https://github.com/barbuz/Husk)
- [justinethier/husk-scheme](https://github.com/justinethier/husk-scheme)
- [Fern — buildwithfern.com](https://buildwithfern.com/)
- [Loom (tokio-rs) — GitHub](https://github.com/tokio-rs/loom)
- [Skein (hash function) — Wikipedia](https://en.wikipedia.org/wiki/Skein_(hash_function))
- [Plait — Racket package](https://pkgs.racket-lang.org/package/plait)
- [Ravel — APL Wiki](https://aplwiki.com/wiki/Ravel)
- [Bract — bract.github.io](https://bract.github.io/about.html)
- [bale (parallel computing) — GitHub](https://github.com/jdevinney/bale)
- [Rhizome — geekbeast/rhizome](https://github.com/geekbeast/rhizome)
- [Vercel Zero — MarkTechPost](https://www.marktechpost.com/2026/05/17/vercel-labs-introduces-zero-a-systems-programming-language-designed-so-ai-agents-can-read-repair-and-ship-native-programs/)
