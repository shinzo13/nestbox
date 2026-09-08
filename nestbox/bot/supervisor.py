from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from nestbox.bot.deps import Deps
from nestbox.core.sessions import SessionStore

CHECK_INTERVAL = 5.0

log = logging.getLogger(__name__)


class MainSupervisor:
    """The orchestrator is always up: it sleeps only while a manual terminal session runs."""

    def __init__(self, deps: Deps, chat_id: int, lock: Path, reset: Path) -> None:
        self._deps = deps
        self._chat_id = chat_id
        self._lock = lock
        self._reset = reset
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                log.warning("main supervisor: %s", exc)
            await asyncio.sleep(CHECK_INTERVAL)

    async def tick(self) -> None:
        branch = await self._deps.branches.main()
        if branch is None:
            return
        key = SessionStore.key(self._chat_id, branch.thread_id)
        awake = self._deps.runner.is_awake(key)

        released = self._lock.with_suffix(".released")
        if self._lock.exists():
            if awake and not self._deps.runner.is_busy(key):
                await self._deps.runner.sleep(key)
                log.info("main handed to a manual session")
            if not self._deps.runner.is_busy(key):
                released.touch()
            return

        released.unlink(missing_ok=True)
        if self._reset.exists():
            if self._deps.runner.is_busy(key):
                return
            await self._deps.runner.sleep(key)
            await self._deps.sessions.drop(key)
            self._reset.unlink(missing_ok=True)
            awake = False
            log.info("main asked for a restart, session dropped")
        if awake:
            return
        record = await self._deps.sessions.get(key)
        spec = self._deps.registry.for_branch(branch)
        resume = record.session_id if record else None
        try:
            await self._deps.runner.wake(spec, key, resume, pinned=True)
        except Exception as exc:
            if not resume:
                raise
            # a broken or busy session must not leave the orchestrator down
            log.warning("resume %s failed (%s), starting a clean session", resume, exc)
            await self._deps.runner.wake(spec, key, None, pinned=True)
            resume = None
        log.info("main is up, session %s", resume or "new")
