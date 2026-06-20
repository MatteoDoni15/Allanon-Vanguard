"""
Semantic duplicate detection (Part 3, proposal 5): the scaling
evolution of internal_linking.py's TF-IDF approach, using the same
published_posts collection in the vector index. Reuses the *same*
similarity score for two different decisions at two different
thresholds, exactly as described in the design document:

  - moderate similarity -> already handled by internal_linking.py's
    TF-IDF suggestions (left as-is; this module does not duplicate it).
  - very high similarity -> flagged here as a likely near-duplicate,
    which TF-IDF's word-overlap approach is structurally weaker at
    catching than an embedding-based comparison.
"""

from __future__ import annotations

from src.state import PipelineState
from src.vector_index import get_knowledge_base_index

DUPLICATE_SIMILARITY_THRESHOLD = 0.90


def run_semantic_duplicate_check(state: PipelineState) -> dict:
    index = get_knowledge_base_index()
    matches = index.query_similar_posts(state["linked_markdown"], top_k=3)

    near_duplicates = [m for m in matches if m["score"] >= DUPLICATE_SIMILARITY_THRESHOLD]
    reasons = [
        f"Near-duplicate of an existing post (similarity {m['score']:.2f}): "
        f"\u201c{m['title']}\u201d ({m['url']})"
        for m in near_duplicates
    ]
    return {"duplicate_check": {"passed": len(reasons) == 0, "reasons": reasons, "matches": matches}}


def index_published_post(state: PipelineState) -> None:
    """Called once a post actually publishes, so later drafts are
    checked against it too -- incremental, not a full recompute."""
    index = get_knowledge_base_index()
    url = state.get("canonical_url") or f"/blog/{state.get('seo_report', {}).get('slug', 'untitled')}/"
    index.add_new_post(
        title=state["title"],
        text=state["linked_markdown"],
        url=url,
    )
