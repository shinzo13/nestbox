"""Working around the getFile limit: fetch the attachment over mtproto, not the Bot API.

The Bot API gives a bot at most 20 MB; mtproto has no such ceiling. The client
logs in with the same bot_token, no separate account needed: the file_id from
the update resolves into a document Telegram is willing to hand over in full.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from telethon import TelegramClient
from telethon.utils import resolve_bot_file_id

from nestbox.config import load_settings


async def fetch(ref: str, dest: Path) -> Path:
    """ref is either a message_id in the working chat or a file_id from an update."""
    settings = load_settings()
    if not settings.tg_api_id or not settings.tg_api_hash:
        raise SystemExit("TG_API_ID/TG_API_HASH missing from .env")

    media: object | None = None
    message_id = int(ref) if ref.lstrip("-").isdigit() else None
    if message_id is None:
        # telethon cannot parse every file_id, so message_id is the main path
        media = resolve_bot_file_id(ref)
        if media is None:
            raise SystemExit("could not parse the file_id: forward the file again and use its message_id")

    session = str(settings.data_dir / "mtproto-bot")
    client = TelegramClient(session, settings.tg_api_id, settings.tg_api_hash)
    await client.start(bot_token=settings.bot_token)
    try:
        if media is None:
            state = json.loads((settings.state_path).read_text(encoding="utf-8") or "{}")
            chat_id = state.get("chat_id") or settings.chat_id or settings.owner_id
            media = await client.get_messages(chat_id, ids=message_id)
            if media is None:
                raise SystemExit("no such message")
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
    parser.add_argument("ref", help="message_id or file_id")
    parser.add_argument("dest", nargs="?", default="./data/inbox", help="file or directory")
    args = parser.parse_args()
    path = asyncio.run(fetch(args.ref, Path(args.dest)))
    print(path)


if __name__ == "__main__":
    cli()
