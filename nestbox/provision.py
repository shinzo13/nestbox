"""Branch provisioning. An orchestrator handle, not visible to the user."""

from __future__ import annotations

import argparse
import asyncio

from aiogram import Bot

from nestbox.bot.formatting import escape_md
from nestbox.core.branches import MODES, Branch, BranchStore
from nestbox.core.registry import AgentRegistry
from nestbox.config import load_settings


async def create(args: argparse.Namespace) -> None:
    settings = load_settings()
    registry = AgentRegistry.from_file(settings.agents_config)
    branches = BranchStore(settings.data_dir / "branches.json")
    chat_id = settings.chat_id or settings.owner_id

    cwd = args.cwd
    if cwd is None:
        try:
            cwd = registry.get(args.agent).cwd
        except KeyError:
            cwd = None

    title = args.title or args.agent
    bot = Bot(token=settings.bot_token)
    try:
        icon = None
        if args.icon:
            stickers = await bot.get_forum_topic_icon_stickers()
            icon = next(
                (s.custom_emoji_id for s in stickers if s.emoji == args.icon), None
            )
        topic = await bot.create_forum_topic(
            chat_id=chat_id, name=title[:128], icon_custom_emoji_id=icon
        )
        branch = await branches.add(
            Branch(
                thread_id=topic.message_thread_id,
                agent=args.agent,
                title=title,
                cwd=cwd,
                mode=args.mode,
                icon=icon,
            )
        )
        if args.greeting:
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=branch.thread_id,
                text=escape_md(args.greeting),
            )
    finally:
        await bot.session.close()
    print(f"branch {branch.thread_id} · {branch.agent} · {branch.mode} · {branch.cwd or '-'}")


async def show(_: argparse.Namespace) -> None:
    settings = load_settings()
    branches = BranchStore(settings.data_dir / "branches.json")
    for branch in await branches.all():
        mark = "★" if branch.is_main else " "
        print(f"{mark} {branch.thread_id} · {branch.title} · {branch.agent} · {branch.mode} · {branch.cwd or '-'}")


async def drop(args: argparse.Namespace) -> None:
    settings = load_settings()
    branches = BranchStore(settings.data_dir / "branches.json")
    chat_id = settings.chat_id or settings.owner_id
    bot = Bot(token=settings.bot_token)
    try:
        await bot.delete_forum_topic(chat_id=chat_id, message_thread_id=args.thread_id)
    finally:
        await bot.session.close()
    print("dropped" if await branches.remove(args.thread_id) else "no such branch")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="provision")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="create a branch with an agent")
    new.add_argument("agent")
    new.add_argument("--title")
    new.add_argument("--cwd")
    new.add_argument("--mode", choices=MODES, default="ask")
    new.add_argument("--icon", help="an emoji from telegram's topic icon set")
    new.add_argument("--greeting", help="first message in the branch")
    new.set_defaults(func=create)

    listing = sub.add_parser("list", help="list branches")
    listing.set_defaults(func=show)

    remove = sub.add_parser("drop", help="drop a branch together with its topic")
    remove.add_argument("thread_id", type=int)
    remove.set_defaults(func=drop)
    return parser


def cli() -> None:
    args = build_parser().parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    cli()
