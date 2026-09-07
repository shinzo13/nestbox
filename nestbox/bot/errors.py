from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent

from nestbox.bot.formatting import escape_md

log = logging.getLogger(__name__)


def register_error_handler(dispatcher: Dispatcher, bot: Bot) -> None:
    """A crashed handler must not look like the bot going silent."""

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception("handler crashed: %s", event.exception)
        message = getattr(event.update, "message", None)
        if message is None:
            return True
        try:
            await bot.send_message(
                chat_id=message.chat.id,
                message_thread_id=message.message_thread_id,
                text=escape_md(f"⚠️ tripped over this message: {type(event.exception).__name__}: {event.exception}"),
            )
        except Exception as exc:  # noqa: BLE001 - nobody left to report the failure to
            log.warning("could not report the failure: %s", exc)
        return True
