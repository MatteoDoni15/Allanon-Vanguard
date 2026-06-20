"""
Pipeline orchestration with LangGraph.

This is Part 4 of the assignment ("Designing the Workflow") expressed
as runnable code rather than just a diagram. LangGraph was chosen over
a plain linear script because two things in the spec are not linear:

  1. Quality gate retries: if compliance/SEO checks fail, the workflow
     needs to loop back to content generation (with feedback) rather
     than just failing. That is a cycle in the graph, which LangGraph
     supports natively (`add_conditional_edges`) and a simple
     function-call chain does not, without hand-rolled while-loops.
  2. Human-in-the-loop fallback: after N failed retries, OR whenever the
     topic itself is tagged high-importance regardless of draft quality
     (see importance_tagger.py and Part 3, proposal 4 of the design
     document), the graph routes to a `needs_review` terminal node
     instead of publishing or crashing -- the natural place to later
     add LangGraph's `interrupt()` for an actual human approval step.

      keyword_input (tags importance_tier + voice_profile)
            |
            v
      web_research  (DuckDuckGo snippets -- runs once, not on retry)
            |
            v
      generate_content  <----------------+
            |                            | retry (feedback attached)
            v                            |
      seo_optimize                       |
            |                            |
            v                            |
      internal_linking                   |
            |                            |
            v                            |
      compliance_judge                   |
            |                            |
            v                            |
      policy_fact_check  (lightweight RAG against company_policies)
            |                            |
            v                            |
      web_fact_check  (DuckDuckGo external claim verification)
            |                            |
            v                            |
      duplicate_check  (vs published_posts collection)
            |                            |
            v                            |
      quality_gate ---- quality fails ---+
        |        \\        & retries left
   pass |         \\
  & std |          v
  imp.  |     needs_review  <-- also reached directly when
        v                       importance_tier == "high",
     publish                    even if quality_passed
   (then indexes the post into
    published_posts for future
    duplicate checks)
"""

from __future__ import annotations

from typing import Callable

from langgraph.graph import StateGraph, END

from src.logging_config import get_logger
from src.state import PipelineState
from src.content_generator import generate_content
from src.seo_optimizer import analyze_and_optimize
from src.internal_linking import suggest_internal_links
from src.compliance_judge import run_compliance_judge
from src.policy_fact_check import run_policy_fact_check
from src.web_research import run_web_research
from src.web_fact_check import run_web_fact_check
from src.semantic_duplicate_check import run_semantic_duplicate_check, index_published_post
from src.quality_gate import run_quality_gate, route_after_quality_gate
from src.publisher import publish, write_review_packet
from src.importance_tagger import tag_importance_from_keyword
from src.voice_profiles import assign_voice_profile

logger = get_logger("pipeline")


def _increment_retries(state: PipelineState) -> dict:
    """Tiny node used only on the retry path so `retries` increases each loop."""
    new_retry_count = state.get("retries", 0) + 1
    logger.info(f"Retrying content generation (attempt {new_retry_count})")
    return {"retries": new_retry_count}


def _needs_review(state: PipelineState) -> dict:
    logger.warning(f"Routing to human review - importance_tier={state.get('importance_tier')}, retries={state.get('retries')}")
    review_fields = write_review_packet(state)
    return {**review_fields, "status": "needs_review"}


def _publish_and_index(state: PipelineState) -> dict:
    logger.info(f"Publishing post: '{state.get('title')}'")
    result = publish(state)
    index_published_post({**state, **result})
    logger.info(f"Post published and indexed successfully")
    return result


def build_pipeline_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("web_research", run_web_research)
    graph.add_node("generate_content", generate_content)
    graph.add_node("seo_optimize", analyze_and_optimize)
    graph.add_node("internal_linking", suggest_internal_links)
    graph.add_node("compliance_judge", run_compliance_judge)
    graph.add_node("policy_fact_check", run_policy_fact_check)
    graph.add_node("web_fact_check", run_web_fact_check)
    graph.add_node("duplicate_check", run_semantic_duplicate_check)
    graph.add_node("quality_gate", run_quality_gate)
    graph.add_node("increment_retries", _increment_retries)
    graph.add_node("publish", _publish_and_index)
    graph.add_node("needs_review", _needs_review)

    graph.set_entry_point("web_research")
    graph.add_edge("web_research", "generate_content")
    graph.add_edge("generate_content", "seo_optimize")
    graph.add_edge("seo_optimize", "internal_linking")
    graph.add_edge("internal_linking", "compliance_judge")
    graph.add_edge("compliance_judge", "policy_fact_check")
    graph.add_edge("policy_fact_check", "web_fact_check")
    graph.add_edge("web_fact_check", "duplicate_check")
    graph.add_edge("duplicate_check", "quality_gate")

    graph.add_conditional_edges(
        "quality_gate",
        route_after_quality_gate,
        {
            "publish": "publish",
            "retry": "increment_retries",
            "needs_review": "needs_review",
        },
    )
    graph.add_edge("increment_retries", "generate_content")  # the loop-back edge
    graph.add_edge("publish", END)
    graph.add_edge("needs_review", END)

    return graph.compile()


