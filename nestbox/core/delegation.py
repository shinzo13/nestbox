"""Orchestrator handles: it hands tasks to subagents straight from the conversation.

The tools live in the bot's own process, so they reach the branch registry and
the runner directly, with no network or tokens involved.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from aiogram import Bot
from claude_agent_sdk import create_sdk_mcp_server, tool

from nestbox.bot.formatting import escape_md
from nestbox.core.branches import MODES, Branch
from nestbox.core.sessions import SessionStore

DELEGATE_TIMEOUT = 900.0

log = logging.getLogger(__name__)


def _text(payload: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": payload}]}


def build_orchestrator_tools(deps_factory: Callable[[], Any], bot_factory: Callable[[], Bot]):
    """Build the orchestrator's MCP server. deps and bot are resolved lazily: they exist only later."""

    async def _find(agent: str) -> Branch | None:
        deps = deps_factory()
        wanted = agent.strip().lower()
        for branch in await deps.branches.all():
            if wanted in (branch.agent.lower(), branch.title.lower()):
                return branch
        try:
            resolved = deps.registry.get(agent).name.lower()
        except KeyError:
            return None
        for branch in await deps.branches.all():
            if branch.agent.lower() == resolved:
                return branch
        return None

    @tool("agents", "branch agents and their state: asleep, busy, whether a session exists", {})
    async def agents(_: dict[str, Any]) -> dict[str, Any]:
        deps = deps_factory()
        lines = []
        for branch in await deps.branches.all():
            key = SessionStore.key(deps.chat_id, branch.thread_id)
            record = await deps.sessions.get(key)
            state = "busy" if deps.runner.is_busy(key) else (
                "awake" if deps.runner.is_awake(key) else "asleep"
            )
            session = "has session" if record and record.session_id else "no session"
            mark = "★ " if branch.is_main else ""
            lines.append(
                f"{mark}{branch.agent} · topic {branch.title} ({branch.thread_id}) · "
                f"{branch.mode} · {state} · {session} · {branch.cwd or '-'}"
            )
        return _text("\n".join(lines) or "no branches")

    @tool(
        "delegate",
        "give a subagent a task in its branch and wait for the report. "
        "the owner sees the exchange in the branch topic",
        {"agent": str, "task": str, "fresh": bool},
    )
    async def delegate(args: dict[str, Any]) -> dict[str, Any]:
        deps = deps_factory()
        bot = bot_factory()
        agent = str(args.get("agent") or "").strip()
        task = str(args.get("task") or "").strip()
        if not agent or not task:
            return _text("agent and task are required")
        branch = await _find(agent)
        if branch is None:
            return _text(f"no branch for '{agent}', create one with new_branch")
        if branch.is_main:
            return _text("that is my own branch, nothing to delegate to myself")

        key = SessionStore.key(deps.chat_id, branch.thread_id)
        if deps.runner.is_busy(key):
            return _text(f"{branch.agent} is busy, try later")

        record = await deps.sessions.get(key)
        spec = deps.registry.for_branch(branch)
        fresh = bool(args.get("fresh"))
        await bot.send_message(
            chat_id=deps.chat_id,
            message_thread_id=branch.thread_id,
            text=escape_md(f"📨 task from the orchestrator:\n{task}"),
        )
        try:
            outcome = await asyncio.wait_for(
                deps.runner.run(
                    bot=bot,
                    chat_id=deps.chat_id,
                    thread_id=branch.thread_id,
                    spec=spec,
                    prompt=task,
                    resume_session=None if fresh else (record.session_id if record else None),
                ),
                timeout=DELEGATE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            deps.runner.cancel(key)
            return _text(f"{branch.agent} did not finish in {DELEGATE_TIMEOUT / 60:.0f} minutes, cancelled")
        except Exception as exc:  # noqa: BLE001 - a report beats a crashed tool
            log.warning("delegate %s: %s", branch.agent, exc)
            return _text(f"{branch.agent} crashed: {type(exc).__name__}: {exc}")

        if outcome.error:
            return _text(f"{branch.agent} returned an error: {outcome.error}")
        return _text(f"{branch.agent} reported:\n{outcome.text or '(empty)'}")

    @tool(
        "new_branch",
        "create a branch: a forum topic in the group and an agent behind it",
        {"agent": str, "title": str, "cwd": str, "mode": str},
    )
    async def new_branch(args: dict[str, Any]) -> dict[str, Any]:
        deps = deps_factory()
        bot = bot_factory()
        agent = str(args.get("agent") or "").strip()
        if not agent:
            return _text("agent name is required")
        title = str(args.get("title") or "").strip() or agent.removeprefix("claude-")
        mode = str(args.get("mode") or "ask").strip()
        if mode not in MODES:
            return _text(f"mode must be one of {MODES}")
        cwd = str(args.get("cwd") or "").strip() or None
        if cwd is None:
            try:
                cwd = deps.registry.get(agent).cwd
            except KeyError:
                cwd = None
        if await _find(agent) is not None:
            return _text(f"a branch for {agent} already exists")

        topic = await bot.create_forum_topic(chat_id=deps.chat_id, name=title[:128])
        branch = await deps.branches.add(
            Branch(
                thread_id=topic.message_thread_id,
                agent=agent,
                title=title,
                cwd=cwd,
                mode=mode,
            )
        )
        return _text(
            f"branch {branch.title} ({branch.thread_id}) created: {branch.agent} · "
            f"{branch.mode} · {branch.cwd or '-'}"
        )

    @tool("drop_branch", "drop a branch together with its topic", {"agent": str})
    async def drop_branch(args: dict[str, Any]) -> dict[str, Any]:
        deps = deps_factory()
        bot = bot_factory()
        branch = await _find(str(args.get("agent") or ""))
        if branch is None:
            return _text("no such branch")
        if branch.is_main:
            return _text("refusing to drop my own branch")
        await bot.delete_forum_topic(chat_id=deps.chat_id, message_thread_id=branch.thread_id)
        await deps.branches.remove(branch.thread_id)
        await deps.sessions.drop(SessionStore.key(deps.chat_id, branch.thread_id))
        return _text(f"branch {branch.title} dropped")

    return create_sdk_mcp_server(
        name="nestbox",
        tools=[agents, delegate, new_branch, drop_branch],
    )
