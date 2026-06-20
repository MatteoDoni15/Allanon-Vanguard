"""
Shared state schema for the LangGraph pipeline.

LangGraph passes one mutable state object between nodes. Each node reads
the fields it needs and returns a partial dict of updates, which
LangGraph merges into the running state. Defining it explicitly (rather
than passing loose dicts) keeps every node's contract obvious and makes
the graph easy to extend later (e.g. add an `image_alt_text` field
without touching unrelated nodes).
"""

from __future__ import annotations
from typing import TypedDict, Optional


class SEOReport(TypedDict, total=False):
    score: int                       # 0-100 overall SEO score
    word_count: int
    flesch_reading_ease: float
    keyword_density_pct: float
    has_meta_title: bool
    has_meta_description: bool
    meta_title: str
    meta_description: str
    slug: str
    issues: list[str]                # human-readable list of problems found
    suggestions: list[str]           # actionable fixes


class LinkSuggestion(TypedDict):
    anchor_text: str
    target_url: str
    target_title: str
    similarity: float


class QualityResult(TypedDict, total=False):
    passed: bool
    reasons: list[str]


class PipelineState(TypedDict, total=False):
    # --- input -----------------------------------------------------------
    keyword: str
    target_audience: str
    importance_tier: str             # "standard" | "high" -- tagged at keyword input
    voice_profile: str                # internal style profile id, fixed across retries

    # --- web research (DuckDuckGo snippets fetched before content generation) --
    web_research_context: str

    # --- content generation ------------------------------------------------
    raw_markdown: str
    title: str

    # --- SEO optimization --------------------------------------------------
    seo_report: SEOReport
    optimized_markdown: str

    # --- internal linking ----------------------------------------------
    internal_links: list[LinkSuggestion]
    linked_markdown: str

    # --- compliance judge (LLM-as-judge, Part 3 proposal 1) -------------
    compliance: QualityResult

    # --- lightweight RAG fact-check against company policies (Part 3 proposal 2) --
    fact_check: QualityResult

    # --- external web fact-check via DuckDuckGo (after policy fact-check) ----
    web_fact_check: QualityResult

    # --- semantic duplicate detection against published posts (Part 3 proposal 5) --
    duplicate_check: QualityResult

    # --- quality gate / compliance -------------------------------------
    quality: QualityResult
    retries: int

    # --- publishing -------------------------------------------------------
    publish_result: dict
    status: str                      # "draft" | "published" | "needs_review" | "rejected"
    canonical_url: str
    scheduled_publish_at: str
    ai_disclosure: str
