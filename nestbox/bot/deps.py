from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from aiogram.types import Message

from nestbox.bot.formatting import escape_md
from nestbox.bot.runner import AgentRunner
from nestbox.core.branches import BranchStore
from nestbox.core.engine.base import Capability
from nestbox.core.registry import AgentRegistry
from nestbox.core.sessions import SessionStore
from nestbox.core.usage import UsageClient, UsageSnapshot

USAGE_CACHE_TTL = 120.0
REDIRECT_COOLDOWN = 300.0


@dataclass
class Deps:
    registry: AgentRegistry
    sessions: SessionStore
    branches: BranchStore
    runner: AgentRunner
    usage: UsageClient
    warn_threshold: int
    capabilities: frozenset[Capability]
    icons: list[tuple[str, str]] = field(default_factory=list)
    inbox: Path = field(default_factory=lambda: Path("./data/inbox"))
    maintenance_lock: Path = field(default_factory=lambda: Path("./data/main.lock"))
    _cache: tuple[float, UsageSnapshot] | None = field(default=None, init=False)
    _warned_at: float = field(default=0.0, init=False)
    _redirected_at: float = field(default=0.0, init=False)

    async def redirect_to_main(self, message: Message) -> None:
        """There is no conversation outside branches: each branch is an agent, the general chat belongs to nobody."""
        now = time.monotonic()
        if now - self._redirected_at < REDIRECT_COOLDOWN:
            return
        self._redirected_at = now
        main = await self.branches.main()
        where = f"«{main.title}»" if main else "main"
        await message.answer(f"the general chat belongs to nobody, write in {where}")

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
