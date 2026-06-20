"""
Vector index over two collections, both living in the same Qdrant
*local-mode* instance (an in-process client, no server to run --
suitable up to roughly 20,000 vectors, which is far more than either
collection here realistically needs):

  - "company_policies": Part 3 proposal 2 (fact-checking via RAG).
  - "published_posts":  Part 3 proposal 5 (semantic duplicate detection
    at scale / the scaling evolution of internal_linking.py).

Local mode is a deliberate choice, not a placeholder: the same
QdrantClient API works identically against a managed or self-hosted
instance, so moving from this to production is a one-line change
(QdrantClient(":memory:") -> QdrantClient(url=...)), not a rewrite. See
the design document, Appendix A, for the full reasoning.
"""

from __future__ import annotations

import json
import os

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from config import settings
from src.embeddings import EmbeddingProvider, get_embedding_provider

POLICIES_COLLECTION = "company_policies"
POSTS_COLLECTION = "published_posts"


def _is_degenerate(vector: np.ndarray, eps: float = 1e-8) -> bool:
    """
    True when a query shares no vocabulary at all with the corpus the
    embedder was fit on, so TF-IDF (and therefore the LSA projection) is
    the zero vector. Cosine similarity is mathematically undefined for a
    zero vector, and in practice Qdrant returns numerically unstable,
    effectively arbitrary scores for one (one query in testing returned
    a spurious 0.99 "match" against an unrelated post). Filtering this
    out before querying is safer than trusting whatever score comes
    back, and it is also the semantically correct answer: a draft with
    zero shared vocabulary with the entire corpus has nothing to be
    grounded in or duplicate of.
    """
    return float(np.linalg.norm(vector)) < eps


class KnowledgeBaseIndex:
    def __init__(self, embedding_provider: EmbeddingProvider | None = None):
        self._client = QdrantClient(":memory:")
        self._embedder = embedding_provider or get_embedding_provider("lsa")
        self._policies: list[dict] = []
        self._posts: list[dict] = []
        self._next_post_id = 1000
        self._fitted = False

    # -- setup ------------------------------------------------------------

    def load_policies_from_file(self, path: str | None = None) -> None:
        path = path or settings.company_policies_path
        with open(path, encoding="utf-8") as f:
            self._policies = json.load(f)

    def _load_existing_posts_from_file(self, path: str) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            catalog = json.load(f)
        return [{"title": p["title"], "url": p["url"], "text": p["summary"]} for p in catalog]

    def build(self, existing_posts_path: str | None = None) -> None:
        """
        Fits the embedder once, on the union of both corpora (so policy
        text and post text share one comparable vector space), then
        populates both Qdrant collections. published_posts is seeded
        with the same existing-content catalog internal_linking.py uses
        (so duplicate-checking has something realistic to compare
        against from the start) and grows further via
        upsert_published_post() as new posts go live.
        """
        existing_posts = self._load_existing_posts_from_file(
            existing_posts_path or settings.existing_content_path
        )
        corpus = [p["text"] for p in self._policies] + [p["text"] for p in existing_posts]
        corpus = corpus or ["placeholder"]
        self._embedder.fit(corpus)
        self._fitted = True

        dim = self._embedder.embed(corpus[:1]).shape[1]
        for name in (POLICIES_COLLECTION, POSTS_COLLECTION):
            if self._client.collection_exists(name):
                self._client.delete_collection(name)
            self._client.create_collection(
                collection_name=name,
                vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
            )

        if self._policies:
            vectors = self._embedder.embed([p["text"] for p in self._policies])
            self._client.upsert(
                collection_name=POLICIES_COLLECTION,
                points=[
                    qmodels.PointStruct(id=i, vector=vectors[i].tolist(), payload=self._policies[i])
                    for i in range(len(self._policies))
                ],
            )

        for post in existing_posts:
            self.upsert_published_post(self._next_post_id, post["title"], post["text"], post["url"])
            self._next_post_id += 1

    # -- company_policies: fact-checking (Part 3 proposal 2) --------------

    def query_policies(self, text: str, top_k: int = 3) -> list[dict]:
        self._ensure_fitted()
        vector = self._embedder.embed([text])[0]
        if _is_degenerate(vector):
            return []  # no shared vocabulary with the fitted corpus at all
        result = self._client.query_points(collection_name=POLICIES_COLLECTION, query=vector.tolist(), limit=top_k)
        return [{"score": h.score, **h.payload} for h in result.points]

    # -- published_posts: duplicate detection (Part 3 proposal 5) ---------

    def upsert_published_post(self, post_id: int, title: str, text: str, url: str) -> None:
        self._ensure_fitted()
        vector = self._embedder.embed([text])[0].tolist()
        payload = {"title": title, "url": url}
        self._client.upsert(
            collection_name=POSTS_COLLECTION,
            points=[qmodels.PointStruct(id=post_id, vector=vector, payload=payload)],
        )
        self._posts.append({"id": post_id, **payload})

    def add_new_post(self, title: str, text: str, url: str) -> int:
        """Used when a newly generated post actually publishes: assigns
        the next id itself so callers (e.g. the pipeline) never need to
        track Qdrant point ids."""
        post_id = self._next_post_id
        self._next_post_id += 1
        self.upsert_published_post(post_id, title, text, url)
        return post_id

    def query_similar_posts(self, text: str, top_k: int = 5) -> list[dict]:
        self._ensure_fitted()
        if not self._posts:
            return []
        vector = self._embedder.embed([text])[0]
        if _is_degenerate(vector):
            return []  # no shared vocabulary with the fitted corpus at all
        result = self._client.query_points(collection_name=POSTS_COLLECTION, query=vector.tolist(), limit=top_k)
        return [{"score": h.score, **h.payload} for h in result.points]

    def _ensure_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError("KnowledgeBaseIndex.build() must be called before querying.")


_INDEX: KnowledgeBaseIndex | None = None


def get_knowledge_base_index() -> KnowledgeBaseIndex:
    """
    Process-wide singleton: the embedder is fit once per process rather
    than once per keyword, since fitting is the relatively expensive
    step and the policy corpus does not change between pipeline runs in
    a single batch.
    """
    global _INDEX
    if _INDEX is None:
        _INDEX = KnowledgeBaseIndex()
        _INDEX.load_policies_from_file()
        _INDEX.build()
    return _INDEX


def reset_knowledge_base_index() -> None:
    """Drop the cached index so the next get_knowledge_base_index() rebuilds it.

    Called after the policy set changes (see policy_store): the LSA embedder is
    fit once per build, so a newly added policy only becomes retrievable -- and
    its vocabulary only enters the vector space -- after a fresh rebuild. The
    rebuild happens lazily on the next pipeline run, which (in the server) holds
    the generation lock, so it never races a run already in flight.
    """
    global _INDEX
    _INDEX = None
