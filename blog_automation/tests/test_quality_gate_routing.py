from datetime import datetime, timezone

from src.quality_gate import route_after_quality_gate
from src.publisher import _next_publish_slot
from config import settings


def _state(passed, retries=0, importance="standard"):
    return {
        "quality": {"passed": passed, "reasons": [] if passed else ["x"]},
        "retries": retries,
        "importance_tier": importance,
    }


def test_routes_to_publish_when_quality_passes_and_importance_standard():
    assert route_after_quality_gate(_state(True, importance="standard")) == "publish"


def test_routes_to_needs_review_when_quality_passes_but_importance_high():
    assert route_after_quality_gate(_state(True, importance="high")) == "needs_review"


def test_routes_to_retry_when_quality_fails_and_retries_remain():
    assert route_after_quality_gate(_state(False, retries=0)) == "retry"


def test_routes_to_needs_review_when_retries_exhausted():
    assert route_after_quality_gate(_state(False, retries=settings.max_generation_retries)) == "needs_review"


def test_next_publish_slot_is_in_the_future_and_in_window():
    now = datetime(2026, 6, 17, 14, 0, tzinfo=timezone.utc)  # a Wednesday
    slot = _next_publish_slot(now)
    assert slot > now
    assert slot.weekday() in settings.publish_window_weekdays
    assert slot.hour == settings.publish_window_hour
