"""
Step 5 of the pipeline: Publishing Automation.

Targets the WordPress REST API as a concrete, widely-used example (many
FinTech marketing sites run on WordPress or a headless WP backend), but
the function signature is generic enough to swap for Contentful,
Webflow, or a custom CMS endpoint.

`settings.dry_run_publish` defaults to True: instead of making a real
HTTP call, the post is converted to HTML and written to outputs/, plus
a JSON manifest with all SEO/compliance metadata. This lets the entire
pipeline be demoed and graded without live website credentials, while
the real `requests.post(...)` call below is exactly what would run in
production once WP_USERNAME/WP_APP_PASSWORD are set.

This node also writes three pieces of metadata described in Part 1 and
Part 3 of the design document:
  - a canonical URL tag, so the same content reachable from more than
    one URL (a trailing slash, a tracking parameter) is not treated as
    duplicate content by search engines;
  - a scheduled publish slot, using a fixed weekday/time window as the
    starting default (see config.py);
  - an AI-content disclosure string, whose wording depends on which
    path through the risk-tiered gate the post took -- see
    `_build_disclosure` below.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import markdown as md
import requests

from config import settings
from src.state import PipelineState


def publish(state: PipelineState) -> dict:
    """Auto-publish path -- only reached when the risk-tiered gate clears
    a draft for an unattended publish (Part 3, proposal 4)."""
    payload = _build_payload(state, disclosure="Generated using artificial intelligence.")

    if settings.dry_run_publish:
        result = _dry_run_write(state, payload, status="published")
    else:
        result = _publish_to_wordpress(payload)

    return {
        "publish_result": result,
        "status": result.get("status", "draft"),
        "canonical_url": payload["meta"]["canonical_url"],
        "scheduled_publish_at": payload["scheduled_at"],
        "ai_disclosure": payload["meta"]["ai_disclosure"],
    }


def write_review_packet(state: PipelineState) -> dict:
    """needs_review path -- writes the same kind of artifact a publish
    would, but tagged for human review, with the reviewer-disclosure
    template (Part 3, proposal 4) instead of the auto-publish one. This
    is what gives the human-review queue something concrete to act on,
    rather than a bare status flag with no content attached."""
    payload = _build_payload(
        state,
        disclosure="Drafted with AI assistance, reviewed and approved by [Reviewer Name].",
    )
    result = _dry_run_write(state, payload, status="needs_review")
    return {
        "publish_result": result,
        "canonical_url": payload["meta"]["canonical_url"],
        "scheduled_publish_at": payload["scheduled_at"],
        "ai_disclosure": payload["meta"]["ai_disclosure"],
    }


def _build_payload(state: PipelineState, disclosure: str) -> dict:
    html_body = md.markdown(_strip_front_matter(state["linked_markdown"]))
    seo = state["seo_report"]
    canonical_url = f"{settings.wp_base_url.rstrip('/')}/blog/{seo['slug']}/"
    scheduled_at = _next_publish_slot()

    return {
        "title": state["title"],
        "slug": seo["slug"],
        "content": html_body,
        "meta": {
            "meta_title": seo["meta_title"],
            "meta_description": seo["meta_description"],
            "canonical_url": canonical_url,
            "ai_disclosure": disclosure,
        },
        "scheduled_at": scheduled_at.isoformat(),
    }


def _next_publish_slot(now: datetime | None = None) -> datetime:
    """Next datetime matching the configured weekday/hour window."""
    now = now or datetime.now(timezone.utc)
    candidate = now.replace(hour=settings.publish_window_hour, minute=0, second=0, microsecond=0)
    for _ in range(8):  # at most one week out
        if candidate.weekday() in settings.publish_window_weekdays and candidate > now:
            return candidate
        candidate += timedelta(days=1)
    return candidate


def _publish_to_wordpress(payload: dict) -> dict:
    """Real call -- requires WP_BASE_URL / WP_USERNAME / WP_APP_PASSWORD."""
    response = requests.post(
        f"{settings.wp_base_url}/wp-json/wp/v2/posts",
        auth=(settings.wp_username, settings.wp_app_password),
        json={
            "title": payload["title"],
            "slug": payload["slug"],
            "content": payload["content"],
            # Scheduled rather than immediate, per the publish window above;
            # WordPress publishes automatically once `date` is reached.
            "status": "future",
            "date": payload["scheduled_at"],
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return {"status": "published", "url": data.get("link"), "cms_id": data.get("id")}


def _dry_run_write(state: PipelineState, payload: dict, status: str) -> dict:
    os.makedirs(settings.output_dir, exist_ok=True)
    base = payload["slug"] or "untitled-post"
    suffix = "" if status == "published" else ".review"

    html_path = os.path.join(settings.output_dir, f"{base}{suffix}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(f"<title>{payload['meta']['meta_title']}</title>\n")
        f.write(f"<meta name='description' content=\"{payload['meta']['meta_description']}\">\n")
        f.write(f"<link rel=\"canonical\" href=\"{payload['meta']['canonical_url']}\">\n")
        f.write(f"<!-- status: {status} -->\n")
        f.write(f"<!-- AI disclosure: {payload['meta']['ai_disclosure']} -->\n")
        f.write(f"<!-- Scheduled for: {payload['scheduled_at']} -->\n")
        f.write(payload["content"])

    manifest_path = os.path.join(settings.output_dir, f"{base}{suffix}.manifest.json")
    manifest = {
        "title": state["title"],
        "keyword": state["keyword"],
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "voice_profile": state.get("voice_profile"),
        "importance_tier": state.get("importance_tier"),
        "seo_report": state["seo_report"],
        "internal_links": state.get("internal_links", []),
        "compliance": state.get("compliance", {}),
        "quality": state.get("quality", {}),
        "canonical_url": payload["meta"]["canonical_url"],
        "scheduled_publish_at": payload["scheduled_at"],
        "ai_disclosure": payload["meta"]["ai_disclosure"],
        "html_file": html_path,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    verb = "published" if status == "published" else "needs_review"
    return {"status": verb, "url": f"(dry-run) file://{html_path}", "manifest": manifest_path}


def _strip_front_matter(markdown_text: str) -> str:
    if markdown_text.startswith("<!--"):
        end = markdown_text.find("-->")
        if end != -1:
            return markdown_text[end + 3:].lstrip()
    return markdown_text
