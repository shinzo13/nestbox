from __future__ import annotations

from datetime import UTC, datetime

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from nestbox.bot.deps import Deps
from nestbox.bot.formatting import escape_md
from nestbox.bot.runner import render_reply
from nestbox.core.engine.base import Capability
from nestbox.core.sessions import SessionStore

router = Router(name="commands")

TOPIC_NAME_LIMIT = 128

HELP = """commands:
/topic <agent> [title] - a new topic branch with its own agent
/rename <title> - rename the current branch
/close - close the branch together with its topic
/agent <name> - switch the agent in this branch
/agents - list agents
/new - start the session over
/btw <question> - side question on a fork, the branch stays untouched
/usage - remaining limits
/sessions - active branches
/stop - cancel the running task
"""


def _fmt_reset(value: datetime | None) -> str:
    if value is None:
        return ""
    delta = value - datetime.now(UTC)
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return f"in {minutes}m"
    return f"in {minutes // 60}h{minutes % 60:02d}m"


@router.message(Command("help", "start"))
async def cmd_help(message: Message) -> None:
    await message.answer(escape_md(HELP), parse_mode="MarkdownV2")


@router.message(Command("agents"))
async def cmd_agents(message: Message, deps: Deps) -> None:
    lines = []
    for spec in deps.registry.all():
        marker = "*" if spec.name == deps.registry.default.name else " "
        lines.append(f"{marker} {spec.name}: {spec.description or spec.cwd or ''}")
    await message.answer(escape_md("\n".join(lines)), parse_mode="MarkdownV2")


@router.message(Command("agent"))
async def cmd_agent(message: Message, command: CommandObject, deps: Deps) -> None:
    name = (command.args or "").strip()
    if not name:
        await message.answer("give a name: /agent web")
        return
    try:
        spec = deps.registry.get(name)
    except KeyError:
        await message.answer(f"no such agent: {name}")
        return
    key = SessionStore.key(message.chat.id, message.message_thread_id)
    await deps.sessions.drop(key)
    await deps.sessions.set(key, "", spec.name)
    await message.answer(escape_md(f"branch switched to {spec.name}, new session"), parse_mode="MarkdownV2")


@router.message(Command("new"))
async def cmd_new(message: Message, deps: Deps) -> None:
    key = SessionStore.key(message.chat.id, message.message_thread_id)
    record = await deps.sessions.get(key)
    agent = record.agent if record else deps.registry.default.name
    await deps.sessions.drop(key)
    await deps.sessions.set(key, "", agent)
    await message.answer(escape_md(f"new session, agent {agent}"), parse_mode="MarkdownV2")


@router.message(Command("topic"))
async def cmd_topic(message: Message, command: CommandObject, deps: Deps) -> None:
    parts = (command.args or "").split(maxsplit=1)
    name = parts[0] if parts else ""
    try:
        spec = deps.registry.get(name or None)
    except KeyError:
        await message.answer(f"no such agent: {name}")
        return
    title = parts[1].strip() if len(parts) > 1 else spec.name
    topic = await message.bot.create_forum_topic(chat_id=message.chat.id, name=title[:TOPIC_NAME_LIMIT])
    key = SessionStore.key(message.chat.id, topic.message_thread_id)
    await deps.sessions.set(key, "", spec.name, title=title)
    await message.bot.send_message(
        chat_id=message.chat.id,
        message_thread_id=topic.message_thread_id,
        text=escape_md(f"agent {spec.name} · {spec.cwd or '~'}"),
        parse_mode="MarkdownV2",
    )


@router.message(Command("rename"))
async def cmd_rename(message: Message, command: CommandObject, deps: Deps) -> None:
    title = (command.args or "").strip()
    if not title:
        await message.answer("give a title: /rename web deploy")
        return
    if message.message_thread_id is None:
        await message.answer("this is the general branch, nothing to rename")
        return
    await message.bot.edit_forum_topic(
        chat_id=message.chat.id,
        message_thread_id=message.message_thread_id,
        name=title[:TOPIC_NAME_LIMIT],
    )
    key = SessionStore.key(message.chat.id, message.message_thread_id)
    record = await deps.sessions.get(key)
    if record:
        await deps.sessions.set(key, record.session_id, record.agent, title=title)


@router.message(Command("close"))
async def cmd_close(message: Message, deps: Deps) -> None:
    thread_id = message.message_thread_id
    if thread_id is None:
        await message.answer("the general branch cannot be closed")
        return
    key = SessionStore.key(message.chat.id, thread_id)
    deps.runner.cancel(key)
    await deps.sessions.drop(key)
    await message.bot.delete_forum_topic(chat_id=message.chat.id, message_thread_id=thread_id)


@router.message(Command("stop"))
async def cmd_stop(message: Message, deps: Deps) -> None:
    key = SessionStore.key(message.chat.id, message.message_thread_id)
    if deps.runner.cancel(key):
        await message.answer("stopping")
    else:
        await message.answer("nothing to stop")


@router.message(Command("sessions"))
async def cmd_sessions(message: Message, deps: Deps) -> None:
    records = await deps.sessions.all()
    if not records:
        await message.answer("no sessions")
        return
    lines = []
    for key, record in sorted(records.items(), key=lambda item: -item[1].updated_at):
        when = datetime.fromtimestamp(record.updated_at, UTC).strftime("%d.%m %H:%M")
        short = record.session_id[-6:] if record.session_id else "new"
        title = record.title or key
        lines.append(f"{title} · {record.agent} · {short} · {when}")
    await message.answer(escape_md("\n".join(lines)), parse_mode="MarkdownV2")


@router.message(Command("usage"))
async def cmd_usage(message: Message, deps: Deps) -> None:
    try:
        snapshot = await deps.usage_snapshot(force=True)
    except Exception as exc:
        await message.answer(escape_md(f"could not fetch usage: {exc}"), parse_mode="MarkdownV2")
        return
    lines = []
    for window in snapshot.windows:
        percent = f"{window.percent:.0f}%" if window.percent is not None else "?"
        reset = _fmt_reset(window.resets_at)
        lines.append(f"{window.label}: {percent} {reset}".strip())
    if snapshot.extra_credits_used:
        lines.append(f"extra: {snapshot.extra_credits_used:.2f} {snapshot.currency or ''}".strip())
    await message.answer(escape_md("\n".join(lines)), parse_mode="MarkdownV2")


@router.message(Command("btw"))
async def cmd_btw(message: Message, command: CommandObject, deps: Deps) -> None:
    question = (command.args or "").strip()
    if not question:
        await message.answer("and the question?")
        return
    key = SessionStore.key(message.chat.id, message.message_thread_id)
    record = await deps.sessions.get(key)
    if not record or not record.session_id:
        await message.answer("no session in this branch yet, nothing to fork")
        return
    if Capability.FORK not in deps.capabilities:
        await message.answer("the engine cannot fork")
        return
    spec = deps.registry.get(record.agent)
    outcome = await deps.runner.run(
        bot=message.bot,
        chat_id=message.chat.id,
        thread_id=message.message_thread_id,
        spec=spec,
        prompt=question,
        resume_session=record.session_id,
        fork=True,
        persist=False,
    )
    for chunk in render_reply(outcome):
        await message.answer(chunk, parse_mode="MarkdownV2")
