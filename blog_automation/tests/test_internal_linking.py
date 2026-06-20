"""
Unit tests for the internal linking module.

Run with:  pytest tests/ -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.internal_linking import suggest_internal_links, _try_insert_link


def test_try_insert_link_wraps_first_matching_tag():
    markdown = "Building good habits around debt repayment takes time."
    anchor, new_markdown = _try_insert_link(
        markdown, tags=["debt"], url="/blog/debt-snowball-vs-avalanche", title="Debt Guide"
    )
    assert anchor == "debt"
    assert "[debt](/blog/debt-snowball-vs-avalanche)" in new_markdown


def test_try_insert_link_skips_headings():
    markdown = "## Debt Repayment Strategies\n\nThis section has no other mention."
    anchor, new_markdown = _try_insert_link(
        markdown, tags=["debt"], url="/blog/debt-snowball-vs-avalanche", title="Debt Guide"
    )
    # The only occurrence of "debt" is inside a heading, so no link should be inserted.
    assert anchor is None
    assert new_markdown == markdown


def test_suggest_internal_links_returns_ranked_suggestions(tmp_path, monkeypatch):
    import json
    from config import settings

    fake_catalog = [
        {
            "id": "p1", "title": "Credit Score Basics", "url": "/blog/credit-score-basics",
            "summary": "A guide to credit scores and credit utilization.",
            "tags": ["credit score", "credit"],
        }
    ]
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(fake_catalog))
    monkeypatch.setattr(settings, "existing_content_path", str(catalog_path))

    state = {
        "title": "How to Improve Your Credit Score",
        "optimized_markdown": "Improving your credit score takes consistent, on-time payments.",
    }
    result = suggest_internal_links(state)
    assert isinstance(result["internal_links"], list)
    assert len(result["internal_links"]) >= 1
    assert result["internal_links"][0]["target_url"] == "/blog/credit-score-basics"
