"""
Central configuration for the blog automation pipeline.

All tunable parameters live here so the rest of the codebase stays
declarative. Values can be overridden via environment variables (see
.env.example), which is what you'd do differently per environment
(dev / staging / production) when this scales to 700 posts/month.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # --- LLM provider -------------------------------------------------
    # "anthropic" | "openai" | "ollama" | "mock"
    # "mock" requires no API key and is used for local development,
    # CI tests, and the demo run included with this submission.
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "2200"))
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.6"))

    # --- Input-token budgeting (see src/token_budget.py) ----------------
    # `max_tokens` above bounds the *output*; these bound what we *send in*,
    # so an oversized web-research context or draft can never blow the model's
    # input window. They are deliberately generous defaults -- tighten per
    # model via env vars (e.g. a small local Ollama model with an 8k window).
    max_input_tokens: int = int(os.getenv("LLM_MAX_INPUT_TOKENS", "6000"))
    # Budget for the DuckDuckGo web-research context injected into the
    # content-generation prompt; compressed/summarised above this.
    max_context_tokens: int = int(os.getenv("LLM_MAX_CONTEXT_TOKENS", "1200"))
    # Budget for the draft handed to the compliance judge; above this the draft
    # is chunked and judged chunk-by-chunk (never summarised, which could hide
    # a violation).
    max_compliance_draft_tokens: int = int(os.getenv("LLM_MAX_COMPLIANCE_DRAFT_TOKENS", "4000"))
    # When True, oversized context is summarised abstractively via the LLM
    # (chunk -> summarise -> combine). When False (default), the deterministic,
    # offline extractive summariser is used -- no extra cost or latency.
    summarizer_use_llm: bool = os.getenv("SUMMARIZER_USE_LLM", "false").lower() == "true"
    summarizer_chunk_tokens: int = int(os.getenv("SUMMARIZER_CHUNK_TOKENS", "800"))

    # --- Ollama (local models) -----------------------------------------
    # Smart routing: each pipeline task uses the model best suited for it.
    #   content    → gemma4:e2b   (largest, best at long-form writing)
    #   compliance → granite4.1:3b (IBM enterprise model, structured JSON output)
    #   default    → qwen2.5:1.5b  (smallest/fastest, used for anything else)
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_content_model: str = os.getenv("OLLAMA_CONTENT_MODEL", "gemma4:e2b")
    ollama_compliance_model: str = os.getenv("OLLAMA_COMPLIANCE_MODEL", "granite4.1:3b")
    ollama_default_model: str = os.getenv("OLLAMA_DEFAULT_MODEL", "qwen2.5:1.5b")

    # --- Company / brand context ---------------------------------------
    company_name: str = os.getenv("COMPANY_NAME", "NorthLedger Finance")
    industry: str = "FinTech / personal finance & digital banking"
    brand_voice: str = (
        "clear, trustworthy, plain-English, no hype, no guaranteed-return "
        "language, compliant with standard financial-promotion guidelines"
    )

    # --- Content requirements -------------------------------------------
    min_word_count: int = 900
    max_word_count: int = 1500
    target_keyword_density_min: float = 0.5   # % of total words
    target_keyword_density_max: float = 2.5   # %
    min_flesch_reading_ease: float = 45.0     # ~"fairly difficult" or easier
    min_internal_links: int = 2
    max_internal_links: int = 5

    # --- Quality gate / compliance ---------------------------------------
    min_seo_score_to_publish: int = 75        # out of 100
    max_generation_retries: int = 2
    banned_phrases: tuple = (
        "guaranteed return", "guaranteed returns", "risk-free", "zero risk",
        "get rich quick", "no risk", "100% safe investment",
        "can't lose", "insider tip",
    )
    # Written guidelines for the compliance_judge LLM-as-judge node
    # (Part 3, proposal 1). Kept short and explicit on purpose -- this is
    # what a real compliance team's actual guidelines would be pasted
    # into, not a prompt-engineering trick.
    compliance_guidelines: str = (
        "1) Never imply guaranteed or risk-free outcomes. "
        "2) Avoid pressuring or urgency language (e.g. 'act now', 'limited "
        "time', 'don't miss out'). "
        "3) Keep any mention of competitors neutral and factual, never "
        "disparaging. "
        "4) Do not state a specific rate, fee, or numeric claim as if it "
        "were company policy unless it is presented as an example or is "
        "clearly attributed to an official source."
    )

    # --- Publishing schedule (Part 1, Publishing Automation) ---------------
    # A fixed starting window for B2B/finance content typically read
    # during working hours; Part 3's feedback loop is what eventually
    # replaces this fixed guess with a window learned from real traffic.
    publish_window_weekdays: tuple = (1, 2, 3)   # Mon=0 .. Sun=6 -> Tue/Wed/Thu
    publish_window_hour: int = 9

    # --- Paths -------------------------------------------------------------
    existing_content_path: str = os.path.join(
        os.path.dirname(__file__), "data", "existing_site_content.json"
    )
    company_policies_path: str = os.path.join(
        os.path.dirname(__file__), "data", "company_policies.json"
    )
    output_dir: str = os.path.join(os.path.dirname(__file__), "outputs")

    # --- Publishing (WordPress REST API example) ---------------------------
    wp_base_url: str = os.getenv("WP_BASE_URL", "https://www.example-fintech.com")
    wp_username: str = os.getenv("WP_USERNAME", "")
    wp_app_password: str = os.getenv("WP_APP_PASSWORD", "")
    dry_run_publish: bool = os.getenv("DRY_RUN_PUBLISH", "true").lower() == "true"


settings = Settings()
