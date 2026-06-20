from src.policy_fact_check import run_policy_fact_check
from src.semantic_duplicate_check import run_semantic_duplicate_check, index_published_post
from src.vector_index import get_knowledge_base_index


def test_fact_check_passes_a_claim_supported_by_policy():
    state = {"linked_markdown": "Instant transfers to an external bank are charged a flat fee of 1.50 EUR per transfer."}
    result = run_policy_fact_check(state)
    assert result["fact_check"]["passed"] is True


def test_fact_check_flags_a_claim_contradicting_policy():
    state = {"linked_markdown": "We guarantee a 20% annual return with zero risk on this account."}
    result = run_policy_fact_check(state)
    assert result["fact_check"]["passed"] is False
    assert "contradict" in result["fact_check"]["reasons"][0].lower()


def test_fact_check_ignores_prose_with_no_specific_claim():
    state = {"linked_markdown": "Building good habits takes time, and everyone's situation is a little different."}
    result = run_policy_fact_check(state)
    assert result["fact_check"]["passed"] is True


def test_duplicate_check_flags_near_identical_published_post():
    # The existing-content catalog is seeded into the index at build
    # time; querying with one of its own summaries verbatim should come
    # back as a near-perfect match against itself.
    state = {
        "linked_markdown": (
            "A step-by-step guide to setting savings targets, choosing the "
            "right account type, and automating monthly transfers to build "
            "a 3-6 month emergency fund."
        )
    }
    result = run_semantic_duplicate_check(state)
    assert result["duplicate_check"]["passed"] is False
    assert result["duplicate_check"]["matches"][0]["score"] > 0.9


def test_duplicate_check_passes_clearly_different_text():
    state = {"linked_markdown": "A completely unrelated sentence about choosing a new pair of running shoes."}
    result = run_semantic_duplicate_check(state)
    assert result["duplicate_check"]["passed"] is True


def test_index_published_post_makes_future_queries_find_it():
    index = get_knowledge_base_index()
    # Finance-flavored but distinct from every existing post, so the
    # embedding has enough genuine vocabulary overlap with the fitted
    # corpus to be reliable -- a fully off-topic example (unrelated to
    # personal finance at all) would correctly be treated as degenerate
    # by the guard tested above, which is not what this test is for.
    text = "A guide to choosing between a fixed-rate and a variable-rate mortgage when refinancing your home loan."
    index_published_post({
        "title": "Fixed vs Variable Mortgage Rates When Refinancing",
        "linked_markdown": text,
        "canonical_url": "https://example.test/blog/fixed-vs-variable-mortgage/",
    })
    matches = index.query_similar_posts(text, top_k=1)
    assert matches[0]["title"] == "Fixed vs Variable Mortgage Rates When Refinancing"
    assert matches[0]["score"] > 0.9
