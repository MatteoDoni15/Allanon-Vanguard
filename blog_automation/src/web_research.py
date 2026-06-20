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

from src.logging_config import get_logger
from src.state import PipelineState

logger = get_logger("web_research")

_MAX_SNIPPETS = 5
_SNIPPET_MAX_CHARS = 300


def run_web_research(state: PipelineState) -> dict:
    keyword = state["keyword"]
    logger.info(f"Searching web for current info on: '{keyword}'")
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = ddgs.text(keyword, max_results=_MAX_SNIPPETS)
        if not results:
            logger.info(f"Web search returned no results for '{keyword}'")
            return {"web_research_context": ""}
        logger.info(f"Web search found {len(results)} snippet(s) for '{keyword}'")
        lines = []
        for r in results:
            snippet = (r.get("body") or "").strip()[:_SNIPPET_MAX_CHARS]
            source = r.get("href", "")
            if snippet:
                lines.append(f"- {snippet} (source: {source})")
        context = "\n".join(lines)
        logger.info(f"Web research context prepared: {len(context)} chars")
        return {"web_research_context": context}
    except Exception as e:
        logger.warning(f"Web research failed for '{keyword}': {str(e)} - continuing without web context")
        return {"web_research_context": ""}
