from __future__ import annotations

import time
from dataclasses import dataclass, field

from aiogram.types import Message

from nestbox.bot.formatting import escape_md
from nestbox.bot.runner import AgentRunner
from nestbox.core.engine.base import Capability
from nestbox.core.registry import AgentRegistry
from nestbox.core.sessions import SessionStore
from nestbox.core.usage import UsageClient, UsageSnapshot

USAGE_CACHE_TTL = 120.0


@dataclass
class Deps:
    registry: AgentRegistry
    sessions: SessionStore
    runner: AgentRunner
    usage: UsageClient
    warn_threshold: int
    capabilities: frozenset[Capability]
    _cache: tuple[float, UsageSnapshot] | None = field(default=None, init=False)
    _warned_at: float = field(default=0.0, init=False)

    async def usage_snapshot(self, force: bool = False) -> UsageSnapshot:
        now = time.monotonic()
        if not force and self._cache and now - self._cache[0] < USAGE_CACHE_TTL:
            return self._cache[1]
        snapshot = await self.usage.fetch()
        self._cache = (now, snapshot)
        return snapshot

    async def maybe_warn_usage(self, message: Message) -> None:
        try:
            snapshot = await self.usage_snapshot()
        except Exception:
            return
        now = time.monotonic()
        if snapshot.peak < self.warn_threshold or now - self._warned_at < 900:
            return
        self._warned_at = now
        await message.answer(
            escape_md(f"⚠️ limit at {snapshot.peak:.0f}%"),
            parse_mode="MarkdownV2",
        )
