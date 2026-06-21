# Automating the Creation of 700 Blogs Monthly — Design Document

**FinTech content automation — end-to-end design, implementation, and Gen-AI/ML proposals**

This is the submission document for the assignment. It covers all four parts:
the workflow (Part 1), what is implemented in code (Part 2), the Generative-AI /
ML methods used to evaluate and improve content quality (Part 3), and how the
components connect into one scalable flow (Part 4). It is paired with a working
Python project (`README.md` for how to run it) and a technical implementation
report (`report.md`).

Throughout, a clear line is drawn between **what runs as code today** and **what
is a costed proposal** for production — the latter mostly where a managed
API/model or real production data is required that a local prototype cannot
honestly stand in for.

---

## 0. Problem framing

A FinTech company needs to publish ~700 blog posts/month (~23/day), each
**relevant, SEO-optimized, on-brand, and compliant**, with publication
automated end-to-end. In a regulated domain, "automated" cannot mean
"unsupervised for everything": the design must auto-publish the safe majority
while routing the genuinely risky minority to a human, without a person in the
loop for every post.

Three forces shape every decision below:

1. **Scale** — 700/month rules out anything with meaningful per-post manual work
   or expensive per-call SaaS where a local computation suffices.
2. **Compliance risk** — financial-promotion rules (no guaranteed returns, no
   "risk-free", no undue urgency, accurate fee/rate claims) make a pure
   "generate-and-publish" loop unacceptable.
3. **Quality at volume** — 700 near-identical posts would be an SEO liability and
   an obvious "AI fingerprint"; variety and de-duplication are first-class
   concerns, not polish.

---

## Part 1 — Key steps of the workflow

The pipeline is the following ordered set of steps. Each is implemented as a
node in a LangGraph state machine (Part 4).

| # | Step | Role | Technical requirements |
|---|------|------|------------------------|
| 0 | **Keyword input & tagging** | Accept the target keyword; tag topic *importance* (standard/high) and assign an internal *writer-voice profile*. | Keyword source (content calendar / queue); a sensitivity tag list or human-curated tags; deterministic voice assignment. |
| 1 | **Web research** | Pull fresh, real context (recent figures, facts) for the keyword so the draft isn't purely model-memory. | Web search API (DuckDuckGo here, no key); token budgeting of the retrieved context. |
| 2 | **Content generation** | Produce a structured, on-brand, SEO-aware Markdown draft from the keyword. | LLM provider (Claude/GPT/local); prompt carrying brand voice, compliance rules, structural targets; input-token budget control. |
| 3 | **SEO optimization** | Score and enrich the draft: readability, keyword density, headings, meta title/description, slug. | Readability lib (textstat), slug lib; deterministic scoring; concrete fix suggestions fed back on retry. |
| 4 | **Internal linking** (the "plus") | Insert contextual links from the new post to existing site content to improve SEO and navigation. | Similarity over a CMS content catalog (TF-IDF/cosine); safe in-text insertion that avoids headings/links. |
| 5 | **Validation & compliance** | Check the draft against written company guidelines and company policies before it can publish. | LLM-as-judge; a RAG index over company policy documents; deterministic banned-phrase checks. |
| 6 | **Quality gate & routing** | One decision: auto-publish, retry-with-feedback, or escalate to a human. | Thresholds in config; bounded retry loop; risk-tier override. |
| 7 | **Publishing automation** | Convert to HTML, attach SEO/canonical/disclosure metadata, schedule, and publish (or write a review packet). | CMS API (WordPress REST example); scheduling window; AI-disclosure; dry-run mode for testing. |

> **Scope note on Step 0 — keyword *discovery* vs keyword *input*.** The prototype
> takes the target keyword as **input** (file / CLI / queue) and the feedback loop
> (Part 3, Proposal 3) *re-ranks* an existing candidate set by past engagement. It
> does **not** actively *discover* new topics. Active discovery — surfacing trending
> FinTech topics from a **news search (Brave Search API)** or by **scraping known
> trusted sources** — is a deliberate, costed proposal (see Appendix C.1), left out
> of the running code for cost/stability reasons, not difficulty. This is the one
> Part-1 step with no active counterpart in code, and it is called out here rather
> than left implicit.

---

## Part 2 — What is implemented in Python

The assignment asks for at least the first three steps coded, with internal
linking as a plus. **All of steps 1–7 are implemented and runnable.** The
project runs end-to-end with **zero setup and zero API cost** in `mock` mode
(a deterministic content generator), so the entire flow — generation → SEO →
linking → compliance → gate → publish — can be exercised and unit-tested
without any key. 36 unit tests cover SEO, linking, compliance parsing, the
vector index, token budgeting, and the routing logic.

