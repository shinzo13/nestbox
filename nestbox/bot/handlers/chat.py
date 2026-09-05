from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from nestbox.bot.deps import Deps
from nestbox.bot.runner import render_reply
from nestbox.core.sessions import SessionStore

router = Router(name="chat")


@router.message()
async def handle_message(message: Message, deps: Deps) -> None:
    text = (message.text or message.caption or "").strip()
    if not text:
        return

    chat_id = message.chat.id
    thread_id = message.message_thread_id
    key = SessionStore.key(chat_id, thread_id)

    if deps.runner.is_busy(key):
        await message.reply("busy with the current task, /stop to cancel")
        return

    record = await deps.sessions.get(key)
    spec = deps.registry.get(record.agent if record else None)

    outcome = await deps.runner.run(
        bot=message.bot,
        chat_id=chat_id,
        thread_id=thread_id,
        spec=spec,
        prompt=text,
        resume_session=record.session_id if record else None,
    )

    for chunk in render_reply(outcome):
        await message.answer(chunk, parse_mode="MarkdownV2")

    await deps.maybe_warn_usage(message)
