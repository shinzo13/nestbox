import asyncio

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendRichMessage

from nestbox.bot.preview import ReplyStream
from nestbox.bot.runner import render_block


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class FakeBot:
    def __init__(self, rich_error: bool = False) -> None:
        self.sent: list[tuple[int | None, str]] = []
        self.edits: list[tuple[int, str | None]] = []
        self.rich: list[str] = []
        self.actions: list[str] = []
        self._rich_error = rich_error
        self._ids = 0

    async def __call__(self, method):
        assert isinstance(method, SendRichMessage)
        if self._rich_error:
            raise TelegramBadRequest(method=method, message="rich messages are unavailable")
        self.rich.append(method.rich_message.blocks[0].text)
        self._ids += 1
        return FakeMessage(1000 + self._ids)

    async def send_message(self, *, text, message_thread_id=None, **kwargs):
        self.sent.append((message_thread_id, text))
        self._ids += 1
        return FakeMessage(self._ids)

    async def edit_message_text(self, *, message_id, text=None, rich_message=None, **kwargs):
        self.edits.append((message_id, text))

    async def send_chat_action(self, *, action, **kwargs):
        self.actions.append(action)


def run(coro):
    return asyncio.run(coro)


def test_each_block_goes_out_as_its_own_message():
    bot = FakeBot()
    stream = ReplyStream(bot, -100, 23, "claude-master")

    async def scenario():
        await stream.start()
        await stream.say(["on it"])
        await stream.say(["done"])
        await stream.finish("✅ claude-master · 3s", tools=0)

    run(scenario())
    assert [text for _, text in bot.sent] == ["on it", "done"]
    assert bot.edits[-1][1].endswith("_✅ claude\\-master · 3s_")
    assert bot.actions == ["typing"]


def test_toolcalls_land_in_the_common_channel():
    bot = FakeBot()
    stream = ReplyStream(bot, -100, 23, "claude-master")

    async def scenario():
        stream.tool("Bash: git log")
        await stream.flush(force=True)
        stream.tool("Read: main.py")
        await stream.flush(force=True)

    run(scenario())
    assert bot.rich == ["claude-master's toolcalls"]
    assert bot.edits and bot.edits[-1][1] is None
    assert all(thread is None for thread, _ in bot.sent)


def test_rich_failure_does_not_kill_the_run():
    bot = FakeBot(rich_error=True)
    stream = ReplyStream(bot, -100, 23, "claude-master")

    async def scenario():
        stream.tool("Bash: ls")
        await stream.flush(force=True)
        await stream.flush(force=True)
        await stream.say(["answer"])

    run(scenario())
    assert [text for _, text in bot.sent] == ["answer"]


def test_summary_becomes_its_own_message_when_nothing_was_said():
    bot = FakeBot()
    stream = ReplyStream(bot, -100, 23, "claude-master")
    run(stream.finish("✅ claude-master · 1s", tools=0))
    assert bot.sent[-1][1] == "_✅ claude\\-master · 1s_"


def test_tool_count_links_to_the_log_message():
    bot = FakeBot()
    stream = ReplyStream(bot, -1001234567890, 23, "claude-master")

    async def scenario():
        stream.tool("Bash: ls")
        await stream.flush(force=True)
        await stream.say(["answer"])
        await stream.finish("✅ claude-master · 3s", tools=7)

    run(scenario())
    tail = bot.edits[-1][1]
    assert "[7 tool calls](https://t.me/c/1234567890/1001)" in tail


def test_tool_count_stays_plain_without_a_log():
    bot = FakeBot(rich_error=True)
    stream = ReplyStream(bot, -1001234567890, 23, "claude-master")

    async def scenario():
        stream.tool("Bash: ls")
        await stream.flush(force=True)
        await stream.say(["answer"])
        await stream.finish("✅ claude-master · 3s", tools=7)

    run(scenario())
    assert "https://t.me" not in bot.edits[-1][1]


def test_render_block_splits_markup_and_attachments():
    chunks, attachments = render_block("**bold**\n[[send:/tmp/a.txt]]")
    assert chunks == ["*bold*"]
    assert attachments == ["/tmp/a.txt"]


@pytest.mark.parametrize("raw", ["", "   ", "[[send:/tmp/a.txt]]"])
def test_render_block_without_text(raw):
    chunks, _ = render_block(raw)
    assert chunks == []