Key modules (full table in `README.md`, deep dive in `report.md`):

- **Content generation** — `src/content_generator.py`, with a pluggable
  `LLMProvider` interface (`src/llm_providers.py`): Anthropic (default), OpenAI,
  Ollama (local, per-task model routing), and Mock. Swapping providers is a
  config change, not a code change.
- **SEO** — `src/seo_optimizer.py`: pure-Python **on-page** SEO (readability,
  keyword density, heading structure, meta title/description, slug) — no paid SEO
  SaaS, so it costs nothing per post at 700/month. It deliberately does **not**
  cover off-page / SERP factors (search volume, competitor gap, backlinks): those
  belong to the keyword-discovery layer (Appendix C.1), not to per-post scoring.
- **Internal linking** — `src/internal_linking.py`: TF-IDF + cosine similarity
  (scikit-learn) against `data/existing_site_content.json`.
- **Compliance & fact-check** — `src/compliance_judge.py`,
  `src/policy_fact_check.py`, `src/vector_index.py` (Part 3, below).
- **Publishing** — `src/publisher.py`: WordPress REST API target, `dry_run`
  default writes HTML + a metadata manifest to `outputs/`.
- **Orchestration** — `src/pipeline_graph.py` (Part 4, below).

The choice to make `mock` the default is deliberate: it lets the design be
**verified as a system**, not just read, and keeps the SEO/linking/routing logic
honest because it runs against real generated Markdown.

---

## Part 3 — Generative-AI / ML methods to evaluate and improve quality

This is where most design effort went. Five proposals; **all five now have
running code** — the feedback loop as a minimal-but-real mechanism, the other
four more fully. The implemented ones are deliberately honest about where the
prototype's local substitutes differ from the recommended production
components, and about what each does and does *not* prove.

### Proposal 1 — Content validation & compliance (LLM-as-judge) — IMPLEMENTED

`src/compliance_judge.py` is a graph node that asks the configured LLM to rate
the draft **only** against written `compliance_guidelines` (config.py) and return
strict JSON `{"passed": bool, "reasons": [...]}`.

- **Why LLM-as-judge, not a trained classifier:** there is no labelled corpus of
  "compliant / flagged" historical posts to train on yet, and a judge works
  immediately from written guidelines while returning *reasons* that feed
  straight back into the retry-with-feedback loop (Proposal 4).
- **Fail-closed:** an unparseable judge response is treated as *needs review*,
  never silently passed — the correct default in a regulated domain.
- **Token-safe:** an over-budget draft is *chunked and judged chunk-by-chunk*,
  never summarised (a summary could drop the exact phrase the check exists to
  catch); verdicts merge with logical AND.
- **Production upgrade:** fine-tune a smaller classifier once enough
  human-labelled outcomes exist, using the judge to bootstrap labels; keep the
  LLM judge as a second opinion on disagreement.

### Proposal 2 — Fact-checking via RAG — IMPLEMENTED (lightweight)

`src/policy_fact_check.py` + `src/vector_index.py` + `src/embeddings.py`. The
draft's numeric/absolute claims (a rate, a fee, "guaranteed", "FDIC", "deposit
protection") are extracted and each is checked against a **Qdrant vector index**
of company-policy documents (`data/company_policies.json`). A claim is flagged if
it (a) retrieves nothing, (b) is below a minimum grounding similarity, or (c)
**contradicts** a retrieved policy (explicit negation cues, e.g. a "guaranteed"
claim against a "not guaranteed" policy).

- **What runs:** real retrieval-and-check, end to end, on a real (mock-content)
  policy corpus.
- **Honest gap — embeddings:** the prototype embeds with **TF-IDF + Truncated
  SVD (LSA, scikit-learn)**, not a neural model. This is a real technique that
  captures *some* latent similarity beyond word overlap, fully offline, and uses
  a dependency the project already has. It is **not** as accurate as a neural
  embedding, and the code says so.
- **Production upgrade:** **Voyage AI `voyage-finance-2`** (Anthropic's
  recommended embeddings partner, finance-tuned) for retrieval, and **IBM Granite
  Guardian** for the groundedness/entailment step — which can distinguish
  *supported* from *contradicted* from *merely unrelated*, where similarity alone
  cannot. **Docling** to ingest real policy PDFs instead of a curated JSON.
