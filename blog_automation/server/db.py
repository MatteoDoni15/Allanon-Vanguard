"""
Local SQLite persistence for generated blog posts.

One table, ``blogs``. Each finished pipeline run (whether it ended in
``published`` or ``needs_review``) is stored as one row. The public URL the
user sees -- ``/blog_1``, ``/blog_2`` ... -- is just this row's integer ``id``.

The full pipeline state is kept as JSON in ``state_json`` so the blog detail
page can show everything (SEO report, compliance/fact-check results, internal
links) without the backend having to model every field as its own column.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

import markdown as md

DB_PATH = os.path.join(os.path.dirname(__file__), "blogs.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blogs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword       TEXT NOT NULL,
                title         TEXT,
                slug          TEXT,
                status        TEXT,
                provider      TEXT,
                model         TEXT,
                seo_score     INTEGER,
                word_count    INTEGER,
                markdown      TEXT,
                html          TEXT,
                state_json    TEXT,
                created_at    TEXT NOT NULL
            )
            """
        )


def _render_html(markdown_text: str) -> str:
    body = markdown_text or ""
    # Drop any leading HTML comment front-matter the pipeline may have added.
    if body.startswith("<!--"):
        end = body.find("-->")
        if end != -1:
            body = body[end + 3:].lstrip()
    return md.markdown(body, extensions=["extra", "sane_lists"])


def save_blog(state: dict[str, Any], provider: str, model: str | None) -> int:
    """Persist one finished pipeline state, return its new id (the /blog_N number)."""
    markdown_text = (
        state.get("linked_markdown")
        or state.get("optimized_markdown")
        or state.get("raw_markdown")
        or ""
    )
    seo = state.get("seo_report", {}) or {}
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO blogs (keyword, title, slug, status, provider, model,
                               seo_score, word_count, markdown, html,
                               state_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.get("keyword"),
                state.get("title"),
                seo.get("slug"),
                state.get("status", "unknown"),
                provider,
                model or "",
                seo.get("score"),
                seo.get("word_count"),
                markdown_text,
                _render_html(markdown_text),
                json.dumps(state, default=str),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return int(cur.lastrowid)


def list_blogs() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, keyword, title, slug, status, provider, model,
                   seo_score, word_count, created_at
            FROM blogs ORDER BY id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_blog(blog_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM blogs WHERE id = ?", (blog_id,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["state"] = json.loads(data.pop("state_json") or "{}")
    return data


def delete_blog(blog_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM blogs WHERE id = ?", (blog_id,))
        return cur.rowcount > 0
