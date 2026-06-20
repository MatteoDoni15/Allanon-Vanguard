"""
Step: Content Validation & Compliance (Part 3, proposal 1 of the design
document), implemented as a LangGraph node.

Deliberately an LLM-as-judge through the existing, already-pluggable
LLMProvider interface (Claude/OpenAI/Mock) rather than a trained
classifier: there is no labeled dataset of "compliant" vs "flagged"
historical posts to train on yet, while a judge works immediately from
written guidelines and returns reasons that plug straight into the same
retry-with-feedback mechanism quality_gate.py already implements.

The judge is asked to return strict JSON. If the response cannot be
parsed as the expected shape, this fails closed (treated as "needs
review") rather than silently passing a draft -- in a regulated
industry, an unparseable judge response should never be read as "ok".
"""

from __future__ import annotations

import json

from config import settings
from src.state import PipelineState
from src.llm_providers import get_llm_provider

COMPLIANCE_SYSTEM_PROMPT = """\
You are a compliance reviewer for a FinTech company's marketing blog. \
Evaluate the draft below ONLY against the guidelines provided. Respond \
with strict JSON and nothing else, in this exact shape:
{"passed": true or false, "reasons": ["short reason", ...]}
If there is nothing to flag, return {"passed": true, "reasons": []}.
"""

COMPLIANCE_USER_TEMPLATE = """\
COMPLIANCE_REVIEW_TASK

COMPANY_GUIDELINES:
{guidelines}

DRAFT_TO_REVIEW:
{draft}
"""


def run_compliance_judge(state: PipelineState) -> dict:
    """LangGraph node: reads `linked_markdown`, returns `compliance`."""
    provider = get_llm_provider()
    user_prompt = COMPLIANCE_USER_TEMPLATE.format(
        guidelines=settings.compliance_guidelines,
        draft=state["linked_markdown"],
    )
    raw = provider.generate(COMPLIANCE_SYSTEM_PROMPT, user_prompt)
    return {"compliance": _parse_judge_response(raw)}


def _parse_judge_response(raw: str) -> dict:
    try:
        data = json.loads(raw.strip())
        passed = bool(data["passed"])
        reasons = [str(r) for r in data.get("reasons", [])]
        return {"passed": passed, "reasons": reasons}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        # Fail closed: an unparseable judge response is never read as "ok".
        return {"passed": False, "reasons": ["Compliance judge response could not be parsed; routing to human review."]}
