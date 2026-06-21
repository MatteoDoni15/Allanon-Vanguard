# Presentation — Automating 700 Blogs/Month (5–10 min)

Speaker notes + slide outline. ~9 slides, ~1 minute each, with a 60–90s live
demo in the middle. Timings are guidance, not a script.

---

## Slide 1 — Title & framing (0:45)

**Automating the creation of 700 FinTech blogs/month — end to end.**

- The ask: ~23 posts/day, each relevant, SEO-optimized, on-brand, **and
  compliant**, with publication automated.
- The one tension that shapes everything: in a **regulated** domain, "automated"
  can't mean "unsupervised for every post". The goal is to **auto-publish the
  safe majority and route the risky minority to a human** — without a person in
  the loop for each one.

> Say: "Everything in this design follows from that one tension."

---

## Slide 2 — The workflow (Part 1) (1:00)

Keyword → **research → generate → SEO → internal linking → compliance/fact-check
→ quality gate → publish**.

- Each box is a real step with a clear role and tech requirement (table in the
  design doc).
- Two boxes are not in a naive "generate-and-publish" pipeline and are the whole
  point: **fact-check/compliance** and the **quality gate**.

> Say: "Steps 1–3 were the minimum asked; I built all seven, including
> publishing."

---

## Slide 3 — Why an orchestrated graph, not a script (Part 4) (1:00)

Two things are **not linear**:

1. **Retry-with-feedback** — a rejected draft loops back to generation *with the
   reasons attached* (a cycle).
2. **Human-in-the-loop** — escalate to review after failed retries, or
   immediately for high-risk topics (a conditional terminal branch).

→ Built as a **LangGraph state machine**. Show the graph diagram.

> Say: "These are cycles and branches — exactly what a graph models natively and
> a linear script fakes with while-loops."

---

## Slide 4 — Live demo (1:30)

Run the web UI (`run.ps1`), generate one post in **mock mode** (no API key):

1. Watch the **node-by-node timeline** stream live (SSE).
2. Open the result: rendered article + SEO score + compliance/fact-check verdicts
   + internal links + **the intermediate outputs** (web research, raw draft).
3. Open **Policies**: add a policy, show it's stored and goes into the vector
   index for the next run.
4. Open **Feedback**: attach fake metrics to a couple of posts, hit *recompute*,
   show future keywords re-ranked by what performed.

> Fallback if live fails: screenshots. Keep it to 90 seconds.

---

## Slide 5 — Content quality at volume (Part 2 + 3) (1:00)

The real risk at 700/month isn't writing one good post — it's **700 that aren't
all the same**.

- **Voice profiles** — deterministically varied tone/structure per keyword, fixed
  across retries (no single "AI fingerprint").
- **SEO** — pure-Python (textstat, density, headings, meta, slug), **zero per-post
  cost**.
- **Semantic duplicate detection** — flags near-duplicates before publish
  (Proposal 5).

> Say: "I actually hit the sameness problem with the mock generator and fixed it,
> rather than hiding it by loosening the duplicate threshold."

---

## Slide 6 — Compliance & fact-checking (Part 3, the core) (1:15)

Two layers, both running code:

- **LLM-as-judge** (Proposal 1) — rates the draft against written guidelines,
  returns *reasons* that feed the retry loop, **fails closed** on an unparseable
  answer.
- **RAG fact-check** (Proposal 2) — every numeric/absolute claim ("guaranteed",
  "FDIC", a rate) is checked against a **Qdrant** index of company policies;
  catches outright **contradictions**, not just missing grounding.

> Honesty slide: embeddings here are **LSA (TF-IDF+SVD)**, offline; production
> upgrade is **Voyage `voyage-finance-2` + IBM Granite Guardian**. The *pattern*
> is real; I'm not claiming the accuracy.

---

## Slide 7 — The risk-tiered gate (Proposal 4) (1:00)

One decision, **two axes**:

- **Quality** — fails → retry with feedback, then escalate.
- **Importance** — a sensitive topic **always** goes to a human, *even if the
  draft is perfect*. Not a quality failure; what it *is*, not how it's *written*.

