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
        # Engagement feedback per published post (Part 3, proposal 3 -- the
        # feedback loop). One row per metrics submission; the latest row per
        # blog is what the keyword-priority recompute reads. This table is the
        # historical dataset that later lets a cheap classifier replace the LLM
        # judge (see DESIGN_DOCUMENT Appendix C.4).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                blog_id       INTEGER NOT NULL,
                impressions   INTEGER NOT NULL DEFAULT 0,
                clicks        INTEGER NOT NULL DEFAULT 0,
                avg_time_sec  REAL NOT NULL DEFAULT 0,
                conversions   INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL,
                FOREIGN KEY (blog_id) REFERENCES blogs(id) ON DELETE CASCADE
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


def approve_blog(blog_id: int, reviewer: str = "human reviewer") -> bool:
    """Mark a needs_review blog as human-approved → published.

    Updates both the top-level ``status`` column and the ``status`` inside the
    saved ``state_json`` (the source of truth the detail page reads), and stamps
    who approved it and when. Returns False if the blog doesn't exist or wasn't
    actually awaiting review.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT status, state_json FROM blogs WHERE id = ?", (blog_id,)
        ).fetchone()
        if row is None or row["status"] != "needs_review":
            return False
        state = json.loads(row["state_json"] or "{}")
        state["status"] = "published"
        state["review"] = {
            "approved_by": reviewer,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        conn.execute(
            "UPDATE blogs SET status = ?, state_json = ? WHERE id = ?",
            ("published", json.dumps(state, default=str), blog_id),
        )
        return True


# --- Feedback loop (Part 3, proposal 3) ---------------------------------------

def save_feedback(
    blog_id: int,
    impressions: int,
    clicks: int,
    avg_time_sec: float,
    conversions: int = 0,
) -> int:
    """Store one engagement-metrics submission for a blog. Returns its row id."""
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO feedback (blog_id, impressions, clicks, avg_time_sec,
                                  conversions, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(blog_id),
                int(impressions),
                int(clicks),
                float(avg_time_sec),
                int(conversions),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return int(cur.lastrowid)


def list_feedback() -> list[dict[str, Any]]:
    """Latest metrics per blog, joined with the blog's keyword/title."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT f.blog_id, b.keyword, b.title,
                   f.impressions, f.clicks, f.avg_time_sec, f.conversions,
                   f.created_at
            FROM feedback f
            JOIN blogs b ON b.id = f.blog_id
            JOIN (
                SELECT blog_id, MAX(id) AS max_id FROM feedback GROUP BY blog_id
            ) latest ON latest.max_id = f.id
            ORDER BY f.blog_id
            """
        ).fetchall()
    return [dict(r) for r in rows]


def history_for_priority() -> list[dict[str, Any]]:
    """Past posts with their latest engagement metrics, for the keyword-priority
    recompute. Posts with no feedback yet are included with ``metrics=None`` so
    the caller can decide how to treat them (here: ignored in scoring)."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT b.id AS blog_id, b.keyword, b.title,
                   f.impressions, f.clicks, f.avg_time_sec, f.conversions
            FROM blogs b
            LEFT JOIN (
                SELECT blog_id, MAX(id) AS max_id FROM feedback GROUP BY blog_id
            ) latest ON latest.blog_id = b.id
            LEFT JOIN feedback f ON f.id = latest.max_id
            ORDER BY b.id
            """
        ).fetchall()
    history: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        has_metrics = d.get("impressions") is not None
        history.append({
            "blog_id": d["blog_id"],
            "keyword": d.get("keyword") or "",
            "title": d.get("title") or "",
            "metrics": (
                {
                    "impressions": d["impressions"],
                    "clicks": d["clicks"],
                    "avg_time_sec": d["avg_time_sec"],
                    "conversions": d["conversions"],
                }
                if has_metrics else None
            ),
        })
    return history
