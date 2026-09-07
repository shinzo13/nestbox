from __future__ import annotations

import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessageDraft

from nestbox.bot.formatting import escape_md

EDIT_INTERVAL = 3.0
DRAFT_INTERVAL = 1.2
MAX_PROGRESS_LINES = 6
PREVIEW_LIMIT = 3500
CURSOR = "▌"


class LivePreview:
    """Shows what the agent is busy with while the answer is being written.

    Two transports: sendMessageDraft (ephemeral, private chats only) and
    editing an ordinary message. With stream=False it behaves as before:
    a list of called tools, without the answer text.
    """

    def __init__(self, bot: Bot, chat_id: int, thread_id: int | None, *, stream: bool) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._thread_id = thread_id
        self._stream = stream
        self._draft = stream and chat_id > 0
        self._interval = DRAFT_INTERVAL if self._draft else EDIT_INTERVAL
        self._agent = ""
        self._message_id: int | None = None
        self._lines: list[str] = []
        self._text = ""
        self._last_push = 0.0
        self._last_payload = ""

    async def start(self, agent: str) -> None:
        self._agent = agent
        await self._push(self._payload(), force=True)

    def tool(self, label: str) -> None:
        self._lines.append(label)
        del self._lines[:-MAX_PROGRESS_LINES]

    def partial(self, delta: str) -> None:
        if not self._stream:
            return
        self._text += delta

    def block_done(self) -> None:
        """A text block ended, the next one follows."""
        if self._stream and self._text.strip():
            self._text = ""
            self._lines.clear()

    def _payload(self) -> str:
        text = self._text.strip()
        if text:
            return f"{text[-PREVIEW_LIMIT:]} {CURSOR}"
        body = "\n".join(f"· {line}" for line in self._lines)
        return f"⏳ {self._agent} is working…\n{body}".strip()

    async def flush(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_push < self._interval:
            return
        await self._push(self._payload())

    async def _push(self, payload: str, force: bool = False) -> None:
        if not payload or (payload == self._last_payload and not force):
            return
        self._last_push = time.monotonic()
        self._last_payload = payload
        if self._draft:
            await self._push_draft(payload)
        else:
            await self._push_message(payload)

    async def _push_draft(self, payload: str) -> None:
        try:
            await self._bot(
                SendMessageDraft(
                    chat_id=self._chat_id,
                    message_thread_id=self._thread_id,
                    draft_id=1,
                    text=escape_md(payload),
                    parse_mode="MarkdownV2",
                )
            )
        except TelegramBadRequest:
            # the chat has no drafts (a group), fall back to ordinary messages
            self._draft = False
            self._interval = EDIT_INTERVAL
            await self._push_message(payload)

    async def _push_message(self, payload: str) -> None:
        try:
            if self._message_id is None:
                message = await self._bot.send_message(
                    chat_id=self._chat_id,
                    message_thread_id=self._thread_id,
                    text=escape_md(payload),
                    parse_mode="MarkdownV2",
                )
                self._message_id = message.message_id
            else:
                await self._bot.edit_message_text(
                    chat_id=self._chat_id,
                    message_id=self._message_id,
                    text=escape_md(payload),
                    parse_mode="MarkdownV2",
                )
        except TelegramBadRequest:
            pass

    async def close(self, note: str | None = None) -> None:
        """Without a note the preview just disappears: the summary goes to the tail of the answer."""
        if note is not None:
            self._last_payload = ""
            if self._draft:
                self._draft = False
            await self._push_message(note)
            return
        if self._message_id is None:
            return
        message_id, self._message_id = self._message_id, None
        try:
            await self._bot.delete_message(chat_id=self._chat_id, message_id=message_id)
        except TelegramBadRequest:
            pass
