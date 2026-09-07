from __future__ import annotations

import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from nestbox.bot.formatting import escape_md

EDIT_INTERVAL = 3.0
MAX_PROGRESS_LINES = 6


class LivePreview:
    """One message per run: first "working", then the answer itself.

    The placeholder goes out right away, collects the tools as they are called and
    is finally edited into the answer: no extra messages, no deletions.
    """

    def __init__(self, bot: Bot, chat_id: int, thread_id: int | None) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._thread_id = thread_id
        self._agent = ""
        self._message_id: int | None = None
        self._lines: list[str] = []
        self._last_edit = 0.0
        self._last_payload = ""

    async def start(self, agent: str) -> None:
        self._agent = agent
        await self._render(self._payload())

    def tool(self, label: str) -> None:
        self._lines.append(label)
        del self._lines[:-MAX_PROGRESS_LINES]

    def _payload(self) -> str:
        body = "\n".join(f"· {line}" for line in self._lines)
        return escape_md(f"⏳ {self._agent} is working…\n{body}".strip())

    async def flush(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_edit < EDIT_INTERVAL:
            return
        await self._render(self._payload())

    async def finish(self, chunks: list[str]) -> None:
        """The first chunk takes the placeholder's place, the rest follow."""
        if not chunks:
            return
        await self._render(chunks[0], force=True)
        for chunk in chunks[1:]:
            await self._send(chunk)

    async def fail(self, note: str) -> None:
        await self._render(escape_md(note), force=True)

    async def _render(self, payload: str, force: bool = False) -> None:
        if not payload or (payload == self._last_payload and not force):
            return
        self._last_edit = time.monotonic()
        self._last_payload = payload
        if self._message_id is None:
            await self._send(payload)
            return
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=self._message_id,
                text=payload,
            )
        except TelegramBadRequest:
            # the placeholder is gone, but the answer still has to go out
            if force:
                self._message_id = None
                await self._send(payload)

    async def _send(self, payload: str) -> None:
        message = await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=self._thread_id,
            text=payload,
        )
        if self._message_id is None:
            self._message_id = message.message_id