- **Why a vector DB at all (Appendix A):** see below.

### Proposal 3 — Feedback loop from published-blog results — IMPLEMENTED (minimal mechanism)

The lowest-risk lever of the loop is now **running code**:
`src/keyword_priority.py` + a `feedback` table (`server/db.py`) + two endpoints
(`POST /api/feedback`, `POST /api/keyword-priorities`) + a frontend page
(`web/src/pages/FeedbackPage.jsx`).

- **What it does, end to end:**
  1. Engagement metrics (impressions, clicks, dwell time, conversions) are
     attached to a published post via `POST /api/feedback` and stored in the DB.
  2. `engagement_score()` blends them into one value (CTR-dominant).
  3. Past posts' scores are **centered on the mean** — above-average → positive
     weight, below-average → negative.
  4. A candidate keyword's priority is the **similarity-weighted sum** of those
     weights (TF-IDF + cosine, the *same* machinery as internal linking — no new
     model). Candidates similar to winners rise; candidates similar to losers
     fall. Each result carries a plain-language rationale.
- **Tested with fake data** (no real traffic exists yet): seeding a
  high-engagement "savings" post, a mediocre "budgeting" one, and a poor "crypto"
  one ranks future keywords exactly as expected — savings topics to the top,
  crypto to the bottom. This proves the **mechanism**, and is explicit that it
  does *not* prove a real engagement uplift (which needs production data).
- **Guardrail:** the loop tunes *what to write next*, **never compliance**.
  Compliance thresholds stay human-owned; a click-through metric is never allowed
  to talk the system into a riskier claim.
- **Missing piece — automatic metric ingestion:** the engagement metrics are
  **entered by hand** (via the UI / `POST /api/feedback`), not pulled
  automatically. There is **no integration that ingests real impressions/clicks
  from Google Analytics (GA4), Google Search Console (GSC), or the CMS** — which
  is also why it can only be tested on fake data today. The *learning mechanism*
  is real; the *automatic ingestion of real metrics* is the missing piece. For a
  serious / production deployment I would add a scheduled connector that imports
  real metrics from **GA4 / GSC / the CMS** into the `feedback` table, closing the
  loop with no manual step — only then does it prove a real engagement uplift
  rather than just the correctness of the mechanism.
- **Two further levers, still proposed** (need more data / production wiring):
  - **Threshold tuning** — replace fixed guesses (the publish-time window in
    `config.py`, the SEO cut-off) with A/B-tested learned values.
  - **Generation guidance** — feed back which voice profiles / structures
    correlate with engagement as *soft* prompt preferences (never hard rules that
    would re-homogenize output).
- **Why the DB matters beyond this:** the same accumulating
  `{post → engagement}` history is the dataset that later trains the cheap
  classifier of Appendix C.4 — this feature is already collecting it.

### Proposal 4 — Risk-tiered publishing gate (human-in-the-loop) — IMPLEMENTED

`src/quality_gate.py` + `src/importance_tagger.py`. The gate combines **two
independent axes** into one routing decision:

1. **Quality axis** — banned phrases, SEO score, minimum length, the compliance
   judge, the policy fact-check, the web fact-check, and the duplicate check. Any
   failure with retries remaining loops back to generation *with the specific
   reasons attached*; after `max_generation_retries`, it escalates.
2. **Importance axis** — a topic tagged **high** importance (tax, rates/fees,
   deposit protection, regulatory/legal, competitor comparisons, unannounced
   product news) **always** routes to human review, *regardless of how good the
   draft is*. This is not a quality failure and never triggers a retry — a
   perfect draft on a sensitive topic still needs sign-off because of *what it
   is*, not *how it was written*.

The `needs_review` branch writes a real **review packet** (`*.review.html` +
`*.review.manifest.json`) with its own AI-disclosure template — giving a human
queue something concrete to act on, not just a status flag. A reviewer then
**approves** the post from the UI (`POST /api/blogs/{id}/approve`,
"✅ Approva e pubblica"), which flips its status to `published` and stamps who
approved it and when — closing the human-in-the-loop. This is also the natural
place to later add LangGraph's `interrupt()` for a true in-graph approval pause.

### Proposal 5 — Semantic duplicate detection at scale — IMPLEMENTED

`src/semantic_duplicate_check.py`. The scaling evolution of internal linking:
the *same* embedding similarity, at a *higher* threshold (0.90), against a second
Qdrant collection (`published_posts`) seeded from the existing-content catalog
and grown **incrementally** as each post publishes. Flags likely near-duplicates
before they can be published — critical at 700/month, where templated generation
otherwise drifts toward sameness (a problem we hit and fixed honestly in the mock
generator rather than hiding it by raising the threshold).

