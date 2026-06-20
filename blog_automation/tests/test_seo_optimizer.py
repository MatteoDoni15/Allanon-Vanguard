"""
Unit tests for the SEO optimizer.

Run with:  pytest tests/ -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.seo_optimizer import analyze_and_optimize, _keyword_density, _build_meta_title


def test_keyword_density_basic():
    text = "investing is great. I love investing. Investing changes lives."
    density = _keyword_density(text, "investing")
    # 3 occurrences of a 1-word keyword out of 9 total words -> ~33%
    assert round(density, 1) == 33.3


def test_keyword_density_multi_word_keyword():
    text = "emergency fund tips are useful. Build your emergency fund tips today."
    density = _keyword_density(text, "emergency fund tips")
    # keyword occurs twice, 3 tokens each, out of 11 total words
    assert round(density, 1) == round((2 * 3 / 11) * 100, 1)


def test_meta_title_includes_keyword_when_missing():
    title = "A Practical Guide"
    meta = _build_meta_title(title, "budgeting apps")
    assert "budgeting apps" in meta.lower()
    assert len(meta) <= 60


def test_analyze_and_optimize_flags_short_content():
    state = {
        "raw_markdown": "# Short Post\n\nThis is way too short to be a real article.",
        "keyword": "short post",
        "title": "Short Post",
    }
    result = analyze_and_optimize(state)
    report = result["seo_report"]
    assert report["word_count"] < 900
    assert any("below" in issue.lower() for issue in report["issues"])
    assert report["score"] < 75  # should not be publish-ready


def test_analyze_and_optimize_produces_front_matter():
    state = {
        "raw_markdown": "# My Title\n\n" + ("This is filler content. " * 50),
        "keyword": "my title",
        "title": "My Title",
    }
    result = analyze_and_optimize(state)
    assert result["optimized_markdown"].startswith("<!--")
    assert "meta_title:" in result["optimized_markdown"]
    assert "slug:" in result["optimized_markdown"]
