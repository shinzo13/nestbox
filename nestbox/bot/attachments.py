from __future__ import annotations

import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

PHOTO_SUFFIX = ".jpg"
# the cloud Bot API getFile limit; beyond it you need your own api server
BOT_API_LIMIT = 20 * 1024 * 1024

log = logging.getLogger(__name__)


def _candidates(message: Message) -> list[tuple[str, str | None, int | None]]:
    """file_id, a name hint and the size, for every kind of attachment a person sends."""
    if message.photo:
        largest = message.photo[-1]
        return [(largest.file_id, None, largest.file_size)]
    for attachment, name in (
        (message.document, getattr(message.document, "file_name", None)),
        (message.audio, getattr(message.audio, "file_name", None)),
        (message.video, getattr(message.video, "file_name", None)),
        (message.voice, None),
        (message.video_note, None),
        (message.animation, getattr(message.animation, "file_name", None)),
        (message.sticker, None),
    ):
        if attachment is not None:
            return [(attachment.file_id, name, getattr(attachment, "file_size", None))]
    return []


def _human_size(size: int | None) -> str:
    if not size:
        return "unknown size"
    return f"{size / 1024 / 1024:.1f} MB"


def _too_big(label: str, size: int | None, message_id: int) -> str:
    """The Bot API will not hand this file over, but mtproto will."""
    return (
        f"{label} ({_human_size(size)}) is over the Bot API limit, fetch it over mtproto: "
        f"`uv run python -m nestbox.bigfile {message_id}` from the bot's directory"
    )


async def save_incoming(message: Message, inbox: Path) -> tuple[list[Path], list[str]]:
    """Downloaded files, and why the rest could not be taken."""
    saved: list[Path] = []
    skipped: list[str] = []
    for file_id, name, size in _candidates(message):
        label = name or "file"
        if size is not None and size > BOT_API_LIMIT:
            skipped.append(_too_big(label, size, message.message_id))
            continue
        try:
            info = await message.bot.get_file(file_id)
            suffix = Path(name or info.file_path or PHOTO_SUFFIX).suffix or PHOTO_SUFFIX
            target = inbox / f"{file_id[-16:]}{suffix}"
            inbox.mkdir(parents=True, exist_ok=True)
            await message.bot.download_file(info.file_path, destination=target)
        except TelegramBadRequest as exc:
            log.warning("attachment %s failed to download: %s", label, exc)
            if "too big" in exc.message.lower():
                skipped.append(_too_big(label, size, message.message_id))
            else:
                skipped.append(f"{label} ({_human_size(size)}): telegram refused: {exc.message}")
            continue
        saved.append(target)
    return saved, skipped


async def send_attachments(
    bot, chat_id: int, thread_id: int | None, paths: list[str]
) -> list[str]:
    """Returns the paths that could not be sent."""
    from aiogram.types import FSInputFile

    failed: list[str] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            failed.append(raw)
            continue
        document = FSInputFile(path)
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            await bot.send_photo(chat_id=chat_id, message_thread_id=thread_id, photo=document)
        else:
            await bot.send_document(chat_id=chat_id, message_thread_id=thread_id, document=document)
    return failed
