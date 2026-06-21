"""
Feedback loop (Part 3, proposal 3): turn the engagement of *past* posts into a
priority ranking for *future* keywords.

The idea, kept deliberately simple and explainable:

  1. Each past post has an engagement score derived from its metrics
     (click-through rate, dwell time, conversions).
  2. Those scores are **centered on the mean**, so above-average posts get a
     positive weight and below-average posts a negative one.
  3. A candidate keyword's priority is the similarity-weighted sum of those
     weights: it rises toward topics like the ones that performed well and falls
     away from topics like the ones that performed badly.

Similarity reuses the same TF-IDF + cosine machinery the rest of the project
already uses (internal_linking), so no extra model or dependency is introduced.

This is the lowest-risk lever of the feedback loop: it tunes *what to write
next*, never compliance thresholds (those stay human-owned -- see
DESIGN_DOCUMENT, proposal 3). It is honest about its limits: with no real
traffic it is tested on fake metrics, which proves the mechanism, not that it
improves real engagement.
"""

from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.logging_config import get_logger

logger = get_logger("keyword_priority")

# Reference dwell time (seconds) at which the dwell component saturates to 1.0.
_DWELL_REFERENCE_SEC = 120.0


def engagement_score(
    impressions: int,
    clicks: int,
    avg_time_sec: float,
    conversions: int = 0,
) -> float:
    """Blend raw metrics into a single engagement value in roughly [0, 1].

    CTR dominates (it is the clearest "did this topic land" signal), with dwell
    time and conversion-among-clicks as secondary signals.
    """
    impressions = max(int(impressions or 0), 0)
    clicks = max(int(clicks or 0), 0)
    ctr = clicks / impressions if impressions > 0 else 0.0
    dwell = min(max(float(avg_time_sec or 0.0), 0.0) / _DWELL_REFERENCE_SEC, 1.0)
    conv_rate = (int(conversions or 0) / clicks) if clicks > 0 else 0.0
    return 0.6 * ctr + 0.3 * dwell + 0.1 * conv_rate


def _history_text(item: dict) -> str:
    """Topical signal for a past post: its keyword plus its title."""
    return f"{item.get('keyword', '')} {item.get('title', '')}".strip()


def compute_keyword_priorities(candidates: list[str], history: list[dict]) -> list[dict]:
    """Rank ``candidates`` (future keywords) by learned priority.

    ``history`` is a list of ``{keyword, title, metrics}`` where ``metrics`` is
    ``{impressions, clicks, avg_time_sec, conversions}`` or ``None`` (no feedback
    yet -- ignored in scoring). Returns a list of
    ``{keyword, priority, raw_score, basis_posts, rationale}`` sorted by
    descending priority. ``priority`` is min-max normalised to 0..100 for display.
    """
    cands = [c.strip() for c in candidates if c and c.strip()]
    if not cands:
        return []

    scored = [h for h in history if h.get("metrics")]
    if not scored:
        logger.info("Keyword priority: no engagement data yet -- returning neutral priorities")
        return [
            {
                "keyword": c,
                "priority": 50.0,
                "raw_score": 0.0,
                "basis_posts": 0,
                "rationale": "Nessun dato di engagement ancora: priorità neutra.",
            }
            for c in cands
        ]

    engagements = np.array(
        [engagement_score(**h["metrics"]) for h in scored], dtype=float
    )
    weights = engagements - engagements.mean()  # center: good > 0, bad < 0
    hist_texts = [_history_text(h) for h in scored]

    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform(cands + hist_texts)
    cand_vecs = matrix[: len(cands)]
    hist_vecs = matrix[len(cands):]
    sims = cosine_similarity(cand_vecs, hist_vecs)  # (n_candidates, n_history)

    contributions = sims * weights  # element-wise, per (candidate, past-post)
    raw = contributions.sum(axis=1)

    if float(raw.max()) == float(raw.min()):
        norm = np.full_like(raw, 50.0)
    else:
        norm = (raw - raw.min()) / (raw.max() - raw.min()) * 100.0

    logger.info(
        f"Keyword priority: ranked {len(cands)} candidate(s) against "
        f"{len(scored)} post(s) with engagement data"
    )

    results: list[dict] = []
    for i, kw in enumerate(cands):
        j = int(np.argmax(np.abs(contributions[i]))) if sims.shape[1] else -1
        if j >= 0 and abs(contributions[i, j]) > 1e-9:
            driver = scored[j]
            direction = "spinge in alto" if contributions[i, j] > 0 else "spinge in basso"
            rationale = (
                f"{direction}: simile a «{driver.get('keyword') or driver.get('title')}» "
                f"(engagement {'sopra' if weights[j] >= 0 else 'sotto'} la media)."
            )
        else:
            rationale = "Nessuna somiglianza rilevante con i post storici."
        results.append({
            "keyword": kw,
            "priority": round(float(norm[i]), 1),
            "raw_score": round(float(raw[i]), 4),
            "basis_posts": len(scored),
            "rationale": rationale,
        })

    results.sort(key=lambda r: r["priority"], reverse=True)
    return results
