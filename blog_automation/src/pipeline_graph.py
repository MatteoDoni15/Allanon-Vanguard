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

from langgraph.graph import StateGraph, END

from src.state import PipelineState
from src.content_generator import generate_content
from src.seo_optimizer import analyze_and_optimize
from src.internal_linking import suggest_internal_links
from src.compliance_judge import run_compliance_judge
from src.policy_fact_check import run_policy_fact_check
from src.semantic_duplicate_check import run_semantic_duplicate_check, index_published_post
from src.quality_gate import run_quality_gate, route_after_quality_gate
from src.publisher import publish, write_review_packet
from src.importance_tagger import tag_importance_from_keyword
from src.voice_profiles import assign_voice_profile


def _increment_retries(state: PipelineState) -> dict:
    """Tiny node used only on the retry path so `retries` increases each loop."""
    return {"retries": state.get("retries", 0) + 1}


def _needs_review(state: PipelineState) -> dict:
    review_fields = write_review_packet(state)
    return {**review_fields, "status": "needs_review"}


def _publish_and_index(state: PipelineState) -> dict:
    result = publish(state)
    # Incremental: only a genuinely auto-published post is added to the
    # published_posts collection, so later drafts get checked against it.
    index_published_post({**state, **result})
    return result


def build_pipeline_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("generate_content", generate_content)
    graph.add_node("seo_optimize", analyze_and_optimize)
    graph.add_node("internal_linking", suggest_internal_links)
    graph.add_node("compliance_judge", run_compliance_judge)
    graph.add_node("policy_fact_check", run_policy_fact_check)
    graph.add_node("duplicate_check", run_semantic_duplicate_check)
    graph.add_node("quality_gate", run_quality_gate)
    graph.add_node("increment_retries", _increment_retries)
    graph.add_node("publish", _publish_and_index)
    graph.add_node("needs_review", _needs_review)

    graph.set_entry_point("generate_content")
    graph.add_edge("generate_content", "seo_optimize")
    graph.add_edge("seo_optimize", "internal_linking")
    graph.add_edge("internal_linking", "compliance_judge")
    graph.add_edge("compliance_judge", "policy_fact_check")
    graph.add_edge("policy_fact_check", "duplicate_check")
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


def run_for_keyword(keyword: str, target_audience: str = "general retail banking customers") -> PipelineState:
    """Convenience entry point: runs the full graph for one keyword."""
    app = build_pipeline_graph()
    initial_state: PipelineState = {
        "keyword": keyword,
        "target_audience": target_audience,
        "retries": 0,
        # Tagged once here, at "keyword input" -- both stay fixed across
        # retries, the same way a topic's sensitivity and a writer's
        # style do not change between draft attempts.
        "importance_tier": tag_importance_from_keyword(keyword),
        "voice_profile": assign_voice_profile(keyword),
    }
    # recursion_limit guards against any unexpected infinite loop in the
    # retry edge; max_generation_retries already bounds it logically.
    return app.invoke(initial_state, config={"recursion_limit": 25})
