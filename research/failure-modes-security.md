# Security Failure Modes in LLM-Generated & Vibe-Coded Apps, Mapped Against Miura

> Research input for v0.8 targeting (Sonnet agent, ~23 searches). Classifies the
> empirically common security failure modes of AI-generated code against what a
> compiler that owns 100% of the generated code can eliminate by construction.

## Framing

Miura is a deterministic compiler that owns 100% of a generated app's Python server, SQL schema, and web UI from a small declarative bundle. It already compiles in: parameterized SQL, hashed-password auth + sessions, deny-by-default role/ownership permission checks, unique constraints, referential integrity with restrict/cascade deletes, atomic multi-effect transactions, and field-level type/length/numeric contracts. Because the compiler is the only thing that ever writes code, any vulnerability that is *schematic* — the same shape in every app — can be structurally eliminated once, for every app generated forever after, the way Miura already eliminates SQL injection.

## Method

Research drew on OWASP's Top 10 and OWASP Top 10 for LLM Applications 2025, the "Asleep at the Keyboard" GitHub Copilot study (~40% of 1,689 generated programs vulnerable across CWE Top 25 scenarios), the CodeLMSec benchmark, Veracode's 2025/2026 GenAI Code Security Reports, Snyk's AI code trust surveys, Endor Labs' vulnerability-category writeup, and a cluster of 2025-2026 vibe-coding postmortems (Lovable/CVE-2025-48757, Base44, Moltbook, Tea app, Wiz's 5,600-app scan, GitGuardian's secret-leak data).

## Ranked failure modes

