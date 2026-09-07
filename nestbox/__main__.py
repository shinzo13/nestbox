from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from nestbox.bot.deps import Deps
from nestbox.bot.errors import register_error_handler
from nestbox.bot.events import EventPump
from nestbox.bot.handlers import build_router
from nestbox.bot.middlewares import (
    BranchOnlyMiddleware,
    MarkdownFallbackMiddleware,
    OwnerOnlyMiddleware,
)
from nestbox.bot.runner import AgentRunner
from nestbox.bot.supervisor import MainSupervisor
from nestbox.config import load_settings
from nestbox.core.delegation import build_orchestrator_tools
from nestbox.core.engine.claude import ClaudeEngine
from nestbox.core.branches import Branch, BranchStore
from nestbox.core.registry import AgentRegistry
from nestbox.core.state import State
from nestbox.core.sessions import SessionStore
from nestbox.core.usage import UsageClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


COMMANDS = [
    BotCommand(command="branch", description="configure this branch"),
    BotCommand(command="agents", description="configured agents"),
    BotCommand(command="new", description="start the session over"),
    BotCommand(command="wake", description="keep the agent awake"),
    BotCommand(command="sleep", description="put the agent to sleep"),
    BotCommand(command="btw", description="side question on a fork"),
    BotCommand(command="usage", description="remaining limits"),
    BotCommand(command="sessions", description="active branches"),
    BotCommand(command="stop", description="cancel the task"),
]


async def ensure_main_branch(
    bot: Bot, branches: BranchStore, chat_id: int | None, agent: str
) -> None:
    """The orchestrator lives in a branch of its own, not in the general chat."""
    if chat_id is None or await branches.main() is not None:
        return
    topic = await bot.create_forum_topic(chat_id=chat_id, name="master")
    await branches.add(
        Branch(
            thread_id=topic.message_thread_id,
            agent="claude-master",
            title="master",
            cwd=str(Path.home()),
            mode="work",
            is_main=True,
        )
    )


async def load_icons(bot: Bot) -> list[tuple[str, str]]:
    try:
        stickers = await bot.get_forum_topic_icon_stickers()
    except Exception:
        return []
    return [
        (sticker.emoji, sticker.custom_emoji_id)
        for sticker in stickers
        if sticker.emoji and sticker.custom_emoji_id
    ]


async def main() -> None:
    settings = load_settings()
    registry = AgentRegistry.from_file(settings.agents_config)
    sessions = SessionStore(settings.sessions_path)
    branches = BranchStore(settings.branches_path)
    state = State(settings.state_path)
    chat_id = state.get("chat_id") or settings.chat_id or settings.owner_id
    engine = ClaudeEngine()
    runner = AgentRunner(engine, sessions)
    deps = Deps(
        registry=registry,
        sessions=sessions,
        branches=branches,
        state=state,
        chat_id=chat_id,
        runner=runner,
        usage=UsageClient(settings.credentials_path),
        warn_threshold=settings.usage_warn_threshold,
        capabilities=engine.capabilities,
        inbox=settings.data_dir / "inbox",
        maintenance_lock=settings.maintenance_lock,
    )

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(
            parse_mode="MarkdownV2",
            link_preview_is_disabled=True,
        ),
    )
    bot.session.middleware(MarkdownFallbackMiddleware())
    registry.set_orchestrator_tools(build_orchestrator_tools(lambda: deps, lambda: bot))
    dispatcher = Dispatcher()
    dispatcher["deps"] = deps
    dispatcher.message.middleware(OwnerOnlyMiddleware(settings.owner_id))
    dispatcher.callback_query.middleware(OwnerOnlyMiddleware(settings.owner_id))
    dispatcher.message.middleware(BranchOnlyMiddleware())
    dispatcher.include_router(build_router())
    register_error_handler(dispatcher, bot)

    runner.start_janitor()
    deps.icons = await load_icons(bot)
    await ensure_main_branch(bot, branches, chat_id, registry.default.name)
    supervisor = MainSupervisor(deps, chat_id, settings.maintenance_lock)
    supervisor.start()
    EventPump(deps, bot, settings.data_dir / "events").start()
    await bot.set_my_commands(COMMANDS)
    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
