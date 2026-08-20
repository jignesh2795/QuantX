from datetime import datetime, timezone

import pytest

from quantx.research.event_replay import EventReplayCatalog, EventReplayKind, ReplayEvent


def ts(hour: int) -> datetime:
    return datetime(2025, 1, 1, hour, 0, tzinfo=timezone.utc)


def test_event_catalog_never_looks_ahead() -> None:
    events = [
        ReplayEvent("e1", ts(1), EventReplayKind.CORPORATE_ACTION, "ABC"),
        ReplayEvent("e2", ts(3), EventReplayKind.CONTRACT_ROLL, "ABC"),
    ]
    catalog = EventReplayCatalog(events)
    assert tuple(event.event_id for event in catalog.as_of(ts(2), "ABC")) == ("e1",)


def test_event_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ReplayEvent("e1", datetime(2025, 1, 1), EventReplayKind.CORPORATE_ACTION, "ABC")


def test_event_lookup_filters_instrument() -> None:
    events = [
        ReplayEvent("e1", ts(1), EventReplayKind.CORPORATE_ACTION, "ABC"),
        ReplayEvent("e2", ts(1), EventReplayKind.CORPORATE_ACTION, "XYZ"),
    ]
    catalog = EventReplayCatalog(events)
    assert tuple(event.event_id for event in catalog.as_of(ts(2), "ABC")) == ("e1",)
