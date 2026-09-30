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
from nestbox.core.state import State
from nestbox.core.usage import RateLimited, UsageClient, UsageSnapshot

# the usage endpoint shares its budget with the cli and goes quiet for ~5 minutes after 3-4 calls
USAGE_CACHE_TTL = 600.0
USAGE_FORCE_TTL = 60.0
USAGE_BACKOFF = 300.0
REDIRECT_COOLDOWN = 300.0


@dataclass
class Deps:
    registry: AgentRegistry
    sessions: SessionStore
    branches: BranchStore
    state: State
    chat_id: int
    runner: AgentRunner
    usage: UsageClient
    warn_threshold: int
    capabilities: frozenset[Capability]
    icons: list[tuple[str, str]] = field(default_factory=list)
    inbox: Path = field(default_factory=lambda: Path("./data/inbox"))
    maintenance_lock: Path = field(default_factory=lambda: Path("./data/main.lock"))
    _cache: tuple[float, UsageSnapshot] | None = field(default=None, init=False)
    _warned_at: float = field(default=0.0, init=False)
    _usage_blocked_until: float = field(default=0.0, init=False)
    _redirected_at: float = field(default=0.0, init=False)

    async def redirect_to_main(self, message: Message) -> None:
        """There is no conversation outside branches: each branch is an agent, the general chat belongs to nobody."""
        now = time.monotonic()
        if now - self._redirected_at < REDIRECT_COOLDOWN:
            return
        self._redirected_at = now
        main = await self.branches.main()
        where = f"«{main.title}»" if main else "master"
        await message.answer(escape_md(f"the general chat belongs to nobody, write in {where}"))

    async def usage_snapshot(self, force: bool = False) -> UsageSnapshot:
        """A fresh snapshot, or the last good one while the api is rate limited.

        A stale snapshot shows itself through fetched_at, so the caller decides
        how to say the numbers are not current.
        """
        now = time.monotonic()
        ttl = USAGE_FORCE_TTL if force else USAGE_CACHE_TTL
        if self._cache and now - self._cache[0] < ttl:
            return self._cache[1]
        if now < self._usage_blocked_until:
            if self._cache:
                return self._cache[1]
            raise RateLimited()
        try:
            snapshot = await self.usage.fetch()
        except RateLimited:
            self._usage_blocked_until = now + USAGE_BACKOFF
            if self._cache:
                return self._cache[1]
            raise
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
        )
