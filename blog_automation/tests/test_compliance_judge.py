import json

from src.compliance_judge import _parse_judge_response
from src.llm_providers import MockProvider


def test_parse_judge_response_valid_json():
    raw = json.dumps({"passed": False, "reasons": ["pressuring tone"]})
    result = _parse_judge_response(raw)
    assert result == {"passed": False, "reasons": ["pressuring tone"]}


def test_parse_judge_response_fails_closed_on_garbage():
    result = _parse_judge_response("not json at all")
    assert result["passed"] is False
    assert result["reasons"]


def test_mock_provider_compliance_judge_passes_clean_draft():
    provider = MockProvider()
    prompt = "COMPLIANCE_REVIEW_TASK\n\nDRAFT_TO_REVIEW:\nThis is a perfectly ordinary, neutral paragraph about budgeting."
    raw = provider.generate("system", prompt)
    data = json.loads(raw)
    assert data["passed"] is True
    assert data["reasons"] == []


def test_mock_provider_compliance_judge_flags_pressuring_tone():
    provider = MockProvider()
    prompt = "COMPLIANCE_REVIEW_TASK\n\nDRAFT_TO_REVIEW:\nAct now, this limited time offer won't last!"
    raw = provider.generate("system", prompt)
    data = json.loads(raw)
    assert data["passed"] is False
    assert any("act now" in r.lower() for r in data["reasons"])
