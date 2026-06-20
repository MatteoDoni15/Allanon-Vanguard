"""
Input-token budgeting: keep what we send to an LLM inside a token budget.

Two things in this pipeline can grow without bound and blow past a model's
input window:

  * ``web_research_context`` -- DuckDuckGo snippets injected into the content
    generation prompt (see content_generator.py);
  * the full draft handed to the compliance judge (see compliance_judge.py).

This module provides the controls to bound both:

  * ``estimate_tokens``      -- cheap, offline token estimate (optionally exact
                                via tiktoken if it happens to be installed).
  * ``chunk_by_tokens``      -- the chunker: split long text into pieces that
                                each fit a token budget, on paragraph/sentence
                                boundaries (never mid-word).
  * ``truncate_to_budget``   -- last-resort hard cut on a clean boundary.
  * ``extractive_summarize`` -- deterministic, dependency-free summary (ranks
                                sentences, keeps the most informative ones).
  * ``compress_to_budget``   -- the main entry point: if the text already fits,
                                return it unchanged; otherwise summarise it down
                                to the budget. Uses the LLM for an abstractive
                                summary when ``summarizer_use_llm`` is on (map
                                over chunks, reduce into one summary); otherwise
                                -- and always for the Mock provider, which can't
                                summarise -- falls back to the extractive path.

Everything works offline with zero extra dependencies; tiktoken and an LLM
summariser are optional accelerators, not requirements.
"""

from __future__ import annotations

import re
from collections import Counter

from config import settings

# Rough bytes-per-token for English text. Deliberately on the low side (real
# text is ~4 chars/token) so our estimate slightly *over*-counts tokens and we
# stay safely under the real limit rather than just over it.
_CHARS_PER_TOKEN = 4

