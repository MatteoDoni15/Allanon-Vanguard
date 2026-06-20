"""
Internal writer voice profiles.

Rather than one uniform writing voice for every post (the surest way to
leave a single, recognizable AI fingerprint across 700 posts/month), the
content-generation prompt is parameterized by one of a small set of
internal style profiles. A given keyword is assigned a profile
deterministically (a stable hash, not random) so the SAME profile is
kept across retries -- a human writer's style does not change between
draft attempts, and neither should this.

These profiles are internal prompt parameters only. None of them is, or
is ever turned into, a public byline: see Part 1 (Content Generation)
and Part 3 (proposal 4) of the design document for why public author
attribution is a separate, more sensitive decision that this module
deliberately stays out of.
"""

from __future__ import annotations

import hashlib

VOICE_PROFILES: dict[str, str] = {
    "analytical": (
        "Voice: analytical and precise. Prefer concrete numbers and short, "
        "declarative sentences. Open each section with the direct answer, "
        "then the supporting detail. Minimal use of rhetorical questions."
    ),
    "conversational": (
        "Voice: warm and conversational, as if explaining this to a "
        "friend. Slightly longer sentences are fine, contractions are "
        "fine, but every claim must still be precise and unhedged on facts."
    ),
    "structured": (
        "Voice: highly structured. Favor short paragraphs, frequent "
        "subheadings, and numbered or bulleted steps wherever a process "
        "is being described, over long narrative paragraphs."
    ),
    "narrative": (
        "Voice: narrative and example-led. Open sections with a brief, "
        "concrete scenario before generalizing into advice, rather than "
        "leading with the abstract rule."
    ),
}


def assign_voice_profile(keyword: str) -> str:
    """
    Deterministic assignment: the same keyword always maps to the same
    profile (stable across retries), while different keywords spread
    across the available profiles.
    """
    digest = hashlib.sha256(keyword.strip().lower().encode("utf-8")).hexdigest()
    index = int(digest, 16) % len(VOICE_PROFILES)
    return sorted(VOICE_PROFILES)[index]


def get_voice_directive(profile_id: str) -> str:
    return VOICE_PROFILES.get(profile_id, VOICE_PROFILES["conversational"])
