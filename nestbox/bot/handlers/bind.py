from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from nestbox.bot.deps import Deps
from nestbox.bot.formatting import escape_md
from nestbox.core.sessions import SessionStore

router = Router(name="bind")

log = logging.getLogger(__name__)
GROUP_TYPES = {"group", "supergroup"}


@router.message(Command("bind"))
async def cmd_bind(message: Message, deps: Deps) -> None:
    """Moving to a group: recreate the branches there, keep the sessions."""
    if message.chat.type not in GROUP_TYPES:
        await message.answer(escape_md("send this command in the group you are moving to"))
        return

    chat_id = message.chat.id
    if deps.state.get("chat_id") == chat_id:
        await message.answer(escape_md("already here"))
        return

    try:
        member = await message.bot.get_chat_member(chat_id, message.bot.id)
    except Exception as exc:
        await message.answer(escape_md(f"could not check my own rights: {exc}"))
        return
    if getattr(member, "can_manage_topics", False) is not True:
        await message.answer(escape_md("make me an admin with the manage topics right and try again"))
        return

    moved = []
    for branch in await deps.branches.all():
        topic = await message.bot.create_forum_topic(
            chat_id=chat_id,
            name=branch.title[:128],
            icon_custom_emoji_id=branch.icon,
        )
        old_key = SessionStore.key(deps.chat_id, branch.thread_id)
        record = await deps.sessions.get(old_key)
        await deps.branches.remove(branch.thread_id)
        branch.thread_id = topic.message_thread_id
        await deps.branches.add(branch)
        if record:
            await deps.sessions.drop(old_key)
            await deps.sessions.set(
                SessionStore.key(chat_id, branch.thread_id),
                record.session_id,
                record.agent,
                record.title,
            )
        moved.append(f"{branch.title} → {branch.thread_id}")

    deps.state.set("chat_id", chat_id)
    await message.answer(
        escape_md("moved:\n" + "\n".join(moved) + "\n\nrestarting, from now on we work here")
    )
    log.info("moved to chat %s, branches: %s", chat_id, len(moved))
    asyncio.get_running_loop().call_later(1.0, sys.exit, 0)