---

## Part 4 — The integrated workflow

### Why LangGraph, not a linear script

Two requirements are **not linear**, and a `StateGraph` models them natively
where a function chain would need hand-rolled while-loops:

1. **Retry-with-feedback** is a *cycle*: `quality_gate → increment_retries →
   generate_content`, bounded by `max_generation_retries`, with rejection
   reasons carried in the shared state.
2. **Human-in-the-loop** is a *conditional terminal branch*: `needs_review`,
   reachable both on exhausted retries and directly on a high-importance tag.

### The flow (Input → Processing → Output)

```
INPUT
  keyword  ─►  importance tag + voice profile

PROCESSING  (LangGraph StateGraph, shared PipelineState)
  web_research ─► generate_content ─► seo_optimize ─► internal_linking
        ▲                                                   │
        │ retry (+ reasons)                                 ▼
        │                                            compliance_judge
        │                                                   │
        └──────────── quality_gate ◄── duplicate_check ◄── web_fact_check ◄── policy_fact_check
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
         publish     needs_review    (retry)
            │             │
OUTPUT      ▼             ▼
   CMS / outputs/    review packet + human queue
   + index into published_posts (for future dedup)
```

### Scaling to 700 posts/month

The unit of work is one `run_for_keyword()` call. To scale:

- **Fan-out:** a queue (SQS / Pub-Sub), one message per approved keyword,
  consumed by **N worker processes** each running this same graph. At ~23/day,
  5–10 workers clear the volume with headroom for retries.
- **Scheduling/orchestration at the fleet level:** Airflow or Prefect to trigger
  batches, handle retries/backfills, and surface failures.
- **State & data:** the in-process Qdrant becomes a **managed/self-hosted Qdrant**
  shared across workers (one-line client change — see Appendix A); generated
  posts go to the **CMS** instead of `outputs/`; a **human-review queue** in the
  CMS handles everything routed to `needs_review`.
- **Cost control:** pure-Python SEO and a local embedder mean the only per-post
  paid call is the LLM generation (and the optional judge) — everything else is
  free compute, which matters a lot at this volume.

---

## Appendix A — Vector DB choice (local mode now, managed later)

The RAG fact-check and the duplicate detector both need vector search. The
prototype uses **Qdrant in local mode** (`QdrantClient(":memory:")`) — an
in-process client, no server to run, suitable up to ~20k vectors (far more than
either collection needs here).

This is a deliberate choice, not a placeholder: the **same `QdrantClient` API**
works identically against a managed or self-hosted instance, so the move to
production is `QdrantClient(":memory:")` → `QdrantClient(url=...)` — one line, not
a rewrite. The embedder is fit once per process (the expensive step) and cached
as a singleton; when the policy set changes, the index is rebuilt so a new
policy's vocabulary actually enters the vector space (`reset_knowledge_base_index`).

A neural embedder (Voyage) removes the need to *fit* at all (the API embeds
directly), which also removes the LSA "degenerate vector" edge case the prototype
has to guard against for very short or off-topic text.

---

## Appendix B — Honest limitations of the prototype

- **Embeddings are LSA, not neural** — see Proposal 2. The pattern is real; the
  accuracy is not production-grade.
- **No real engagement data** — the feedback loop (Proposal 3) is implemented as
  a minimal-but-real mechanism (keyword re-ranking), but it is **tested only on
  fake metrics**: it proves the mechanism, not a real engagement uplift, which
  needs production traffic.
- **Mock policy corpus** — `company_policies.json` is illustrative; production
  needs real documents (Docling ingestion).
- **In-process index** — fine for a prototype / single batch; production needs a
  shared managed instance for multi-worker fan-out.
- **Single-lock generation in the web server** — the API serialises generation
  because nodes read a global provider setting; correct for a local testing tool,
  replaced by per-worker isolation at scale.

These are stated up front because, in a compliance context, knowing exactly where
a system's guarantees end is itself part of the design.

---

## Appendix C — Pragmatic prototyping choices and their production deltas

Every choice below was made to keep the prototype **free, local, and runnable
with zero setup**. Each is the *right* call for a take-home prototype and the
*wrong* call for a company deployment — so each is paired with what I would
actually do in production. Stating the delta explicitly is the point: nothing
here is a hidden assumption.

### C.1 Web research & keyword discovery — DuckDuckGo now, news search / scraping in prod

