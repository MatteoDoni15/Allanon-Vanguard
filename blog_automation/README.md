# Automated Blog Pipeline -- FinTech Content at Scale

A working prototype of the automation pipeline described in the assignment:
keyword in, SEO-optimized, internally-linked, compliance-checked blog post
out -- orchestrated as a LangGraph state machine instead of a linear script,
so that quality-gate retries and human-review fallbacks are first-class
parts of the workflow rather than afterthoughts.

Implements **Part 1** (workflow), **Part 2** (the first three pipeline
steps, plus the internal linking "plus" task), and a working version of
Part 3's first proposal (an LLM-as-judge compliance check, plus a
risk-tiered routing gate) -- see "Part 3" below for exactly what is coded
here versus left as a costed proposal in the submitted report.

## Quick start

```bash
pip install -r requirements.txt
python main.py                     # runs 3 demo keywords in mock mode, no API key needed
python main.py "high-yield savings accounts" "roth ira contribution limits"
python main.py --file keywords_example.txt
pytest tests/ -v                   # 36 unit tests across SEO, linking, compliance, fact-checking, token budgeting, routing
```

By default `LLM_PROVIDER=mock`, so the whole pipeline (generation -> SEO ->
internal linking -> quality gate -> publish) runs with zero setup and zero
API cost, using a deterministic content generator that produces real,
checkable Markdown. To generate with a real model:

```bash
cp .env.example .env
# edit .env: LLM_PROVIDER=anthropic, ANTHROPIC_API_KEY=sk-...
python main.py "your keyword here"
```

Switching to OpenAI is the same -- `LLM_PROVIDER=openai` plus `OPENAI_API_KEY`.
No other code changes are needed; see `src/llm_providers.py`.

## What each module does

| Module | Pipeline step | Responsibility |
|---|---|---|
| `src/voice_profiles.py` | Content Generation | A small set of internal writer-voice profiles (tone, structure habits); deterministically assigned per keyword and kept fixed across retries. Never a public byline -- see Part 1/3 of the report for why. |
| `src/importance_tagger.py` | Keyword Input | Tags each keyword `standard`/`high` importance (tax, rate/fee claims, regulatory topics, competitor comparisons, ...); re-scans the generated draft itself as a safety net. |
| `src/content_generator.py` | Content Generation | Builds an SEO-aware system+user prompt (brand voice, the assigned voice profile, compliance rules, structural requirements) and calls the configured LLM provider. |
| `src/seo_optimizer.py` | SEO Optimization | Pure-Python analysis: word count, Flesch reading ease (`textstat`), keyword density, heading structure, auto-generated meta title/description and slug (`python-slugify`). Produces a 0-100 score and concrete fix suggestions. |
| `src/internal_linking.py` | Internal Linking (plus) | TF-IDF + cosine similarity (`scikit-learn`) against a catalog of existing site content; inserts contextual Markdown links where a related post's topic words actually appear in the new draft. |
| `src/compliance_judge.py` | Content Validation & Compliance | LLM-as-judge node (Part 3 proposal 1) that rates the draft against written company guidelines through the same pluggable `LLMProvider`; fails closed if its response cannot be parsed. |
| `src/embeddings.py` | Fact-checking / duplicate detection | Pluggable embedding interface; `LSAEmbeddingProvider` (TF-IDF + truncated SVD, scikit-learn) runs by default, `VoyageEmbeddingProvider` is the production shape, unused without an API key. |
| `src/vector_index.py` | Fact-checking / duplicate detection | Qdrant client in local mode, two collections (`company_policies`, `published_posts`); guards against the degenerate near-zero vectors a tiny TF-IDF vocabulary can produce for very short or off-topic text. |
| `src/policy_fact_check.py` | Content Validation & Compliance (Part 3 proposal 2, lightweight) | Extracts numeric/absolute claims from the draft, retrieves the closest company-policy passages, and flags either an outright contradiction or a lack of grounding. |
| `src/quality_gate.py` | Risk-tiered publishing gate | Combines the SEO/banned-phrase/length checks, the compliance judge, the policy fact-check, the duplicate check, and the importance tag into one routing decision: publish, retry with feedback, or escalate to a human -- see Part 3 proposal 4 of the report. |
| `src/semantic_duplicate_check.py` | Internal Linking at scale (Part 3 proposal 5) | Queries `published_posts` for very-high similarity; flags likely near-duplicates and incrementally indexes each post once it actually publishes. |
| `src/publisher.py` | Publishing Automation | Converts to HTML, writes a canonical-URL tag, computes a scheduled publish slot, and attaches the path-appropriate AI-disclosure string, then either calls the WordPress REST API or (default) writes the HTML + a full metadata manifest to `outputs/`. Also writes a review packet (with its own disclosure template) for anything routed to `needs_review`. |
| `src/pipeline_graph.py` | Orchestration | Wires the above into a LangGraph `StateGraph`, including the retry loop and the `needs_review` escape hatch; tags importance/voice profile once at keyword input. |

