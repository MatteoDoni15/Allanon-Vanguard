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
    state = json.loads(data.pop("state_json") or "{}")
    data["state"] = state
    # Surface every pipeline node's output as an ordered, display-friendly list
    # so the frontend can show what each step produced (web-research snippets,
    # SEO findings, fact-check reasons, ...) -- not just the final post. Built
    # on read from the already-persisted state, so it also works for older rows.
    data["steps"] = _build_pipeline_steps(state)
    return data


def _fmt_score(value: Any) -> str:
    return f"{value:.2f}" if isinstance(value, (int, float)) else str(value)


def _build_pipeline_steps(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the saved pipeline state into an ordered list of per-step outputs.

    Each step is ``{key, label, summary?, status?, text?, items?}`` where
    ``status`` is ``"pass"``/``"fail"`` for the check nodes, ``text`` is a long
    free-text block (web research, the raw draft) and ``items`` is a bullet list
    (SEO findings, internal links, fact-check reasons). The frontend renders any
    of these generically.
    """
    seo = state.get("seo_report") or {}
    links = state.get("internal_links") or []

    def _check(res: Any) -> tuple[str | None, list[str]]:
        if not isinstance(res, dict):
            return None, []
        status = "pass" if res.get("passed", True) else "fail"
        return status, [str(r) for r in (res.get("reasons") or [])]

    steps: list[dict[str, Any]] = [
        {
            "key": "web_research",
            "label": "🌐 Ricerca Web",
            "summary": "Snippet recuperati da internet (DuckDuckGo) e usati come contesto.",
            "text": (state.get("web_research_context") or "").strip(),
        },
        {
            "key": "generate_content",
            "label": "✍️ Generazione contenuto",
            "summary": f"Titolo: {state.get('title') or '—'} · {state.get('retries', 0)} retry",
            "text": (state.get("raw_markdown") or "").strip(),
        },
        {
            "key": "seo_optimize",
            "label": "📊 Ottimizzazione SEO",
            "summary": (
                f"Score {seo.get('score', '—')}/100 · {seo.get('word_count', '—')} parole · "
                f"Flesch {seo.get('flesch_reading_ease', '—')} · "
                f"density {seo.get('keyword_density_pct', '—')}%"
            ),
            "items": list(seo.get("issues") or []) + list(seo.get("suggestions") or []),
        },
        {
            "key": "internal_linking",
            "label": "🔗 Link interni",
            "summary": f"{len(links)} link suggeriti",
            "items": [
                f"{lk.get('anchor_text')} → {lk.get('target_url')} (sim. {_fmt_score(lk.get('similarity'))})"
                for lk in links
            ],
        },
    ]

    for key, label, res in [
        ("compliance", "⚖️ Compliance Judge", state.get("compliance")),
        ("fact_check", "📋 Policy Fact-Check", state.get("fact_check")),
        ("web_fact_check", "🔍 Web Fact-Check", state.get("web_fact_check")),
        ("duplicate_check", "🔁 Duplicate Check", state.get("duplicate_check")),
        ("quality", "🚦 Quality Gate", state.get("quality")),
    ]:
        status, reasons = _check(res)
        step = {"key": key, "label": label, "status": status, "items": reasons}
        if key == "duplicate_check" and isinstance(res, dict):
            matches = res.get("matches") or []
            step["items"] = step["items"] + [
                f"Simile: {m.get('title')} ({_fmt_score(m.get('score'))}) {m.get('url', '')}".strip()
                for m in matches
            ]
        steps.append(step)

    pub_items: list[str] = []
    if state.get("ai_disclosure"):
        pub_items.append(f"AI disclosure: {state['ai_disclosure']}")
    if state.get("canonical_url"):
        pub_items.append(f"Canonical URL: {state['canonical_url']}")
    if state.get("scheduled_publish_at"):
        pub_items.append(f"Programmato per: {state['scheduled_publish_at']}")
    pub_url = (state.get("publish_result") or {}).get("url")
    if pub_url:
        pub_items.append(f"File: {pub_url}")
    steps.append({
        "key": "publish",
        "label": "🚀 Pubblicazione",
        "summary": f"Stato finale: {state.get('status', '—')}",
        "items": pub_items,
    })

    return steps


def delete_blog(blog_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM blogs WHERE id = ?", (blog_id,))
        return cur.rowcount > 0
