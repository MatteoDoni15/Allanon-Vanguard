"""
Quality gate / risk-tiered publishing decision.

This node now combines two independent axes, matching Part 3 (proposal
4) of the design document:

  1. Quality axis -- are the automated checks all satisfied: banned
     phrases, SEO score, minimum length, the compliance_judge node's
     verdict, the lightweight policy fact-check, and the semantic
     duplicate check? If not, and retries remain, the graph loops back
     to content_generation with the specific reasons attached. After
     `max_generation_retries` failed attempts, it routes to
     needs_review instead of looping forever.
  2. Importance axis -- regardless of how well a draft scores, a topic
     tagged "high" importance at keyword input (see
     importance_tagger.py) always routes to needs_review. This is not
     a quality failure and never triggers a retry: the draft can be
     perfectly good and still need a human sign-off because of what
     the topic is, not how it was written.

Both checks must pass for a post to qualify for auto-publish.
"""

from __future__ import annotations

from config import settings
from src.state import PipelineState
from src.importance_tagger import rescan_importance_in_text


def run_quality_gate(state: PipelineState) -> dict:
    text = state["linked_markdown"].lower()
    reasons: list[str] = []

    # 1. Compliance: banned/risky financial-promotion language.
    found_banned = [p for p in settings.banned_phrases if p in text]
    if found_banned:
        reasons.append(
            "Contains non-compliant financial language: " + ", ".join(found_banned)
        )

    # 2. SEO score threshold (reuses the seo_optimizer's score).
    seo_score = state["seo_report"]["score"]
    if seo_score < settings.min_seo_score_to_publish:
        reasons.append(
            f"SEO score {seo_score} is below the publish threshold "
            f"({settings.min_seo_score_to_publish}). "
            + " ".join(state["seo_report"].get("suggestions", []))
        )

    # 3. Minimum structural sanity (defends against an empty/degenerate draft).
    if state["seo_report"]["word_count"] < 200:
        reasons.append("Draft is too short to be a real article (possible generation failure).")

    # 4. Compliance judge verdict (Part 3, proposal 1 -- run_compliance_judge,
    #    a separate LangGraph node feeding into the same `compliance` field).
    compliance = state.get("compliance", {"passed": True, "reasons": []})
    if not compliance.get("passed", True):
        reasons.extend(compliance.get("reasons", []))

    # 5. Lightweight policy fact-check (Part 3, proposal 2 -- run_policy_fact_check).
    fact_check = state.get("fact_check", {"passed": True, "reasons": []})
    if not fact_check.get("passed", True):
        reasons.extend(fact_check.get("reasons", []))

    # 5b. External web fact-check via DuckDuckGo (run_web_fact_check).
    web_fact_check = state.get("web_fact_check", {"passed": True, "reasons": []})
    if not web_fact_check.get("passed", True):
        reasons.extend(web_fact_check.get("reasons", []))

    # 6. Semantic duplicate check against published posts (Part 3, proposal 5).
    duplicate_check = state.get("duplicate_check", {"passed": True, "reasons": []})
    if not duplicate_check.get("passed", True):
        reasons.extend(duplicate_check.get("reasons", []))

    quality_passed = len(reasons) == 0

    # Safety-net re-check: a sensitive subject can show up inside the
    # generated text even when the keyword itself looked routine.
    importance_tier = rescan_importance_in_text(text, state.get("importance_tier", "standard"))

    return {
        "quality": {"passed": quality_passed, "reasons": reasons},
        "importance_tier": importance_tier,
    }


def route_after_quality_gate(state: PipelineState) -> str:
    """LangGraph conditional-edge function. Returns the name of the next node."""
    quality_passed = state["quality"]["passed"]

    if not quality_passed:
        if state.get("retries", 0) < settings.max_generation_retries:
            return "retry"
        return "needs_review"

    # Quality is fine on its own merits; the importance axis can still
    # require a human, independently of draft quality.
    if state.get("importance_tier", "standard") == "high":
        return "needs_review"

    return "publish"
