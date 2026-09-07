from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendRichMessage
from aiogram.types import (
    InputRichBlockDetails,
    InputRichBlockParagraph,
    InputRichBlockPreformatted,
    InputRichMessage,
)

from nestbox.bot.formatting import TELEGRAM_LIMIT, escape_md

TYPING_INTERVAL = 4.0
LOG_INTERVAL = 3.0
MAX_LOG_LINES = 40

log = logging.getLogger(__name__)


class ReplyStream:
    """How a run looks in the chat.

    The agent's branch shows only "typing..." and the answer itself, one message
    per chunk the agent finished. Tool calls go to the common channel as a
    separate message folded into details, updated as the work goes.
    """

    def __init__(self, bot: Bot, chat_id: int, thread_id: int | None, agent: str) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._thread_id = thread_id
        self._agent = agent
        self._typing: asyncio.Task | None = None
        self._log_id: int | None = None
        self._tools: list[str] = []
        self._last_reply_id: int | None = None
        self._last_reply_text = ""
        self._last_log_edit = 0.0
        self._log_failed = False

    async def start(self) -> None:
        await self._type()
        if self._typing is None:
            self._typing = asyncio.create_task(self._typing_loop())

    async def _type(self) -> None:
        try:
            await self._bot.send_chat_action(
                chat_id=self._chat_id,
                message_thread_id=self._thread_id,
                action="typing",
            )
        except Exception as exc:  # noqa: BLE001 - a status is not worth failing the run
            log.debug("typing: %s", exc)

    async def _typing_loop(self) -> None:
        while True:
            await asyncio.sleep(TYPING_INTERVAL)
            await self._type()

    def tool(self, label: str) -> None:
        self._tools.append(label)
        del self._tools[:-MAX_LOG_LINES]

    def _rich(self) -> InputRichMessage:
        body = "\n".join(f"{n}. {line}" for n, line in enumerate(self._tools, 1))
        blocks: list[object] = [InputRichBlockParagraph(text=f"{self._agent}'s toolcalls")]
        if body:
            blocks.append(
                InputRichBlockDetails(
                    summary=f"{len(self._tools)} calls",
                    is_open=False,
                    blocks=[InputRichBlockPreformatted(text=body[:3500])],
                )
            )
        return InputRichMessage(blocks=blocks)

    async def flush(self, force: bool = False) -> None:
        """The tool call log lives in the common channel, not in the agent's branch."""
        if self._log_failed or not self._tools:
            return
        now = time.monotonic()
        if not force and now - self._last_log_edit < LOG_INTERVAL:
            return
        self._last_log_edit = now
        try:
            if self._log_id is None:
                message = await self._bot(
                    SendRichMessage(chat_id=self._chat_id, rich_message=self._rich())
                )
                self._log_id = message.message_id
            else:
                await self._bot.edit_message_text(
                    chat_id=self._chat_id,
                    message_id=self._log_id,
                    rich_message=self._rich(),
                )
        except TelegramBadRequest as exc:
            if "not modified" in str(exc):
                return
            log.warning("tool call log failed: %s", exc)
            self._log_failed = True

    async def say(self, chunks: list[str]) -> None:
        """Every finished chunk goes out as its own message without waiting for the end."""
        for chunk in chunks:
            if not chunk.strip():
                continue
            message = await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=self._thread_id,
                text=chunk,
            )
            self._last_reply_id = message.message_id
            self._last_reply_text = chunk

    def _log_link(self, label: str) -> str:
        """The tool call counter links to that log in the common channel."""
        if self._log_id is None:
            return escape_md(label)
        internal = str(self._chat_id).removeprefix("-100")
        return f"[{escape_md(label)}](https://t.me/c/{internal}/{self._log_id})"

    async def finish(self, head: str | None, tools: int = 0) -> None:
        await self._stop_typing()
        await self.flush(force=True)
        if not head:
            return
        tail = escape_md(head)
        if tools:
            tail = f"{tail} · {self._log_link(f'{tools} tool calls')}"
        tail = f"_{tail}_"
        if self._last_reply_id is None:
            await self.say([tail])
            return
        payload = f"{self._last_reply_text}\n\n{tail}"
        if len(payload) > TELEGRAM_LIMIT:
            await self.say([tail])
            return
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=self._last_reply_id,
                text=payload,
            )
        except TelegramBadRequest:
            await self.say([tail])

    async def fail(self, note: str) -> None:
        await self._stop_typing()
        await self.say([escape_md(note)])

    async def _stop_typing(self) -> None:
        if self._typing is not None:
            self._typing.cancel()
            self._typing = None
