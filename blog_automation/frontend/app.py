"""
Streamlit frontend for the blog automation pipeline.

Launch from the blog_automation/ directory:
    streamlit run frontend/app.py

Lets you:
  - Enter one or more keywords (one per line)
  - Choose the LLM provider (mock / ollama / anthropic / openai)
  - See a per-keyword results panel with status, scores, content preview,
    and all check details (SEO, compliance, fact-check, duplicate check)
"""

from __future__ import annotations

import os
import sys
import time

import streamlit as st

# Make `src/` importable from this subdirectory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Blog Automation Pipeline",
    page_icon="✍️",
    layout="wide",
)

st.title("✍️ Blog Automation Pipeline")
st.caption("Genera, ottimizza e verifica post per NorthLedger Finance")

# ── sidebar — provider & options ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configurazione")

    provider = st.selectbox(
        "LLM Provider",
        options=["mock", "ollama", "anthropic", "openai"],
        index=0,
        help=(
            "mock: nessuna API key, output deterministico\n"
            "ollama: modelli locali (gemma4 → contenuto, granite → compliance, qwen → default)\n"
            "anthropic / openai: richiede API key in .env"
        ),
    )

    if provider == "ollama":
        st.info(
            "**Routing automatico Ollama:**\n"
            "- `gemma4:e2b` → content generation\n"
            "- `granite4.1:3b` → compliance judge\n"
            "- `qwen2.5:1.5b` → default\n\n"
            "Modificabile via env vars in `.env`"
        )
        ollama_url = st.text_input("Ollama base URL", value="http://localhost:11434")
    elif provider == "anthropic":
        st.warning("Richiede `ANTHROPIC_API_KEY` in `.env`")
    elif provider == "openai":
        st.warning("Richiede `OPENAI_API_KEY` in `.env`")

    target_audience = st.text_input(
        "Target audience",
        value="general retail banking customers",
    )

    st.markdown("---")
    st.markdown(
        "**Pipeline attiva:**\n"
        "1. 🌐 Web Research\n"
        "2. ✍️ Content Generation\n"
        "3. 📊 SEO Optimize\n"
        "4. 🔗 Internal Linking\n"
        "5. ⚖️ Compliance Judge\n"
        "6. 📋 Policy Fact-Check\n"
        "7. 🔍 Web Fact-Check\n"
        "8. 🔁 Duplicate Check\n"
        "9. 🚦 Quality Gate\n"
        "10. 🚀 Publish / Review"
    )

# ── main input area ───────────────────────────────────────────────────────────
keywords_raw = st.text_area(
    "Keywords (una per riga)",
    placeholder="how to start investing\nhow to improve your credit score\nbest budgeting apps for beginners",
    height=120,
)

run_btn = st.button("▶️ Esegui pipeline", type="primary", use_container_width=True)

# ── run ───────────────────────────────────────────────────────────────────────
if run_btn:
    keywords = [k.strip() for k in keywords_raw.splitlines() if k.strip()]
    if not keywords:
        st.error("Inserisci almeno un keyword.")
        st.stop()

    # Override provider via env so the pipeline picks it up
    os.environ["LLM_PROVIDER"] = provider
    if provider == "ollama":
        os.environ["OLLAMA_BASE_URL"] = ollama_url

    # Import here so env vars are set before config is read
    from src.pipeline_graph import run_for_keyword  # noqa: E402

    for kw in keywords:
        st.markdown(f"---\n### 🔑 `{kw}`")
        progress = st.progress(0, text="Avvio pipeline...")
        t0 = time.time()

        try:
            # LangGraph is synchronous — run directly
            progress.progress(10, text="🌐 Web research...")
            state = run_for_keyword(kw, target_audience=target_audience)
            elapsed = time.time() - t0
            progress.progress(100, text=f"Completato in {elapsed:.1f}s")
        except Exception as exc:
            progress.empty()
            st.error(f"Errore pipeline: {exc}")
            continue

        # ── status badge ──────────────────────────────────────────────────
        status = state.get("status", "unknown")
        badge = {"published": "🟢", "needs_review": "🟡", "rejected": "🔴"}.get(status, "⚪")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Status", f"{badge} {status}")
        col2.metric("SEO Score", f"{state.get('seo_report', {}).get('score', '—')}/100")
        col3.metric("Parole", state.get("seo_report", {}).get("word_count", "—"))
        col4.metric("Retry", state.get("retries", 0))

        # ── voice & importance ────────────────────────────────────────────
        st.caption(
            f"Voice profile: `{state.get('voice_profile', '—')}`  |  "
            f"Importance tier: `{state.get('importance_tier', '—')}`  |  "
            f"Tempo: `{elapsed:.1f}s`"
        )

        # ── check results ─────────────────────────────────────────────────
        checks_col, content_col = st.columns([1, 2])

        with checks_col:
            st.subheader("Checks")

            def _check_row(label: str, result: dict) -> None:
                passed = result.get("passed", True)
                icon = "✅" if passed else "❌"
                with st.expander(f"{icon} {label}", expanded=not passed):
                    reasons = result.get("reasons", [])
                    if reasons:
                        for r in reasons:
                            st.warning(r)
                    else:
                        st.success("Nessun problema rilevato.")

            _check_row("Compliance Judge", state.get("compliance", {"passed": True, "reasons": []}))
            _check_row("Policy Fact-Check", state.get("fact_check", {"passed": True, "reasons": []}))
            _check_row("Web Fact-Check", state.get("web_fact_check", {"passed": True, "reasons": []}))
            _check_row("Duplicate Check", state.get("duplicate_check", {"passed": True, "reasons": []}))
            _check_row("Quality Gate", state.get("quality", {"passed": True, "reasons": []}))

            # Internal links
            links = state.get("internal_links", [])
            with st.expander(f"🔗 Internal links ({len(links)})", expanded=False):
                if links:
                    for lk in links:
                        st.markdown(
                            f"- **{lk['anchor_text']}** → `{lk['target_url']}` "
                            f"(sim={lk['similarity']})"
                        )
                else:
                    st.info("Nessun link interno suggerito.")

        with content_col:
            st.subheader("Contenuto generato")
            title = state.get("title", kw)
            st.markdown(f"**{title}**")

            seo = state.get("seo_report", {})
            seo_cols = st.columns(3)
            seo_cols[0].metric("Flesch ease", f"{seo.get('flesch_reading_ease', '—'):.1f}" if seo.get("flesch_reading_ease") else "—")
            seo_cols[1].metric("KW density", f"{seo.get('keyword_density_pct', '—'):.2f}%" if seo.get("keyword_density_pct") else "—")
            seo_cols[2].metric("Slug", seo.get("slug", "—"))

            with st.expander("📄 Anteprima contenuto (markdown)", expanded=False):
                md = state.get("linked_markdown") or state.get("optimized_markdown") or state.get("raw_markdown", "")
                st.markdown(md if md else "_Nessun contenuto disponibile._")

            if state.get("publish_result", {}).get("url"):
                st.success(f"File output: `{state['publish_result']['url']}`")
            if state.get("canonical_url"):
                st.info(f"Canonical URL: `{state['canonical_url']}`")
            if state.get("scheduled_publish_at"):
                st.info(f"Pubblicazione schedulata: `{state['scheduled_publish_at']}`")

    st.markdown("---")
    st.success("Pipeline completata per tutti i keyword.")
