from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from nestbox.bot.attachments import save_incoming, send_attachments
from nestbox.bot.formatting import escape_md
from nestbox.bot.deps import Deps
from nestbox.bot.handlers.branch import consume_pending
from nestbox.core.sessions import SessionStore

router = Router(name="chat")


@router.message()
async def handle_message(message: Message, deps: Deps) -> None:
    text = (message.text or message.caption or "").strip()
    files = await save_incoming(message, deps.inbox)
    if not text and not files:
        return
    if files:
        listing = "\n".join(f"- {path}" for path in files)
        text = f"{text}\n\nattached files:\n{listing}".strip()

    chat_id = message.chat.id
    thread_id = message.message_thread_id

    branch = await deps.branches.get(thread_id)
    if branch is None:
        await deps.redirect_to_main(message)
        return

    if await consume_pending(message, deps, branch):
        return

    if branch.is_main and deps.maintenance_lock.exists():
        await message.answer(escape_md(f"{branch.title} is in a manual terminal session right now, wait a bit"))
        return

    key = SessionStore.key(chat_id, thread_id)
    if deps.runner.is_busy(key):
        await message.reply(escape_md("busy with the current task, /stop to cancel"))
        return

    record = await deps.sessions.get(key)
    spec = deps.registry.for_branch(branch)

    outcome = await deps.runner.run(
        bot=message.bot,
        chat_id=chat_id,
        thread_id=thread_id,
        spec=spec,
        prompt=text,
        resume_session=record.session_id if record else None,
    )

    if outcome.attachments:
        await send_attachments(message, outcome.attachments)

    await deps.maybe_warn_usage(message)
