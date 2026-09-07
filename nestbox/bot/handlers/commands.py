from __future__ import annotations

from datetime import UTC, datetime

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from nestbox.bot.attachments import send_attachments
from nestbox.bot.deps import Deps
from nestbox.bot.formatting import escape_md
from nestbox.core.engine.base import Capability
from nestbox.core.sessions import SessionStore

router = Router(name="commands")

TOPIC_NAME_LIMIT = 128

HELP = """branches are created by the orchestrator: ask it in the main topic.

commands:
/branch - configure this branch: title, icon
/agents - configured agents
/new - start this branch's session over
/wake - keep the agent up between messages
/sleep - put it to sleep, the session is kept
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
    await message.answer(escape_md(HELP))


@router.message(Command("agents"))
async def cmd_agents(message: Message, deps: Deps) -> None:
    lines = []
    for spec in deps.registry.all():
        marker = "*" if spec.name == deps.registry.default.name else " "
        lines.append(f"{marker} {spec.name}: {spec.description or spec.cwd or ''}")
    await message.answer(escape_md("\n".join(lines)))


@router.message(Command("new"))
async def cmd_new(message: Message, deps: Deps) -> None:
    branch = await deps.branches.get(message.message_thread_id)
    if branch is None:
        await deps.redirect_to_main(message)
        return
    key = SessionStore.key(message.chat.id, message.message_thread_id)
    await deps.runner.sleep(key)
    await deps.sessions.drop(key)
    await deps.sessions.set(key, "", branch.agent)
    await message.answer(escape_md(f"new session, agent {branch.agent}"))


@router.message(Command("wake"))
async def cmd_wake(message: Message, deps: Deps) -> None:
    key = SessionStore.key(message.chat.id, message.message_thread_id)
    if Capability.LIVE not in deps.capabilities:
        await message.answer(escape_md("the engine has no live sessions"))
        return
    branch = await deps.branches.get(message.message_thread_id)
    if branch is None:
        await deps.redirect_to_main(message)
        return
    record = await deps.sessions.get(key)
    spec = deps.registry.for_branch(branch)
    if deps.runner.is_awake(key):
        await message.answer(escape_md(f"{spec.name} is already awake"))
        return
    try:
        await deps.runner.wake(spec, key, record.session_id if record else None)
    except Exception as exc:
        await message.answer(escape_md(f"failed to wake: {exc}"))
        return
    await message.answer(
        escape_md(f"🟢 {spec.name} is up, sleeps after 30m idle")
    )


@router.message(Command("sleep"))
async def cmd_sleep(message: Message, deps: Deps) -> None:
    key = SessionStore.key(message.chat.id, message.message_thread_id)
    if await deps.runner.sleep(key):
        await message.answer(escape_md("💤 asleep, session kept"))
    else:
        await message.answer(escape_md("it was not awake"))


@router.message(Command("stop"))
async def cmd_stop(message: Message, deps: Deps) -> None:
    key = SessionStore.key(message.chat.id, message.message_thread_id)
    if deps.runner.cancel(key):
        await message.answer(escape_md("stopping"))
    else:
        await message.answer(escape_md("nothing to stop"))


@router.message(Command("sessions"))
async def cmd_sessions(message: Message, deps: Deps) -> None:
    records = await deps.sessions.all()
    if not records:
        await message.answer(escape_md("no sessions"))
        return
    awake = deps.runner.awake_keys()
    lines = []
    for key, record in sorted(records.items(), key=lambda item: -item[1].updated_at):
        when = datetime.fromtimestamp(record.updated_at, UTC).strftime("%d.%m %H:%M")
        short = record.session_id[-6:] if record.session_id else "new"
        title = record.title or key
        mark = "🟢" if key in awake else "💤"
        lines.append(f"{mark} {title} · {record.agent} · {short} · {when}")
    await message.answer(escape_md("\n".join(lines)))


@router.message(Command("usage"))
async def cmd_usage(message: Message, deps: Deps) -> None:
    try:
        snapshot = await deps.usage_snapshot(force=True)
    except Exception as exc:
        await message.answer(escape_md(f"could not fetch usage: {exc}"))
        return
    lines = []
    for window in snapshot.windows:
        percent = f"{window.percent:.0f}%" if window.percent is not None else "?"
        reset = _fmt_reset(window.resets_at)
        lines.append(f"{window.label}: {percent} {reset}".strip())
    if snapshot.extra_credits_used:
        lines.append(f"extra: {snapshot.extra_credits_used:.2f} {snapshot.currency or ''}".strip())
    await message.answer(escape_md("\n".join(lines)))


@router.message(Command("btw"))
async def cmd_btw(message: Message, command: CommandObject, deps: Deps) -> None:
    question = (command.args or "").strip()
    if not question:
        await message.answer(escape_md("and the question?"))
        return
    key = SessionStore.key(message.chat.id, message.message_thread_id)
    branch = await deps.branches.get(message.message_thread_id)
    record = await deps.sessions.get(key)
    if branch is None:
        await deps.redirect_to_main(message)
        return
    if not record or not record.session_id:
        await message.answer(escape_md("no session in this branch yet, nothing to fork"))
        return
    if Capability.FORK not in deps.capabilities:
        await message.answer(escape_md("the engine cannot fork"))
        return
    spec = deps.registry.for_branch(branch)
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
    if outcome.attachments:
        await send_attachments(message, outcome.attachments)
