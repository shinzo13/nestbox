from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from nestbox.bot.deps import Deps
from nestbox.bot.formatting import escape_md
from nestbox.core.branches import Branch

router = Router(name="branch")

ICONS_PER_PAGE = 24
ICON_COLUMNS = 6
PENDING_TTL = 300.0

_pending_rename: dict[tuple[int, int], float] = {}


def _menu(thread_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ title", callback_data=f"br:name:{thread_id}"),
                InlineKeyboardButton(text="🎨 icon", callback_data=f"br:icons:{thread_id}:0"),
            ]
        ]
    )


def _icon_keyboard(deps: Deps, thread_id: int, page: int) -> InlineKeyboardMarkup:
    icons = deps.icons
    pages = max(1, (len(icons) + ICONS_PER_PAGE - 1) // ICONS_PER_PAGE)
    page %= pages
    chunk = icons[page * ICONS_PER_PAGE : (page + 1) * ICONS_PER_PAGE]
    rows: list[list[InlineKeyboardButton]] = []
    for start in range(0, len(chunk), ICON_COLUMNS):
        rows.append(
            [
                InlineKeyboardButton(
                    text=emoji, callback_data=f"br:seticon:{thread_id}:{custom_id}"
                )
                for emoji, custom_id in chunk[start : start + ICON_COLUMNS]
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="‹", callback_data=f"br:icons:{thread_id}:{page - 1}"),
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="br:noop"),
            InlineKeyboardButton(text="›", callback_data=f"br:icons:{thread_id}:{page + 1}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("branch"))
async def cmd_branch(message: Message, deps: Deps) -> None:
    branch = await deps.branches.get(message.message_thread_id)
    if branch is None:
        await deps.redirect_to_main(message)
        return
    body = f"{branch.title}\nagent: {branch.agent} · mode: {branch.mode}\n{branch.cwd or '-'}"
    await message.answer(
        escape_md(body),
        parse_mode="MarkdownV2",
        reply_markup=_menu(branch.thread_id),
    )


@router.callback_query(F.data.startswith("br:name:"))
async def on_rename(call: CallbackQuery, deps: Deps) -> None:
    thread_id = int(call.data.split(":")[2])
    _pending_rename[(call.message.chat.id, thread_id)] = time.monotonic()
    await call.answer()
    await call.message.answer("send the new branch title")


@router.callback_query(F.data.startswith("br:icons:"))
async def on_icons(call: CallbackQuery, deps: Deps) -> None:
    _, _, thread_id, page = call.data.split(":")
    if not deps.icons:
        await call.answer("icons failed to load", show_alert=True)
        return
    await call.message.edit_reply_markup(
        reply_markup=_icon_keyboard(deps, int(thread_id), int(page))
    )
    await call.answer()


@router.callback_query(F.data.startswith("br:seticon:"))
async def on_set_icon(call: CallbackQuery, deps: Deps) -> None:
    _, _, thread_id, custom_id = call.data.split(":")
    thread_id = int(thread_id)
    await call.bot.edit_forum_topic(
        chat_id=call.message.chat.id,
        message_thread_id=thread_id,
        icon_custom_emoji_id=custom_id,
    )
    await deps.branches.update(thread_id, icon=custom_id)
    await call.message.edit_reply_markup(reply_markup=_menu(thread_id))
    await call.answer("icon updated")


@router.callback_query(F.data == "br:noop")
async def on_noop(call: CallbackQuery) -> None:
    await call.answer()


async def consume_pending(message: Message, deps: Deps, branch: Branch) -> bool:
    """Waiting for a branch title: plain text, not a command."""
    key = (message.chat.id, branch.thread_id)
    started = _pending_rename.get(key)
    if started is None:
        return False
    del _pending_rename[key]
    if time.monotonic() - started > PENDING_TTL:
        return False
    title = (message.text or "").strip()
    if not title:
        return False
    await message.bot.edit_forum_topic(
        chat_id=message.chat.id,
        message_thread_id=branch.thread_id,
        name=title[:128],
    )
    await deps.branches.update(branch.thread_id, title=title)
    await message.answer("renamed")
    return True
