from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
# the cli rewrites credentials in place (401). 429 is not retried: the endpoint
# allows three or four calls, then refuses for about five minutes, and retries extend it
RETRY_STATUSES = {401, 500, 502, 503, 529}
RETRIES = 4
RETRY_DELAY = 1.5
MAX_WAIT = 8.0


@dataclass(slots=True)
class Window:
    label: str
    percent: float | None
    resets_at: datetime | None


class RateLimited(Exception):
    pass


@dataclass(slots=True)
class UsageSnapshot:
    windows: list[Window]
    extra_credits_used: float | None
    currency: str | None
    fetched_at: datetime | None = None

    @property
    def peak(self) -> float:
        values = [w.percent for w in self.windows if w.percent is not None]
        return max(values) if values else 0.0


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return None


def _retry_after(response: aiohttp.ClientResponse) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class UsageClient:
    def __init__(self, credentials_path: Path) -> None:
        self._credentials_path = credentials_path

    def _token(self) -> str:
        payload = json.loads(self._credentials_path.read_text(encoding="utf-8"))
        return payload["claudeAiOauth"]["accessToken"]

    async def fetch(self) -> UsageSnapshot:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(RETRIES):
                headers = {
                    "Authorization": f"Bearer {self._token()}",
                    "anthropic-beta": OAUTH_BETA,
                }
                async with session.get(USAGE_URL, headers=headers) as response:
                    if response.status == 429:
                        raise RateLimited()
                    last = attempt + 1 >= RETRIES
                    if response.status in RETRY_STATUSES and not last:
                        delay = _retry_after(response) or RETRY_DELAY * 2**attempt
                        if delay > MAX_WAIT:
                            log.warning("usage %s, would wait %.0fs, not waiting", response.status, delay)
                            response.raise_for_status()
                        log.warning(
                            "usage %s, attempt %s of %s, retrying in %.1fs",
                            response.status, attempt + 1, RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    response.raise_for_status()
                    payload = await response.json()
                    break
        snapshot = self._parse(payload)
        snapshot.fetched_at = datetime.now(UTC)
        return snapshot

    @staticmethod
    def _parse(payload: dict) -> UsageSnapshot:
        windows: list[Window] = []
        for key, label in (("five_hour", "5h"), ("seven_day", "week")):
            block = payload.get(key)
            if not isinstance(block, dict):
                continue
            windows.append(
                Window(
                    label=label,
                    percent=block.get("utilization"),
                    resets_at=_parse_ts(block.get("resets_at")),
                )
            )
        for key, label in (("seven_day_opus", "week opus"), ("seven_day_sonnet", "week sonnet")):
            block = payload.get(key)
            if isinstance(block, dict) and block.get("utilization") is not None:
                windows.append(
                    Window(
                        label=label,
                        percent=block.get("utilization"),
                        resets_at=_parse_ts(block.get("resets_at")),
                    )
                )
        extra = payload.get("extra_usage") or {}
        return UsageSnapshot(
            windows=windows,
            extra_credits_used=extra.get("used_credits"),
            currency=extra.get("currency"),
        )
