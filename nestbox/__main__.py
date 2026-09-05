from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from nestbox.bot.deps import Deps
from nestbox.bot.handlers import build_router
from nestbox.bot.middlewares import OwnerOnlyMiddleware
from nestbox.bot.runner import AgentRunner
from nestbox.config import load_settings
from nestbox.core.engine.claude import ClaudeEngine
from nestbox.core.registry import AgentRegistry
from nestbox.core.sessions import SessionStore
from nestbox.core.usage import UsageClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


COMMANDS = [
    BotCommand(command="topic", description="new branch with its own agent"),
    BotCommand(command="rename", description="rename the branch"),
    BotCommand(command="close", description="close the branch"),
    BotCommand(command="agent", description="switch the branch agent"),
    BotCommand(command="agents", description="list agents"),
    BotCommand(command="new", description="start the session over"),
    BotCommand(command="btw", description="side question on a fork"),
    BotCommand(command="usage", description="remaining limits"),
    BotCommand(command="sessions", description="active branches"),
    BotCommand(command="stop", description="cancel the task"),
]


async def main() -> None:
    settings = load_settings()
    registry = AgentRegistry.from_file(settings.agents_config)
    sessions = SessionStore(settings.sessions_path)
    engine = ClaudeEngine()
    runner = AgentRunner(engine, sessions)
    deps = Deps(
        registry=registry,
        sessions=sessions,
        runner=runner,
        usage=UsageClient(settings.credentials_path),
        warn_threshold=settings.usage_warn_threshold,
        capabilities=engine.capabilities,
    )

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=None),
    )
    dispatcher = Dispatcher()
    dispatcher["deps"] = deps
    dispatcher.message.middleware(OwnerOnlyMiddleware(settings.owner_id))
    dispatcher.include_router(build_router())

    await bot.set_my_commands(COMMANDS)
    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
