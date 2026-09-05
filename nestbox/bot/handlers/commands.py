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

HELP = """commands:
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
        lines.append(f"{key} · {record.agent} · {short} · {when}")
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