## Why LangGraph instead of a linear script

Two requirements in the assignment are not linear:

1. **Retry-with-feedback.** If the quality gate rejects a draft, the
   workflow must go back to content generation -- with the rejection
   reasons attached -- not just fail. That is a cycle in the graph.
   `pipeline_graph.py` implements it with `add_conditional_edges` and a
   bounded retry counter (`max_generation_retries` in `config.py`), so it
   loops at most twice before escalating instead of looping forever.
2. **Human-in-the-loop fallback.** After retries are exhausted -- or
   immediately, if the topic itself is tagged high-importance regardless
   of how good the draft is (see `src/importance_tagger.py`) -- the graph
   routes to a `needs_review` terminal node rather than publishing
   low-quality or high-risk content unattended. This is also the natural
   place to later add LangGraph's `interrupt()` for a real human-approval
   pause before publish, which matters for a regulated FinTech context
   where marketing/compliance sign-off may be required.

## Part 3 -- what's coded here vs. what stays a proposal in the report

Four of Part 3's proposals in the submitted report are implemented as
running code:

- **Content validation & compliance** (`src/compliance_judge.py`): a real
  LLM-as-judge node, on by default, in the graph between `internal_linking`
  and `policy_fact_check`.
- **Fact-checking via RAG** (`src/policy_fact_check.py`, `src/vector_index.py`,
  `src/embeddings.py`): a real Qdrant vector index, in local mode, over a
  small mock company-policy corpus (`data/company_policies.json`), queried
  for every numeric or absolute claim ("guaranteed", "FDIC", a specific
  rate/fee) the draft makes. It checks for an outright contradiction first
  (a claim asserting something a retrieved policy explicitly prohibits)
  and falls back to a minimum-similarity grounding check otherwise. This
  is a deliberately lighter version of the report's production
  recommendation: embeddings here are TF-IDF + truncated SVD
  (scikit-learn, already a dependency) rather than a neural model, because
  this sandbox cannot reach huggingface.co to download pretrained weights
  and a multi-hundred-MB torch install is not a reasonable default
  dependency regardless. The report's recommendation (Voyage AI's
  voyage-finance-2) and IBM Granite Guardian for the groundedness check
  specifically both remain the proposed production upgrade -- this code
  demonstrates the retrieval-and-check pattern honestly, not a claim that
  it matches their accuracy.
- **Semantic duplicate detection at scale** (`src/semantic_duplicate_check.py`):
  the same vector index, a second collection (`published_posts`), seeded
  from the existing-content catalog and updated incrementally as posts
  publish. Flags very-high similarity as a likely near-duplicate,
  independently of `internal_linking.py`'s TF-IDF-based contextual-link
  suggestions, which are left untouched.
- **Risk-tiered publishing gate** (`src/quality_gate.py` +
  `src/importance_tagger.py`): publish requires the SEO/banned-phrase
  checks, the compliance judge, the policy fact-check, the duplicate
  check, and a `standard` importance tag to all agree; failing any one
  routes to `needs_review`, which writes an actual review packet
  (`*.review.html` / `*.review.manifest.json`) instead of just flipping a
  status flag.

