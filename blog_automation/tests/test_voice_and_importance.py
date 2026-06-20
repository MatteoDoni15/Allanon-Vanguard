from src.voice_profiles import assign_voice_profile, get_voice_directive, VOICE_PROFILES
from src.importance_tagger import tag_importance_from_keyword, rescan_importance_in_text


def test_voice_profile_assignment_is_deterministic():
    assert assign_voice_profile("how to start investing") == assign_voice_profile("how to start investing")


def test_voice_profile_assignment_varies_across_keywords():
    profiles = {assign_voice_profile(k) for k in [
        "how to start investing", "best budgeting apps", "credit score tips",
        "emergency fund basics", "retirement planning 101",
    ]}
    # Not asserting every profile is hit, just that we are not collapsing
    # every keyword onto a single voice.
    assert len(profiles) > 1


def test_get_voice_directive_returns_known_text_for_every_profile():
    for profile_id in VOICE_PROFILES:
        directive = get_voice_directive(profile_id)
        assert directive and "Voice:" in directive


def test_tag_importance_flags_high_risk_keywords():
    assert tag_importance_from_keyword("tax deadline for freelancers") == "high"
    assert tag_importance_from_keyword("our APR vs a competitor") == "high"


def test_tag_importance_default_is_standard():
    assert tag_importance_from_keyword("best budgeting apps for beginners") == "standard"


def test_rescan_importance_upgrades_on_sensitive_text():
    upgraded = rescan_importance_in_text("this mentions a recent data breach", "standard")
    assert upgraded == "high"


def test_rescan_importance_never_downgrades():
    assert rescan_importance_in_text("totally harmless text", "high") == "high"
