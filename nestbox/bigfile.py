"""Working around the getFile limit: fetch the attachment over mtproto, not the Bot API.

The Bot API gives a bot at most 20 MB; mtproto has no such ceiling. The client
logs in with the same bot_token, no separate account needed: the file_id from
the update resolves into a document Telegram is willing to hand over in full.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from telethon import TelegramClient
from telethon.utils import resolve_bot_file_id

from nestbox.config import load_settings


async def fetch(file_id: str, dest: Path) -> Path:
    settings = load_settings()
    if not settings.tg_api_id or not settings.tg_api_hash:
        raise SystemExit("TG_API_ID/TG_API_HASH missing from .env")
    media = resolve_bot_file_id(file_id)
    if media is None:
        raise SystemExit("could not resolve the file_id into a document")

    session = str(settings.data_dir / "mtproto-bot")
    client = TelegramClient(session, settings.tg_api_id, settings.tg_api_hash)
    await client.start(bot_token=settings.bot_token)
    try:
        if dest.is_dir():
            dest = dest / getattr(media, "id", "download").__str__()
        dest.parent.mkdir(parents=True, exist_ok=True)
        saved = await client.download_media(media, file=str(dest))
    finally:
        await client.disconnect()
    if saved is None:
        raise SystemExit("telegram did not return the file")
    return Path(saved)


def cli() -> None:
    parser = argparse.ArgumentParser(prog="bigfile", description="download an attachment over mtproto")
    parser.add_argument("file_id")
    parser.add_argument("dest", nargs="?", default="./data/inbox", help="file or directory")
    args = parser.parse_args()
    path = asyncio.run(fetch(args.file_id, Path(args.dest)))
    print(path)


if __name__ == "__main__":
    cli()
