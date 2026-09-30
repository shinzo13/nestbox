from nestbox.core.usage import UsageClient

PAYLOAD = {
    "five_hour": {"utilization": 18.0, "resets_at": "2026-09-05T23:20:00+00:00"},
    "seven_day": {"utilization": 6.0, "resets_at": "2026-09-11T08:00:00+00:00"},
    "seven_day_opus": None,
    "extra_usage": {"used_credits": 1.5, "currency": "EUR"},
}


def test_parses_windows():
    snapshot = UsageClient._parse(PAYLOAD)
    assert [w.label for w in snapshot.windows] == ["5h", "week"]
    assert snapshot.peak == 18.0
    assert snapshot.extra_credits_used == 1.5


def test_ignores_null_blocks():
    snapshot = UsageClient._parse({"five_hour": None, "seven_day": None})
    assert snapshot.windows == []
    assert snapshot.peak == 0.0


def test_bad_timestamp_is_none():
    snapshot = UsageClient._parse({"five_hour": {"utilization": 1.0, "resets_at": "nope"}})
    assert snapshot.windows[0].resets_at is None


async def test_rate_limit_serves_the_last_good_snapshot():
    import time

    import pytest

    from nestbox.bot.deps import Deps
    from nestbox.core.usage import RateLimited, UsageSnapshot

    class Client:
        def __init__(self):
            self.calls = 0
            self.limited = False

        async def fetch(self):
            self.calls += 1
            if self.limited:
                raise RateLimited()
            return UsageSnapshot(windows=[], extra_credits_used=None, currency=None)

    client = Client()
    deps = Deps(None, None, None, None, 1, None, client, 80, frozenset())
    first = await deps.usage_snapshot()
    deps._cache = (time.monotonic() - 3600, first)
    client.limited = True
    assert await deps.usage_snapshot(force=True) is first
    calls = client.calls
    assert await deps.usage_snapshot(force=True) is first
    assert client.calls == calls

    deps._cache = None
    with pytest.raises(RateLimited):
        await deps.usage_snapshot(force=True)
