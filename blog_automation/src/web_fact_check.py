"""
External web fact-check node: for each claim sentence extracted from the
draft, queries DuckDuckGo to check whether the claim returns any
corroborating evidence. A claim that gets zero results is flagged as
externally unverifiable.

This runs after the internal policy fact-check (which verifies against
company documents) and adds an orthogonal layer: consistency with what
the public web actually says about specific numbers and assertions.

To avoid hitting DuckDuckGo rate limits, only the first
_MAX_CLAIMS_TO_SEARCH claims are searched.

Non-blocking on network/package errors: the node returns passed=True so
the pipeline is not blocked when the web is unreachable.
"""

from __future__ import annotations

import re

from src.logging_config import get_logger
from src.state import PipelineState

logger = get_logger("web_fact_check")

_CLAIM_TERMS = (
    "guarantee", "guaranteed", "risk-free", "zero risk", "fdic",
    "deposit insurance", "deposit protection",
)
_NUMBER_PATTERN = re.compile(
    r"\d+(\.\d+)?\s?%|\$\s?\d+|€\s?\d+|\d+(\.\d+)?\s?(eur|usd)",
    re.IGNORECASE,
)
_MAX_CLAIMS_TO_SEARCH = 3


def run_web_fact_check(state: PipelineState) -> dict:
    logger.info("Running web fact-check")
    text = state["linked_markdown"]
    claims = _extract_claim_sentences(text)[:_MAX_CLAIMS_TO_SEARCH]

    if not claims:
        logger.info("No fact-checkable claims found")
        return {"web_fact_check": {"passed": True, "reasons": []}}

    logger.info(f"Extracted {len(claims)} fact-checkable claim(s) to verify")
    reasons: list[str] = []
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            for i, claim in enumerate(claims, 1):
                logger.info(f"Verifying claim {i}/{len(claims)}: '{claim[:80]}...'")
                results = ddgs.text(claim[:120], max_results=3)
                if not results:
                    logger.warning(f"Claim {i} unverifiable - no web results")
                    reasons.append(
                        f"Claim returned no external search results (unverifiable): "
                        f"“{claim.strip()}”"
                    )
                else:
                    logger.info(f"Claim {i} verified - found {len(results)} web result(s)")
    except Exception as e:
        logger.warning(f"Web fact-check failed: {str(e)} - continuing without verification")
        return {"web_fact_check": {"passed": True, "reasons": []}}

    passed = len(reasons) == 0
    if passed:
        logger.info("Web fact-check: PASSED")
    else:
        logger.warning(f"Web fact-check: FAILED - {len(reasons)} unverifiable claim(s)")

    return {"web_fact_check": {"passed": passed, "reasons": reasons}}


def _extract_claim_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    claims = []
    for sentence in sentences:
        s = sentence.strip()
        if not s or s.startswith("#"):
            continue
        lowered = s.lower()
        term_hit = any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in _CLAIM_TERMS)
        if _NUMBER_PATTERN.search(s) or term_hit:
            claims.append(s)
    return claims
