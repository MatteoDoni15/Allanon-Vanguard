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
from src.logging_config import get_logger
from src.state import PipelineState
from src.llm_providers import get_llm_provider
from src.token_budget import estimate_tokens, chunk_by_tokens

logger = get_logger("compliance_judge")

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
    logger.info("Running compliance judge")
    provider = get_llm_provider(task="compliance")
    draft = state["linked_markdown"]

    if estimate_tokens(draft) <= settings.max_compliance_draft_tokens:
        parts = [draft]
        logger.info(f"Draft fits in token budget - judging as single part")
    else:
        parts = chunk_by_tokens(draft, settings.max_compliance_draft_tokens)
        logger.info(f"Draft exceeds token budget - chunking into {len(parts)} parts for compliance review")

    results = []
    for i, part in enumerate(parts, 1):
        logger.info(f"Judging compliance chunk {i}/{len(parts)}")
        user_prompt = COMPLIANCE_USER_TEMPLATE.format(
            guidelines=settings.compliance_guidelines,
            draft=part,
        )
        raw = provider.generate(COMPLIANCE_SYSTEM_PROMPT, user_prompt)
        result = _parse_judge_response(raw)
        results.append(result)

    merged = _merge_judgments(results)
    if merged["passed"]:
        logger.info("Compliance judge: PASSED")
    else:
        logger.warning(f"Compliance judge: FAILED - {merged['reasons']}")

    return {"compliance": merged}


def _merge_judgments(results: list[dict]) -> dict:
    """Combine per-chunk verdicts: passes only if every chunk passed; reasons
    are the de-duplicated union across chunks."""
    if len(results) == 1:
        return results[0]
    passed = all(r.get("passed", False) for r in results)
    reasons: list[str] = []
    for r in results:
        for reason in r.get("reasons", []):
            if reason not in reasons:
                reasons.append(reason)
    return {"passed": passed, "reasons": reasons}


def _parse_judge_response(raw: str) -> dict:
    try:
        data = json.loads(raw.strip())
        passed = bool(data["passed"])
        reasons = [str(r) for r in data.get("reasons", [])]
        return {"passed": passed, "reasons": reasons}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"Failed to parse compliance judge response: {str(e)}")
        return {"passed": False, "reasons": ["Compliance judge response could not be parsed; routing to human review."]}
