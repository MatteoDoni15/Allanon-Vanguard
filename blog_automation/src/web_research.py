"""
Web research node: queries DuckDuckGo for current snippets on the target
keyword before content generation. The collected snippets are stored in
`web_research_context` and injected into the content_generator prompt so
the LLM can reference real, up-to-date data rather than relying solely
on training knowledge.

Non-blocking: on any search error (network failure, rate limit, missing
package) the node returns an empty context and the pipeline continues
normally -- the post is written without external research rather than
failing.
"""

from __future__ import annotations

from src.state import PipelineState

_MAX_SNIPPETS = 5
_SNIPPET_MAX_CHARS = 300


def run_web_research(state: PipelineState) -> dict:
    keyword = state["keyword"]
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = ddgs.text(keyword, max_results=_MAX_SNIPPETS)
        if not results:
            return {"web_research_context": ""}
        lines = []
        for r in results:
            snippet = (r.get("body") or "").strip()[:_SNIPPET_MAX_CHARS]
            source = r.get("href", "")
            if snippet:
                lines.append(f"- {snippet} (source: {source})")
        return {"web_research_context": "\n".join(lines)}
    except Exception:
        return {"web_research_context": ""}
