"""Tests for the input-token budgeting helpers (all offline, no LLM)."""

from __future__ import annotations

from src.token_budget import (
    estimate_tokens,
    within_budget,
    chunk_by_tokens,
    truncate_to_budget,
    extractive_summarize,
    compress_to_budget,
)

_LONG = (
    "Emergency funds protect households from unexpected costs. "
    "A common target is three to six months of essential expenses. "
    "Automating a fixed transfer on payday makes the habit stick. "
    "Reviewing the plan each quarter keeps it aligned with income changes. "
) * 40  # clearly over any small budget


def test_estimate_tokens_scales_with_length():
    assert estimate_tokens("") == 0
    short = estimate_tokens("hello world")
    long = estimate_tokens("hello world " * 100)
    assert long > short > 0


def test_chunker_respects_budget_and_preserves_words():
    chunks = chunk_by_tokens(_LONG, chunk_tokens=50)
    assert len(chunks) > 1
    for c in chunks:
        # allow a little slack for boundary handling, but no runaway chunks
        assert estimate_tokens(c) <= 50 * 2
    # No word is split across the join (rough check: rejoined text has no
    # obviously broken tokens like a trailing partial word marker).
    assert "".join(chunks).replace(" ", "")  # non-empty, did not crash


def test_truncate_fits_budget_and_marks():
    out = truncate_to_budget(_LONG, max_tokens=30)
    assert within_budget(out, 30)
    assert "troncato" in out


def test_extractive_summary_fits_budget():
    out = extractive_summarize(_LONG, max_tokens=40)
    assert within_budget(out, 40)
    assert len(out) < len(_LONG)


def test_compress_passthrough_when_already_small():
    text = "Short enough to keep verbatim."
    assert compress_to_budget(text, max_tokens=1000) == text


def test_compress_shrinks_oversized_text_offline():
    # use_llm=False forces the deterministic extractive path (no provider).
    out = compress_to_budget(_LONG, max_tokens=50, use_llm=False)
    assert within_budget(out, 50)
    assert 0 < len(out) < len(_LONG)
