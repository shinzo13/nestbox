from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiohttp

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"


@dataclass(slots=True)
class Window:
    label: str
    percent: float | None
    resets_at: datetime | None


@dataclass(slots=True)
class UsageSnapshot:
    windows: list[Window]
    extra_credits_used: float | None
    currency: str | None

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


class UsageClient:
    def __init__(self, credentials_path: Path) -> None:
        self._credentials_path = credentials_path

    def _token(self) -> str:
        payload = json.loads(self._credentials_path.read_text(encoding="utf-8"))
        return payload["claudeAiOauth"]["accessToken"]

    async def fetch(self) -> UsageSnapshot:
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "anthropic-beta": OAUTH_BETA,
        }
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(USAGE_URL, headers=headers) as response:
                response.raise_for_status()
                payload = await response.json()
        return self._parse(payload)

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