- **Prototype:** web research and the web fact-check use the **DuckDuckGo** Python
  client (`ddgs`) because it is a working, **free, key-less** service — good
  enough to prove the retrieval-and-inject pattern end to end.
- **Production — two complementary upgrades, both deliberately left out of the
  prototype for cost/stability reasons, not difficulty:**
  - **News-driven keyword discovery.** Today the pipeline takes keywords as input
    (file / CLI / queue) and the feedback loop only *re-ranks* an existing
    candidate set; it does not *discover* fresh topics. In production I would feed
    the candidate set from a **news search via the Brave Search API** (a paid,
    stable, ToS-clean API with proper rate limits and result quality — the
    low-risk default for a company), surfacing trending FinTech topics worth
    writing about before they are ranked by the feedback loop.
  - **Full-page scraping for grounding.** Instead of snippets, **crawl and parse
    full pages** — either from open search results or from a curated list of
    known, trusted sources — using an **open-source crawler of the Crawl4AI /
    Firecrawl family** (open source, so production is "add the dependency and wire
    it in", not a rewrite). This grounds the draft in much richer, fresher source
    material than snippets allow.
- **Why it is a proposal and not code here:** the scraping path was prototyped but
  **not committed**. I tested reading the scraped pages with **local Gemma models
  (4B and 2B) via Ollama**, but my machine ran out of resources / errored on the
  larger context, so rather than ship code I could not actually run end to end I
  left it as a costed proposal. The principle holds throughout this submission:
  **no untested code in the repo.** Brave Search is likewise a paid API I did not
  want to key in for a take-home.
- **Why it matters:** the quality of the web-grounded facts — and of the topic
  selection itself — is capped by the search/crawl layer; DuckDuckGo snippets are
  the floor, not the ceiling.

### C.2 LLM — tested locally with one small model only

- **Prototype:** real generation was validated **only with `qwen2.5:1.5b` via
  Ollama**, because it is the single model of *satisfactory quality that runs on
  my local machine*. The pipeline was **not** exercised against hosted API models
  (Claude / GPT) in this submission — though the provider abstraction
  (`src/llm_providers.py`) makes that a config switch, not a code change, and the
  default deterministic `mock` provider covers the logic in tests.
- **Production:** use a hosted, higher-capability model (Claude as default) for
  content and the compliance judge, where output quality and instruction-following
  are materially better. The small local model is a development convenience, not
  the production writer.
- **Why it matters:** the prototype proves the *plumbing* and the *control flow*;
  it does not prove production-grade *prose quality*, which depends on a model not
  tested here.

### C.3 Embeddings — scikit-learn (LSA) now, never in production

- **Prototype:** the vector index embeds with **TF-IDF + Truncated SVD (LSA),
  scikit-learn** — deliberately, to **avoid adding another model** (no weight
  download, no torch, no extra service) on top of an already dependency-rich
  prototype.
- **Production:** with a **much larger policy corpus**, I would **never** use LSA.
  LSA must be refit on the whole corpus and degrades as vocabulary grows; a
  proper neural embedder (**Voyage `voyage-finance-2`**, or a self-hosted
  sentence model) embeds directly, scales, and captures real semantic similarity.
- **Why it matters:** LSA is fine for a handful of policies and a demo; it is not
  a retrieval backbone for a real, growing compliance corpus.

### C.4 No classification model yet — by design, because data comes first

- **Prototype:** compliance/quality use an **LLM-as-judge**, not a trained
  classifier, because **a good classifier needs a lot of labelled data** that does
  not exist at day zero.
- **The plan, and why the DB matters:** every generated post is **persisted to a
  database** (`server/db.py`, full pipeline state included). That store is not
  just output — it is the **historical dataset** that, once large enough, lets us
  train a classifier (compliance pass/fail, quality scoring) that is **both more
  accurate and far cheaper per call than an LLM**. The LLM judge bootstraps the
  labels; the accumulated history graduates the cheap model in.
- **Why it matters:** this is the honest sequencing — LLM now for cold-start,
  classifier later once the data earns it. The architecture is already collecting
  the data for that step.

---

## Deliverables map

| Assignment deliverable | Where |
|---|---|
| Description of the workflow | This document (Parts 1 & 4) + `report.md` |
| Working Python project | The repository; `README.md` to run it; `mock` mode = zero setup |
| Proposals for Gen-AI / ML | This document, Part 3 (5 proposals, all 5 with running code) |
| Short presentation (5–10 min) | `PRESENTATION.md` |