# Small English stop-word set so extractive scoring rewards content words, not
# "the/and/of". Kept tiny on purpose -- this is a budgeter, not an NLP library.
_STOPWORDS = frozenset(
    "the a an and or but of to in on for with as at by from is are was were be "
    "been being this that these those it its their his her your our you we they "
    "i he she them us not no yes do does did has have had will would can could "
    "should may might must if then than so such about into over under more most "
    "can't will not also which who whom whose what when where why how".split()
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text``.

    Uses tiktoken when available (exact for OpenAI, a good proxy elsewhere),
    otherwise a conservative chars/4 heuristic. Never raises.
    """
    if not text:
        return 0
    try:  # optional: only if the user already has tiktoken installed
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN


def within_budget(text: str, max_tokens: int) -> bool:
    return estimate_tokens(text) <= max_tokens


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def chunk_by_tokens(text: str, chunk_tokens: int) -> list[str]:
    """Split ``text`` into chunks that each fit ~``chunk_tokens`` tokens.

    Splits on blank-line paragraph boundaries first, falling back to sentence
    boundaries for any single paragraph that is itself larger than a chunk.
    Never splits inside a word.
    """
    char_budget = max(1, chunk_tokens) * _CHARS_PER_TOKEN
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for para in _PARAGRAPH_SPLIT.split(text.strip()):
        para = para.strip()
        if not para:
            continue
        if len(para) > char_budget:
            for sent in _split_sentences(para):
                if current and len(current) + len(sent) + 1 > char_budget:
                    flush()
                current = f"{current} {sent}".strip()
                if len(current) >= char_budget:
                    flush()
        else:
            if current and len(current) + len(para) + 2 > char_budget:
                flush()
            current = f"{current}\n\n{para}".strip()
    flush()
    return chunks or [text[:char_budget]]


def truncate_to_budget(text: str, max_tokens: int, marker: str = " …[troncato]") -> str:
    """Hard-cut ``text`` to the budget on a clean sentence/word boundary."""
    full_budget = max(1, max_tokens) * _CHARS_PER_TOKEN
    if len(text) <= full_budget:
        return text
    # Reserve room for the marker so the returned string (marker included) still
    # fits the token budget.
    char_budget = max(1, full_budget - len(marker))
    cut = text[:char_budget]
    boundary = max(cut.rfind(". "), cut.rfind("\n"))
    if boundary > char_budget * 0.5:
        cut = cut[: boundary + 1]
    else:
        space = cut.rfind(" ")
        if space > 0:
            cut = cut[:space]
    return cut.rstrip() + marker


def extractive_summarize(text: str, max_tokens: int) -> str:
    """Deterministic offline summary: keep the highest-information sentences.

    Scores each sentence by the summed frequency of its content words and keeps
    the top-scoring ones (in original order) until the token budget is reached.
    No model, no network, no extra dependency -- so it also backs the Mock
    provider and any LLM-summariser failure.
    """
    if within_budget(text, max_tokens):
        return text

    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return truncate_to_budget(text, max_tokens)

    freq: Counter[str] = Counter(
        w for w in re.findall(r"[a-zA-Z']+", text.lower())
        if w not in _STOPWORDS and len(w) > 2
    )
    top = max(freq.values()) if freq else 1

    def score(sentence: str) -> float:
        words = [w for w in re.findall(r"[a-zA-Z']+", sentence.lower()) if w not in _STOPWORDS]
        if not words:
            return 0.0
        return sum(freq.get(w, 0) for w in words) / (len(words) * top)

    ranked = sorted(range(len(sentences)), key=lambda i: score(sentences[i]), reverse=True)

    char_budget = max(1, max_tokens) * _CHARS_PER_TOKEN
    kept: set[int] = set()
    used = 0
    for i in ranked:
        cost = len(sentences[i]) + 1
        if used + cost > char_budget:
            continue
        kept.add(i)
        used += cost
        if used >= char_budget * 0.95:
            break

    summary = " ".join(sentences[i] for i in sorted(kept)) if kept else sentences[0]
    return truncate_to_budget(summary, max_tokens)


_SUMMARY_SYSTEM = (
    "You are a precise summariser. Compress the text the user gives you, "
    "preserving concrete facts, numbers, names and source URLs. Output only the "
    "summary as plain prose, no preamble."
)


def _summarize_chunk_with_llm(chunk: str, provider, target_tokens: int) -> str:
    target_words = max(40, int(target_tokens * 0.7))
    user = (
        f"Summarise the following in at most {target_words} words, keeping the "
        f"most important facts:\n\n{chunk}"
    )
    return provider.generate(_SUMMARY_SYSTEM, user).strip()


def _default_summarizer():
    """The cheap/fast provider used for summarisation (lazy import to avoid a
    circular dependency with llm_providers)."""
    from src.llm_providers import get_llm_provider

    return get_llm_provider(task=None)


def compress_to_budget(
    text: str,
    max_tokens: int,
    use_llm: bool | None = None,
    summarizer_provider=None,
) -> str:
    """Return ``text`` shrunk to fit ``max_tokens`` input tokens.

    Fast path: already within budget -> returned untouched. Otherwise summarise:
    abstractively via the LLM (chunk -> summarise each -> combine) when enabled
    and a real provider is available, else with the deterministic extractive
    summariser. A final hard truncate guarantees the result fits even if a
    summary came back longer than asked.
    """
    text = (text or "").strip()
    if not text or within_budget(text, max_tokens):
        return text

    use_llm = settings.summarizer_use_llm if use_llm is None else use_llm
    if use_llm:
        try:
            provider = summarizer_provider or _default_summarizer()
            # The Mock provider returns a templated blog post, not a summary, so
            # never route summarisation through it -- use the extractive path.
            if type(provider).__name__ == "MockProvider":
                raise RuntimeError("mock provider cannot summarise")
            chunks = chunk_by_tokens(text, settings.summarizer_chunk_tokens)
            per_chunk = max(60, max_tokens // max(1, len(chunks)))
            summaries = [_summarize_chunk_with_llm(c, provider, per_chunk) for c in chunks]
            combined = "\n".join(s for s in summaries if s).strip()
            if not within_budget(combined, max_tokens):
                combined = extractive_summarize(combined, max_tokens)
            return combined if within_budget(combined, max_tokens) else truncate_to_budget(combined, max_tokens)
        except Exception:
            # Any summariser failure (network, parse, mock) -> safe offline path.
            pass

    return extractive_summarize(text, max_tokens)
