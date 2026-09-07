from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, TelegramObject

from nestbox.bot.formatting import strip_md_escapes

log = logging.getLogger(__name__)


class OwnerOnlyMiddleware(BaseMiddleware):
    def __init__(self, owner_id: int) -> None:
        self._owner_id = owner_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id != self._owner_id:
            if isinstance(event, Message):
                return None
            return None
        return await handler(event, data)


class BranchOnlyMiddleware(BaseMiddleware):
    """Conversations live only in branches: in the general chat the bot points to main."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        deps = data.get("deps")
        text = (getattr(event, "text", None) or "") if isinstance(event, Message) else ""
        if text.startswith("/bind"):
            return await handler(event, data)
        if isinstance(event, Message) and deps is not None and event.message_thread_id is None:
            await deps.redirect_to_main(event)
            return None
        return await handler(event, data)


class MarkdownFallbackMiddleware(BaseRequestMiddleware):
    """If Telegram rejects the markup, the same text goes out without it."""

    async def __call__(self, make_request, bot, method):
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as exc:
            text = getattr(method, "text", None)
            if text is None or "can't parse entities" not in str(exc).lower():
                raise
            log.warning("markup rejected: %s", exc)
            plain = method.model_copy(
                update={"text": strip_md_escapes(text), "parse_mode": None}
            )
            return await make_request(bot, plain)
