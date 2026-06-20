"""
Persistence for the company-policy documents that the policy_fact_check
node grounds drafts against.

Policies live in the same ``data/company_policies.json`` file the vector
index already reads (see vector_index.load_policies_from_file), so adding
or removing one here is immediately picked up the next time the index is
(re)built. This module is the single write path for that file -- the
backend API and any tooling go through it rather than editing the JSON by
hand, which keeps doc_ids unique and the shape consistent.

Note: after any mutation the caller must reset the cached vector index
(vector_index.reset_knowledge_base_index) so the embedder is refit on the
new policy set and the change becomes retrievable -- the LSA embedder is
fit once per index build, so a new policy's vocabulary only enters the
vector space on a rebuild.
"""

from __future__ import annotations

import json
import os
import re

from config import settings
from src.logging_config import get_logger

logger = get_logger("policy_store")


def _path() -> str:
    return settings.company_policies_path


def _read() -> list[dict]:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write(policies: list[dict]) -> None:
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(policies, f, ensure_ascii=False, indent=2)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60]


def list_policies() -> list[dict]:
    """All stored policy documents, in file order."""
    return _read()


def add_policy(title: str, text: str, doc_id: str | None = None) -> dict:
    """Append a new policy and persist it. Returns the stored document."""
    policies = _read()
    base = (doc_id or _slugify(title) or "policy").strip()
    existing = {p.get("doc_id") for p in policies}
    unique = base
    n = 2
    while unique in existing:
        unique = f"{base}-{n}"
        n += 1
    doc = {"doc_id": unique, "title": title.strip(), "text": text.strip()}
    policies.append(doc)
    _write(policies)
    logger.info(f"Added policy '{doc['title']}' (doc_id={doc['doc_id']}) -- now {len(policies)} policies")
    return doc


def delete_policy(doc_id: str) -> bool:
    """Remove a policy by doc_id. Returns False if nothing matched."""
    policies = _read()
    remaining = [p for p in policies if p.get("doc_id") != doc_id]
    if len(remaining) == len(policies):
        logger.warning(f"Delete policy: doc_id '{doc_id}' not found")
        return False
    _write(remaining)
    logger.info(f"Deleted policy doc_id={doc_id} -- now {len(remaining)} policies")
    return True