# Human-friendly labels for each graph node, in display order. Used by the
# web frontend to render the "node by node" progress timeline, and kept here
# (next to the graph definition) so a new node automatically has one place to
# document itself for the UI.
NODE_LABELS: dict[str, str] = {
    "web_research": "🌐 Web Research",
    "generate_content": "✍️ Content Generation",
    "seo_optimize": "📊 SEO Optimize",
    "internal_linking": "🔗 Internal Linking",
    "compliance_judge": "⚖️ Compliance Judge",
    "policy_fact_check": "📋 Policy Fact-Check",
    "web_fact_check": "🔍 Web Fact-Check",
    "duplicate_check": "🔁 Duplicate Check",
    "quality_gate": "🚦 Quality Gate",
    "increment_retries": "🔄 Retry (regenerating)",
    "publish": "🚀 Publish",
    "needs_review": "🟡 Needs Review",
}

# The "happy path" order, used to compute a progress percentage in the UI.
NODE_ORDER: list[str] = [
    "web_research", "generate_content", "seo_optimize", "internal_linking",
    "compliance_judge", "policy_fact_check", "web_fact_check",
    "duplicate_check", "quality_gate", "publish",
]


def _recursion_limit() -> int:
    """Step budget for one full run, worst case.

    Each retry re-runs ~9 nodes (generate -> ... -> quality_gate -> increment),
    so exhausting ``max_generation_retries`` and then routing to needs_review
    needs roughly ``(retries + 1) * 9 + a few`` super-steps. The original fixed
    25 was just short of that for 2 retries, which made a draft that could
    never pass quality crash with a GRAPH_RECURSION_LIMIT error instead of
    landing in needs_review. We size the budget from the configured retry
    count (with margin) so that path always terminates cleanly.
    """
    from config import settings  # local import: keep module import side-effect free
    return (settings.max_generation_retries + 1) * 10 + 5


def _initial_state(keyword: str, target_audience: str) -> PipelineState:
    importance = tag_importance_from_keyword(keyword)
    voice = assign_voice_profile(keyword)
    logger.info(f"Initializing pipeline state - keyword='{keyword}', importance={importance}, voice={voice}")
    return {
        "keyword": keyword,
        "target_audience": target_audience,
        "retries": 0,
        "importance_tier": importance,
        "voice_profile": voice,
    }


def run_for_keyword(keyword: str, target_audience: str = "general retail banking customers") -> PipelineState:
    """Convenience entry point: runs the full graph for one keyword."""
    logger.info(f"Starting pipeline run: keyword='{keyword}'")
    app = build_pipeline_graph()
    return app.invoke(
        _initial_state(keyword, target_audience),
        config={"recursion_limit": _recursion_limit()},
    )


def stream_for_keyword(
    keyword: str,
    target_audience: str = "general retail banking customers",
    on_node: Callable[[str, dict, PipelineState], None] | None = None,
) -> PipelineState:
    """Run the graph for one keyword, invoking ``on_node`` after every node.

    Same result as ``run_for_keyword`` but observable: LangGraph's
    ``.stream(stream_mode="updates")`` yields ``{node_name: partial_update}``
    after each node finishes, which is exactly the granularity the web UI
    needs to draw its node-by-node progress. We merge those partial updates
    into a running copy of the state ourselves (updates mode does not carry
    the full state), so the returned object matches ``run_for_keyword``.
    """
    logger.info(f"Starting streaming pipeline run: keyword='{keyword}'")
    app = build_pipeline_graph()
    state: PipelineState = dict(_initial_state(keyword, target_audience))
    for chunk in app.stream(state, config={"recursion_limit": _recursion_limit()}, stream_mode="updates"):
        for node_name, update in chunk.items():
            if update:
                state.update(update)
            if on_node is not None:
                on_node(node_name, update or {}, state)
    logger.info(f"Pipeline execution complete for keyword='{keyword}' - final status={state.get('status')}")
    return state
