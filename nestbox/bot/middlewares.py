from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


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
