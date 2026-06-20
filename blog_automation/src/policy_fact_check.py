"""
Lightweight, explainable fact-check against the company-policy index
(Part 3, proposal 2 of the design document) -- a working but
deliberately simple stand-in for the production recommendation there
(Voyage AI embeddings + IBM Granite Guardian for groundedness). This
version demonstrates the real retrieval pattern end to end: extract a
candidate claim from the draft, retrieve the closest policy passage,
and flag the claim if nothing retrieved is actually close to it.

What this is NOT: a sentence-level entailment/groundedness model like
Granite Guardian, which can tell "supported" apart from "contradicted"
apart from "merely unrelated." This node only answers the cruder
question "is there anything in our policies that resembles this claim
at all" -- a real, useful first filter, but explicitly not a substitute
for the production proposal. See README.md for which is which.
"""

from __future__ import annotations

import re

from src.state import PipelineState
from src.vector_index import get_knowledge_base_index

# A draft sentence is treated as a "claim" worth checking if it contains
# a number-like token (rates, fees, amounts) or one of these terms --
# the kind of statement where being ungrounded is a real compliance risk,
# as opposed to ordinary advice prose with nothing specific to verify.
# A draft sentence is treated as a "claim" worth checking if it states a
# specific number (a rate, fee, or amount) or asserts one of these
# strong, absolute terms -- the kind of statement where being ungrounded
# is a real compliance risk. Deliberately narrow: generic mentions of
# "interest rates" or "fees" as a financial-literacy concept (not an
# assertion about this company's own terms) are not flagged, to avoid
# drowning real risks in false positives.
_CLAIM_TERMS = (
    "guarantee", "guaranteed", "risk-free", "zero risk", "fdic",
    "deposit insurance", "deposit protection",
)
_NUMBER_PATTERN = re.compile(r"\d+(\.\d+)?\s?%|\$\s?\d+|\u20ac\s?\d+|\d+(\.\d+)?\s?(eur|usd)", re.IGNORECASE)

MIN_GROUNDING_SCORE = 0.35

# Similarity alone cannot tell "this policy supports the claim" apart
# from "this policy explicitly prohibits the claim" -- a claim and the
# policy that bans it are often the most topically similar passage in
# the whole corpus, since they share the same vocabulary. This table
# catches the common, high-stakes version of that confusion explicitly:
# if the claim asserts one of these terms and the retrieved policy text
# itself contains a negation of it, that is a contradiction, not
# grounding. This is still a simple, rule-based check -- the kind of
# nuance Granite Guardian's groundedness model is the proposed
# production answer for (see README / design document, Part 3).
_CONTRADICTION_CUES: dict[str, tuple[str, ...]] = {
    "guarantee": ("not guaranteed", "never guarantee", "not be guaranteed", "does not guarantee"),
    "guaranteed": ("not guaranteed", "never guarantee", "not be guaranteed", "does not guarantee"),
    "risk-free": ("must not describe", "not be described as risk-free", "never risk-free"),
    "zero risk": ("must not describe", "not be described as risk-free"),
}


def run_policy_fact_check(state: PipelineState) -> dict:
    text = state["linked_markdown"]
    claims = _extract_claim_sentences(text)

    index = get_knowledge_base_index()
    reasons: list[str] = []
    for claim in claims:
        matches = index.query_policies(claim, top_k=3)
        if not matches:
            reasons.append(f"Claim not clearly grounded in company policy (no policy retrieved): \u201c{claim.strip()}\u201d")
            continue

        # A contradiction can show up in any of the top few retrieved
        # passages, not necessarily the single highest-scoring one --
        # raw similarity can rank a topically-close but irrelevant policy
        # above the one that actually prohibits this specific claim.
        contradicted_by = next((m for m in matches if _contradicts(claim, m.get("text", ""))), None)
        if contradicted_by:
            reasons.append(
                f"Claim appears to contradict company policy \u201c{contradicted_by.get('title')}\u201d: "
                f"\u201c{claim.strip()}\u201d"
            )
        elif matches[0]["score"] < MIN_GROUNDING_SCORE:
            reasons.append(
                f"Claim not clearly grounded in company policy (best match "
                f"score {matches[0]['score']:.2f}): \u201c{claim.strip()}\u201d"
            )

    return {"fact_check": {"passed": len(reasons) == 0, "reasons": reasons}}


def _contradicts(claim: str, policy_text: str) -> bool:
    claim_lower = claim.lower()
    policy_lower = policy_text.lower()
    for term, negation_cues in _CONTRADICTION_CUES.items():
        if re.search(rf"\b{re.escape(term)}\b", claim_lower) and any(cue in policy_lower for cue in negation_cues):
            return True
    return False


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
