"""
Topic-importance tagging.

This is independent of, and runs alongside, the quality checks in
quality_gate.py. A draft can pass every quality check perfectly and
still cover a topic where the cost of an undetected mistake is too
high to risk an unattended publish -- tax deadlines, specific rate or
fee claims, deposit protection, regulatory/legal subjects, direct
competitor comparisons, unannounced product news, sensitive or crisis
topics. Those always route to a human writer (see Part 3, proposal 4
of the design document), regardless of how confident the automated
checks are.

Two layers, intentionally cheap rather than a trained model:
  1. `tag_importance_from_keyword` -- the primary signal, applied once
     at keyword input. In a real deployment this would usually be a
     human-curated tag set when the content calendar is planned, since
     whoever schedules a "what happens if you miss your tax deadline"
     post already knows it is sensitive; this keyword list is the
     stand-in for that human judgment in the demo.
  2. `rescan_importance_in_text` -- a safety net applied to the
     generated draft itself, in case a sensitive subject appears inside
     the text without being obvious from the keyword alone.
"""

from __future__ import annotations

import re

HIGH_IMPORTANCE_TRIGGERS: tuple[str, ...] = (
    "tax deadline", "tax filing", "irs", "fdic", "deposit insurance",
    "deposit protection", "interest rate", "apr", "annual percentage rate",
    "overdraft fee", "late fee", "penalty", "lawsuit", "regulation",
    "regulatory", "compliance", "data breach", "security breach", "hacked",
    "fraud alert", "vs competitor", "compared to", "unannounced", "recall",
)


def tag_importance_from_keyword(keyword: str) -> str:
    lowered = keyword.lower()
    if any(trigger in lowered for trigger in HIGH_IMPORTANCE_TRIGGERS):
        return "high"
    return "standard"


def rescan_importance_in_text(text: str, current_tier: str) -> str:
    """Safety-net re-check on the generated draft; never downgrades a tier."""
    if current_tier == "high":
        return "high"
    lowered = text.lower()
    if any(re.search(rf"\b{re.escape(trigger)}\b", lowered) for trigger in HIGH_IMPORTANCE_TRIGGERS):
        return "high"
    return current_tier
