"""
Step 2 of the pipeline: Content Generation.

Builds an SEO-aware prompt around a single target keyword and the
company's brand voice, then calls the configured LLM provider. The
prompt explicitly asks for the structural elements an SEO pass will
later check (H1, H2s, target word count, natural keyword placement),
which dramatically reduces how much the SEO step has to "fix" after
the fact.
"""

from __future__ import annotations

from config import settings
from src.state import PipelineState
from src.llm_providers import get_llm_provider
from src.voice_profiles import get_voice_directive

SYSTEM_PROMPT_TEMPLATE = """\
You are a senior content writer for {company}, a company in the \
{industry} space. Brand voice and tone: {brand_voice}.

{voice_directive}

Rules:
- Never promise guaranteed returns, "risk-free" outcomes, or speculative \
financial advice. Always include the idea that individual circumstances \
vary, where relevant.
- Write for a general audience with no finance background unless told \
otherwise.
- Use Markdown with exactly one H1 (#) and several H2 sections (##).
- Target length: {min_words}-{max_words} words.
- Naturally include the target keyword in the H1, the first 100 words, \
and 2-4 more times in the body -- never force it unnaturally.
"""

USER_PROMPT_TEMPLATE = """\
TARGET_KEYWORD: {keyword}
TARGET_AUDIENCE: {audience}

Write a complete, publish-ready blog post optimized for the target \
keyword above. Include:
1. An H1 title containing the keyword.
2. A short, engaging introduction (naturally includes the keyword).
3. 3-5 H2 sections covering practical, actionable guidance.
4. A short "Key Takeaways" section near the end.

{revision_note}
"""


def generate_content(state: PipelineState) -> dict:
    """LangGraph node: produces `raw_markdown` and `title` from `keyword`."""
    provider = get_llm_provider()

    revision_note = ""
    if state.get("quality", {}).get("reasons"):
        # Loop-back path: the quality gate rejected the previous draft.
        # Feed its reasons back into the prompt so the regenerated draft
        # specifically addresses them (this is the LangGraph retry edge).
        reasons = "; ".join(state["quality"]["reasons"])
        revision_note = (
            f"IMPORTANT: a previous draft was rejected for these reasons: "
            f"{reasons}. Fix these specifically in this new draft."
        )

    # voice_profile is assigned once at keyword input (see
    # pipeline_graph.run_for_keyword) and stays fixed across retries here --
    # a writer's style does not change between draft attempts.
    voice_directive = get_voice_directive(state.get("voice_profile", ""))
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        company=settings.company_name,
        industry=settings.industry,
        brand_voice=settings.brand_voice,
        voice_directive=voice_directive,
        min_words=settings.min_word_count,
        max_words=settings.max_word_count,
    )

    user_prompt = USER_PROMPT_TEMPLATE.format(
        keyword=state["keyword"],
        audience=state.get("target_audience", "general retail banking customers"),
        revision_note=revision_note,
    )

    markdown = provider.generate(system_prompt, user_prompt)
    title = _extract_title(markdown, fallback=state["keyword"].title())

    return {
        "raw_markdown": markdown,
        "title": title,
        "retries": state.get("retries", 0),
    }


def _extract_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line.lstrip("#").strip()
    return fallback