- **Feedback loop** (`src/keyword_priority.py`, `server/db.py` feedback table,
  `web/src/pages/FeedbackPage.jsx`): engagement metrics attached to past posts
  re-rank future keywords by similarity to what performed (TF-IDF + cosine, the
  same machinery as internal linking). Implemented as a minimal-but-real
  mechanism and tested with fake metrics — it proves the loop, not a real
  engagement uplift (which needs production traffic). Tunes *what to write next*,
  never compliance.

What remains a costed proposal in the report rather than code: Voyage AI's
finance-tuned embeddings and IBM Granite Guardian specifically (both need
an API key/model host this sandbox cannot provide), Docling for ingesting
real (as opposed to mock) policy PDFs, a Neo4j extension for claims that
depend on multiple interacting conditions, the two heavier feedback-loop
levers (threshold tuning and generation guidance), and a trained compliance
classifier (which needs the post/engagement history to accumulate first).
See the submitted report (`DESIGN_DOCUMENT.md`, Part 3 and Appendix A) for
the full reasoning and the alternatives considered for each.

## Scaling to 700 posts/month

The single-keyword `run_for_keyword()` call is the unit of work a
scheduler would fan out: a queue (e.g. SQS/Pub-Sub) holding one message
per approved keyword, consumed by N worker processes each running this
same graph, writing results to the CMS instead of `outputs/`. At ~23
posts/day, even modest parallelism (5-10 workers) clears the volume with
headroom for retries. See the submitted report for the full
input/processing/output architecture diagram and tool recommendations
(Airflow/Prefect for scheduling, a vector DB for the RAG step, and a
human-review queue in the CMS for anything routed to `needs_review`).

## Project layout

```
blog_automation/
├── main.py                  # CLI entry point
├── config.py                 # all tunable thresholds, env-driven
├── requirements.txt
├── .env.example
├── keywords_example.txt      # sample keyword list for --file
├── run.ps1                   # one-shot launcher for backend + frontend
├── data/
│   ├── existing_site_content.json   # mock CMS export for internal linking
│   └── company_policies.json         # mock policy corpus for fact-checking
├── src/
│   ├── state.py               # shared LangGraph state schema
│   ├── llm_providers.py        # Anthropic / OpenAI / Ollama / Mock, pluggable
│   ├── embeddings.py            # LSA (default) / Voyage (production shape)
│   ├── voice_profiles.py        # internal writer-voice profiles
│   ├── importance_tagger.py     # high/standard topic-importance tagging
│   ├── content_generator.py
│   ├── seo_optimizer.py
│   ├── internal_linking.py
│   ├── compliance_judge.py      # LLM-as-judge compliance node
│   ├── vector_index.py           # Qdrant local-mode index (2 collections)
│   ├── policy_fact_check.py      # lightweight RAG fact-check node
│   ├── policy_store.py          # CRUD write-path for company policies
│   ├── web_research.py          # DuckDuckGo context retrieval (non-blocking)
│   ├── web_fact_check.py        # DuckDuckGo external claim verification
│   ├── semantic_duplicate_check.py
│   ├── keyword_priority.py      # feedback loop: re-rank keywords by engagement
│   ├── token_budget.py          # input-token budgeting / chunking
│   ├── quality_gate.py           # risk-tiered publish/retry/review routing
│   ├── publisher.py
│   ├── logging_config.py
│   └── pipeline_graph.py        # the LangGraph wiring
├── server/                    # FastAPI backend (HTTP + SSE) + SQLite persistence
│   ├── app.py
│   └── db.py
├── web/                       # React + Vite SPA (Generate / Blog / Policies / Feedback)
├── outputs/                   # generated HTML + JSON manifests land here
└── tests/
    ├── test_seo_optimizer.py
    ├── test_internal_linking.py
    ├── test_voice_and_importance.py
    ├── test_compliance_judge.py
    ├── test_vector_index.py
    ├── test_token_budget.py
    └── test_quality_gate_routing.py
```
