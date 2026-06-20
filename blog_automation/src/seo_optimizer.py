"""
Step 3 of the pipeline: SEO Optimization.

Pure-Python SEO analysis -- no external SEO SaaS API required, which
matters at 700 posts/month where per-call API pricing would add up
fast. Uses:
  - textstat        for readability (Flesch Reading Ease)
  - python-slugify   for clean, URL-safe slugs
  - simple regex/counting for keyword density and structural checks

The analyzer never blocks the pipeline by itself -- it scores the draft
and emits actionable `suggestions`. The actual go/no-go decision is the
job of the separate quality_gate module (Part 3 of the assignment),
which can use this score as one of its signals.
"""

from __future__ import annotations

import re
import textstat
from slugify import slugify

from config import settings
from src.logging_config import get_logger
from src.state import PipelineState, SEOReport

logger = get_logger("seo_optimizer")


def analyze_and_optimize(state: PipelineState) -> dict:
    """LangGraph node: reads `raw_markdown`, returns `seo_report` + `optimized_markdown`."""
    logger.info("Analyzing SEO metrics")
    markdown = state["raw_markdown"]
    keyword = state["keyword"]
    title = state["title"]

    word_count = len(re.findall(r"\b\w+\b", markdown))
    flesch = textstat.flesch_reading_ease(markdown)
    density = _keyword_density(markdown, keyword)
    h2_count = len(re.findall(r"^##\s+", markdown, flags=re.MULTILINE))
    h1_count = len(re.findall(r"^#\s+", markdown, flags=re.MULTILINE))

    logger.info(f"SEO metrics - words: {word_count}, flesch: {flesch:.1f}, density: {density:.2f}%, H1: {h1_count}, H2: {h2_count}")

    issues: list[str] = []
    suggestions: list[str] = []

    if word_count < settings.min_word_count:
        logger.warning(f"SEO: Word count {word_count} below minimum {settings.min_word_count}")
        issues.append(f"Word count {word_count} is below the {settings.min_word_count} minimum.")
        suggestions.append("Expand one or two H2 sections with a concrete example.")
    if word_count > settings.max_word_count:
        logger.warning(f"SEO: Word count {word_count} exceeds maximum {settings.max_word_count}")
        issues.append(f"Word count {word_count} exceeds the {settings.max_word_count} maximum.")
        suggestions.append("Trim repetitive sentences in the middle sections.")

    if density < settings.target_keyword_density_min:
        logger.warning(f"SEO: Keyword density {density:.2f}% too low")
        issues.append(f"Keyword density {density:.2f}% is too low.")
        suggestions.append(f"Mention '{keyword}' a couple more times naturally.")
    elif density > settings.target_keyword_density_max:
        logger.warning(f"SEO: Keyword density {density:.2f}% too high (stuffing risk)")
        issues.append(f"Keyword density {density:.2f}% risks keyword stuffing.")
        suggestions.append(f"Replace some repetitions of '{keyword}' with synonyms.")

    if flesch < settings.min_flesch_reading_ease:
        logger.warning(f"SEO: Flesch score {flesch:.1f} below readability threshold")
        issues.append(f"Flesch Reading Ease {flesch:.1f} is hard to read for a general audience.")
        suggestions.append("Shorten long sentences and prefer plain-English words.")

    if h1_count != 1:
        issues.append(f"Found {h1_count} H1 headings; exactly 1 is expected.")
    if h2_count < 3:
        issues.append(f"Only {h2_count} H2 sections found; aim for 3-5 for good structure.")
        suggestions.append("Break a long section into two clearly-titled H2s.")

    meta_title = _build_meta_title(title, keyword)
    meta_description = _build_meta_description(markdown, keyword)
    slug = slugify(title)[:75]

    score = _score(
        word_count_ok=settings.min_word_count <= word_count <= settings.max_word_count,
        density_ok=settings.target_keyword_density_min <= density <= settings.target_keyword_density_max,
        flesch_ok=flesch >= settings.min_flesch_reading_ease,
        structure_ok=(h1_count == 1 and h2_count >= 3),
        meta_ok=bool(meta_title and meta_description),
    )

    logger.info(f"SEO score: {score}/100" + (f" - {len(issues)} issue(s) found" if issues else " - all checks passed"))

    report: SEOReport = {
        "score": score,
        "word_count": word_count,
        "flesch_reading_ease": round(flesch, 1),
        "keyword_density_pct": round(density, 2),
        "has_meta_title": bool(meta_title),
        "has_meta_description": bool(meta_description),
        "meta_title": meta_title,
        "meta_description": meta_description,
        "slug": slug,
        "issues": issues,
        "suggestions": suggestions,
    }

    optimized_markdown = (
        f"<!--\n"
        f"meta_title: {meta_title}\n"
        f"meta_description: {meta_description}\n"
        f"slug: {slug}\n"
        f"-->\n\n{markdown.strip()}\n"
    )

    return {"seo_report": report, "optimized_markdown": optimized_markdown}


def _keyword_density(markdown: str, keyword: str) -> float:
    # Normalize hyphens to spaces in both the body and the keyword before
    # tokenizing, so a hyphenated keyword like "high-yield savings
    # accounts" tokenizes the same way the body text does (the \w+ regex
    # below does not treat "-" as part of a word, so without this
    # normalization a hyphenated keyword would never match and density
    # would silently come out as 0%).
    words = re.findall(r"\b\w+\b", markdown.lower().replace("-", " "))
    if not words:
        return 0.0
    kw_tokens = keyword.lower().replace("-", " ").split()
    kw_len = len(kw_tokens)
    count = 0
    for i in range(len(words) - kw_len + 1):
        if words[i:i + kw_len] == kw_tokens:
            count += 1
    return (count * kw_len / len(words)) * 100


def _build_meta_title(title: str, keyword: str) -> str:
    meta = title if keyword.lower() in title.lower() else f"{title} | {keyword.title()}"
    return meta[:60]


def _build_meta_description(markdown: str, keyword: str) -> str:
    body = re.sub(r"^#.*$", "", markdown, flags=re.MULTILINE)  # drop headings
    body = re.sub(r"\s+", " ", body).strip()
    snippet = body[:155].rsplit(" ", 1)[0]
    if keyword.lower() not in snippet.lower():
        snippet = f"{keyword.title()}: {snippet}"[:155]
    return snippet.rstrip(".,;:") + "."


def _score(*, word_count_ok, density_ok, flesch_ok, structure_ok, meta_ok) -> int:
    weights = {
        "word_count_ok": 20,
        "density_ok": 25,
        "flesch_ok": 20,
        "structure_ok": 20,
        "meta_ok": 15,
    }
    checks = {
        "word_count_ok": word_count_ok,
        "density_ok": density_ok,
        "flesch_ok": flesch_ok,
        "structure_ok": structure_ok,
        "meta_ok": meta_ok,
    }
    return sum(weights[k] for k, passed in checks.items() if passed)
