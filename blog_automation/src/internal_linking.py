"""
Step 4 of the pipeline (the "plus" task): Internal Linking Management.

Uses TF-IDF + cosine similarity (scikit-learn) to compare the new post
against a catalog of existing site content, then automatically inserts
contextual hyperlinks where the matched article's topic words actually
appear in the new post's text.

In production, `existing_site_content.json` would instead be a nightly
export (or live query) from the CMS/database -- title, URL, and a short
summary or tag list per published post are all this module needs.
"""

from __future__ import annotations

import json
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import settings
from src.state import PipelineState, LinkSuggestion


def _load_existing_content() -> list[dict]:
    with open(settings.existing_content_path, "r", encoding="utf-8") as f:
        return json.load(f)


def suggest_internal_links(state: PipelineState) -> dict:
    """LangGraph node: reads `optimized_markdown`, returns ranked link suggestions
    and a copy of the markdown with the top matches linked inline."""
    markdown = state["optimized_markdown"]
    existing_posts = _load_existing_content()

    corpus_summaries = [f"{p['title']} {p['summary']} {' '.join(p['tags'])}" for p in existing_posts]
    new_post_text = f"{state['title']} {markdown}"

    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(corpus_summaries + [new_post_text])
    new_post_vector = tfidf_matrix[-1]
    existing_vectors = tfidf_matrix[:-1]

    similarities = cosine_similarity(new_post_vector, existing_vectors).flatten()
    ranked = sorted(zip(existing_posts, similarities), key=lambda x: x[1], reverse=True)

    suggestions: list[LinkSuggestion] = []
    linked_markdown = markdown
    links_inserted = 0

    for post, score in ranked:
        if links_inserted >= settings.max_internal_links:
            break
        if score <= 0.05:  # not topically related enough to force a link
            continue

        anchor_text, linked_markdown_candidate = _try_insert_link(
            linked_markdown, post["tags"], post["url"], post["title"]
        )
        if anchor_text:
            linked_markdown = linked_markdown_candidate
            suggestions.append({
                "anchor_text": anchor_text,
                "target_url": post["url"],
                "target_title": post["title"],
                "similarity": round(float(score), 3),
            })
            links_inserted += 1

    return {"internal_links": suggestions, "linked_markdown": linked_markdown}


def _try_insert_link(markdown: str, tags: list[str], url: str, title: str):
    """Finds the first occurrence of one of the target post's tags in the
    body text (outside headings/links/HTML comments) and wraps it in a
    Markdown link. Returns (anchor_text, new_markdown) or (None, markdown)
    if no safe insertion point was found."""
    for tag in sorted(tags, key=len, reverse=True):  # prefer longer, more specific tags
        pattern = re.compile(rf"(?<!\[)\b({re.escape(tag)})\b(?!\])", re.IGNORECASE)

        for match in pattern.finditer(markdown):
            line_start = markdown.rfind("\n", 0, match.start()) + 1
            line = markdown[line_start:markdown.find("\n", match.start())]
            if line.strip().startswith("#") or line.strip().startswith("<!--"):
                continue  # don't link inside headings or the front-matter block
            anchor = match.group(1)
            new_markdown = (
                markdown[:match.start()]
                + f"[{anchor}]({url})"
                + markdown[match.end():]
            )
            return anchor, new_markdown
    return None, markdown