| # | Failure mode | Frequency / severity evidence | Classification | How Miura eats it |
|---|---|---|---|---|
| 1 | Broken access control / IDOR / BOLA (missing ownership check on read/write) | OWASP #1; ~100% of tested apps show *some* access-control weakness; the AI pattern of "building the endpoint that returns the record but rarely the check that the caller owns it" | **Already covered, with a gap** — `(allow (owner owner))` exists but nothing *forces* an author to add it to a mutation on an owned entity | A `miurac check` linter rule: any mutation targeting an entity with a `(ref User)` field that lacks an owner/role restriction is flagged, not silently allowed |
| 2 | Broken function-level authorization | OWASP API5 | **Already covered** | Deny-by-default `(allow ...)` on every action/query — no endpoint without a declared permission |
| 3 | Client-direct-to-database + forgotten row-level security | The defining 2025-26 vibe incident class: Lovable CVE-2025-48757 (CVSS 9.3, 170+ apps), Base44 auth bypass, Moltbook (1.5M tokens leaked via RLS-less table) | **Already covered by architecture** | Miura's client never talks to the DB; every read/write routes through the compiled server which enforces `allow` before anything runs — no client-callable data layer to misconfigure |
| 4 | Client-side-only authorization | Tea app DM leak, Enrichlead subscription bypass | **Already covered** | Permission checks compiled into the server handler, not the emitted UI |
| 5 | Hardcoded/leaked secrets in generated client code | 20-40% of vibe deployments leak a secret (Wiz: 400+ across 5,600 apps); median 11 min leak→first malicious request | **Already covered / needs a standing invariant for growth** | Server holds all secrets; the language has no primitive to embed a credential in client JS. Must stay an explicit invariant once outbound integrations are added |
| 6 | Mass assignment / over-posting | OWASP API6 | **Already covered by design** | Every effect names its fields explicitly; there is no "assign the whole payload" code path to generate |
| 7 | XSS via unsanitized rendering | Veracode: AI fails CWE-80 defense in 86% of samples; 28% of React repos use `dangerouslySetInnerHTML`, <10% sanitized | **Compiler-eatable** | The UI's only content primitives (`text`/`label`/`heading`) must always emit escaped output; never grow a raw-HTML sink without a mandatory compiled sanitizer — codify as invariant + regression test |
| 8 | Missing CSRF protection on state-changing requests | Common AI-generated-form gap | **Compiler-eatable** | Every mutating action is compiler-known; emit SameSite=Strict cookies + same-origin/anti-CSRF check on all mutations, zero bundle syntax |
| 9 | CORS misconfiguration (wildcard + credentials) | 23% of scanned sites; AI defaults to `origin:"*"` | **Compiler-eatable (largely moot by architecture)** | Same-origin UI+API; never emit a permissive CORS header, assert it in a test |
| 10 | Missing rate limiting / brute-force protection on auth | Recurrent AI-codegen gap | **Compiler-eatable** | Signup/login are compiler-owned; attach per-IP/per-account throttling uniformly |
| 11 | Verbose errors / stack traces / debug mode leaking internals | Routine AI pattern | **Compiler-eatable** | Guarantee unhandled exceptions in a production build return a generic message, no traceback/path/schema, detail logged server-side only |
| 12 | Weak/absent password hashing | Classic breach root cause | **Already covered** | Salted hashing compiled in |
| 13 | Excessive data exposure (row returns fields the caller shouldn't see) | OWASP API3 — field-level, not row-level | **Contract-expressible (gap)** | Row-scoped permissions don't reach field-level; needs a per-field visibility declaration compiled into the query projection |
| 14 | Hallucinated/malicious dependencies (slopsquatting) | ~20% of AI-suggested packages hallucinated | **Already covered** | Generated servers are stdlib-only — no dependency tree to squat |
| 15 | Insecure deserialization / eval / dynamic code | Common when AI reaches for eval/pickle | **Already covered** | Closed-form expression language; no primitive compiles to eval |
| 16 | SSRF / unrestricted file upload | Insecure upload in 78% of upload-offering sites | **Out-of-scope today, landmine for tomorrow** | No file/blob/outbound-HTTP primitive yet; must be designed with allowlists/limits the moment upload/fetch lands |
| 17 | Session-fixation / weak cookie hardening | Rolled into "broken authentication" (~1 in 4 AI-code OWASP findings) | **Mostly covered, worth hardening explicitly** | Make cookie flags (HttpOnly/Secure/SameSite) + expiry/rotation an explicit, tested guarantee |

## The key finding

The most dangerous high-frequency vibe-coding failures of 2025-26 — client-side-only auth, forgotten Supabase RLS, mass assignment, dependency hallucination, hand-rolled password storage — are *architectural* consequences of letting an LLM freehand a full-stack app with a client that talks straight to a database. Miura's "no client-callable data layer, no free-text effect, no dependency tree" design forecloses most of them **by construction, not by discipline** — the vulnerable code shape has nowhere to be written, the same way SQL injection is already impossible. The remaining gaps cluster in (a) web-transport hygiene unrelated to business logic (CSRF, CORS, rate limiting, verbose errors) and (b) two real permission-model gaps: ownership checks that can be *omitted*, and no field-level (only row-level) visibility.

## v0.8 target list

1. **CSRF defense on every mutating action** — SameSite=Strict + same-origin/token check, pure server codegen, zero bundle syntax.
2. **Auth-endpoint rate limiting / brute-force throttling** — per-IP + per-account counter with backoff on the compiler-owned signup/login/reset endpoints.
3. **Production-safe error boundary** — unhandled exceptions never return a traceback/path/SQL fragment; generic message to client, full detail to server logs.
4. **Ownership-check linter (close the BOLA gap)** — `miurac check` flags any mutation on an owned entity with no owner/role restriction. Highest-value fix; BOLA/IDOR is the most common and damaging category in every study surveyed.
5. **Field-level visibility contracts** — a per-field `(visible owner)` / `(visible (role admin))` compiled into the query projection, closing excessive-data-exposure which the row-level model can't reach.
6. **Codify secrets-stay-server-side and output-escaping as standing invariants** with regression tests, before adding any external-API or rich-text feature.

Items 1-3 are pure "same shape every app" wins with no bundle-syntax cost — the fastest path. Item 4 is a validator change. Item 5 is a small DSL extension. Item 6 is a design constraint to enforce now.

## Sources

- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/) · [OWASP LLM Top 10 for code generation — Sonar](https://www.sonarsource.com/resources/library/owasp-llm-code-generation/)
- [Asleep at the Keyboard — CACM](https://cacm.acm.org/research-highlights/asleep-at-the-keyboard-assessing-the-security-of-github-copilots-code-contributions/) · [CodeLMSec — arXiv:2302.04012](https://arxiv.org/abs/2302.04012)
- [Veracode 2025 GenAI Code Security Report](https://www.veracode.com/resources/analyst-reports/2025-genai-code-security-report/) · [Veracode blog](https://www.veracode.com/blog/genai-code-security-report/)
- [Wiz: risks in 20% of vibe-coded apps](https://www.wiz.io/blog/common-security-risks-in-vibe-coded-apps) · [Escape.tech vibe-coding scan](https://escape.tech/blog/methodology-how-we-discovered-vulnerabilities-apps-built-with-vibe-coding/)
- [Lovable CVE-2025-48757 — SentinelOne](https://www.sentinelone.com/vulnerability-database/cve-2025-48757/) · [The Next Web](https://thenextweb.com/news/lovable-vibe-coding-security-crisis-exposed)
- [Secrets leaking through vibe-coded sites — RedHunt Labs](https://redhuntlabs.com/blog/echoes-of-ai-exposure-thousands-of-secrets-leaking-through-vibe-coded-sites-wave-15-project-resonance/)
- [Most common vulnerabilities in AI-generated code — Endor Labs](https://www.endorlabs.com/learn/the-most-common-security-vulnerabilities-in-ai-generated-code)
- [OWASP API1 BOLA](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/) · [OWASP API5](https://owasp.org/API-Security/editions/2023/en/0xa5-broken-function-level-authorization/) · [Mass assignment — Snyk Learn](https://learn.snyk.io/lesson/mass-assignment/)
- [XSS in AI React/Next code — VibeDoctor](https://vibedoctor.io/blog/sec-003-xss-vulnerabilities-react-nextjs) · [Bad Vibes — Georgia Tech](https://news.research.gatech.edu/2026/04/13/bad-vibes-ai-generated-code-vulnerable-researchers-warn)