`needs_review` writes a real **review packet** for a human queue, not just a flag.

> Say: "This is how you automate aggressively and stay safe — the gate decides
> what's allowed to publish itself."

---

## Slide 8 — Scaling & the feedback loop (Part 3 & 4) (1:00)

- **Scale:** one `run_for_keyword()` = one queue message; **N workers**; Airflow/
  Prefect to orchestrate; managed Qdrant (one-line change); CMS + human-review
  queue. 5–10 workers clear 23/day with headroom.
- **Feedback loop (Proposal 3, implemented):** engagement metrics → an
  engagement score → **future keywords re-ranked** by similarity to what
  performed (same TF-IDF as internal linking). Endpoints + DB table + a frontend
  page. **Tested on fake data** (savings up, crypto down) — proves the
  *mechanism*; a real uplift needs real traffic. Tunes *what to write next*,
  **never compliance**.

---

## Slide 8b — Pragmatic choices & production deltas (1:00)

Four choices made to keep the prototype **free, local, zero-setup** — each paired
with what I'd actually do in production (full detail: Design Doc, Appendix C):

| Prototype (now) | Production (real deployment) |
|---|---|
| **DuckDuckGo** search (free, key-less) | **Brave Search API**, or aggressive full-page **crawling/scraping** (Firecrawl/Crawl4AI-style) |
| Tested only with **`qwen2.5:1.5b`** locally (only good model my PC runs) | Hosted **Claude/GPT** — config switch, not code; quality not proven here |
| **scikit-learn LSA** embeddings (avoid adding a model) | **Voyage `voyage-finance-2`** / neural embedder — LSA never used with a big corpus |
| **No classifier** — LLM-as-judge (no labelled data yet) | Train a **cheaper, more accurate classifier** once the **post DB** has built up history |

> Say: "The DB isn't just output — it's the dataset that lets a cheap classifier
> replace the LLM judge later. LLM now for cold-start, classifier when the data
> earns it."

---

## Slide 9 — What's code vs proposal, and close (0:45)

| Implemented (runs today) | Costed proposal |
|---|---|
| All 7 pipeline steps, end-to-end | Voyage + Granite Guardian |
| LLM-as-judge compliance | Docling PDF ingestion |
| RAG fact-check (LSA) | Threshold tuning / generation guidance |
| Risk-tiered gate + human review | Managed Qdrant, multi-worker fleet |
| Feedback loop (keyword re-ranking) | Compliance classifier (needs more data) |
| Semantic dedup, 30 unit tests | |

> Close: "It runs end-to-end today with zero setup, and every gap is a labelled
> proposal — not a hidden assumption. In a compliance context, knowing exactly
> where the guarantees end is part of the design."

---

### Q&A — likely questions, short answers

- **Why mock by default?** So the system can be *verified*, not just read — and
  it keeps SEO/linking/routing honest against real generated Markdown.
- **Why LSA and not sentence-transformers?** Offline sandbox can't download
  weights; LSA is a real, dependency-free substitute. Production = Voyage.
- **What stops it publishing something non-compliant?** Three independent checks
  (banned phrases, LLM judge, policy RAG) must all agree, plus a topic-importance
  override — any one failing escalates to a human.
- **Could the feedback loop change a compliance threshold?** No — by design it
  tunes prioritization and presentation only; compliance stays human-owned.
- **Which models did you actually test?** Real generation only with
  `qwen2.5:1.5b` locally (the best model my PC runs); hosted Claude/GPT is a
  config switch, untested here. Logic is covered by the deterministic mock + 30
  tests.
- **Why no trained classifier for compliance?** It needs labelled data we don't
  have at day zero. The post DB is accumulating exactly that history; once it's
  big enough, a classifier replaces the LLM judge — cheaper and more accurate.
- **Why DuckDuckGo and not a real search API?** Free and key-less, enough to
  prove the pattern. Production = Brave Search API or heavy crawling/scraping.
