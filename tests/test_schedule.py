from datetime import datetime, timedelta, timezone

import pytest

from reelkit.schedule import validate_publish_at


def test_validate_publish_at_accepts_future_utc():
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    value = "2026-10-25T13:00:00Z"

    assert validate_publish_at(value, now=now).isoformat() == "2026-10-25T13:00:00+00:00"


@pytest.mark.parametrize("value", ["tomorrow", "2026-10-25 13:00:00", None, 123])
def test_validate_publish_at_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="صيغة موعد الجدولة"):
        validate_publish_at(value, now=datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc))


def test_validate_publish_at_rejects_past_time():
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="موعد الجدولة في الماضي"):
        validate_publish_at("2026-10-25T11:54:00Z", now=now)
