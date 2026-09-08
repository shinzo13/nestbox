from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot

from nestbox.bot.deps import Deps
from nestbox.core.sessions import SessionStore

POLL_INTERVAL = 10.0
QUIET_MARK = "#quiet"

log = logging.getLogger(__name__)


class EventPump:
    """Outside events (cron, watchers) wake the orchestrator with a task.

    A file in data/events becomes an ordinary run in the orchestrator's branch,
    so the owner sees its handling and the answer where everything else is.
    """

    def __init__(self, deps: Deps, bot: Bot, folder: Path) -> None:
        self._deps = deps
        self._bot = bot
        self._folder = folder
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                log.warning("event pump: %s", exc)
            await asyncio.sleep(POLL_INTERVAL)

    async def tick(self) -> None:
        events = sorted(self._folder.glob("*.txt"))
        if not events:
            return
        branch = await self._deps.branches.main()
        if branch is None:
            return
        key = SessionStore.key(self._deps.chat_id, branch.thread_id)
        if self._deps.runner.is_busy(key) or self._deps.maintenance_lock.exists():
            return

        path = events[0]
        prompt = path.read_text(encoding="utf-8").strip()
        path.unlink(missing_ok=True)
        # #quiet on the first line: the conversation bypasses the chat, the owner hears only about failures
        quiet = prompt.startswith(QUIET_MARK)
        if quiet:
            prompt = prompt[len(QUIET_MARK):].strip()
        if not prompt:
            return
        record = await self._deps.sessions.get(key)
        spec = self._deps.registry.for_branch(branch)
        log.info("event for the orchestrator: %s", prompt[:80])
        await self._deps.runner.run(
            bot=self._bot,
            chat_id=self._deps.chat_id,
            thread_id=branch.thread_id,
            spec=spec,
            prompt=prompt,
            resume_session=record.session_id if record else None,
            quiet=quiet,
        )
