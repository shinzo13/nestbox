import asyncio

import pytest
from aiogram.exceptions import TelegramBadRequest

from nestbox.bot.preview import LivePreview
from nestbox.bot.runner import RunOutcome, append_summary, render_reply


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.edits: list[str] = []
        self.deleted: list[int] = []

    async def send_message(self, *, text, **kwargs):
        self.sent.append(text)
        return FakeMessage(len(self.sent))

    async def edit_message_text(self, *, text, **kwargs):
        self.edits.append(text)

    async def delete_message(self, *, chat_id, message_id):
        self.deleted.append(message_id)


def run(coro):
    return asyncio.run(coro)


def test_placeholder_turns_into_the_answer():
    bot = FakeBot()
    preview = LivePreview(bot, -1001234567890, 23)

    async def scenario():
        await preview.start("master")
        preview.tool("Bash: git log")
        await preview.flush(force=True)
        await preview.finish(["done"])

    run(scenario())
    assert len(bot.sent) == 1
    assert bot.sent[0].startswith("⏳ master")
    assert "Bash: git log" in bot.edits[0].replace("\\", "")
    assert bot.edits[-1] == "done"
    assert bot.deleted == []


def test_long_answer_spills_into_extra_messages():
    bot = FakeBot()
    preview = LivePreview(bot, -1001234567890, 23)

    async def scenario():
        await preview.start("master")
        await preview.finish(["first", "second"])

    run(scenario())
    assert bot.edits[-1] == "first"
    assert bot.sent[-1] == "second"


def test_stop_note_replaces_the_placeholder():
    bot = FakeBot()
    preview = LivePreview(bot, -1001234567890, 23)

    async def scenario():
        await preview.start("master")
        await preview.fail("⛔ stopped")

    run(scenario())
    assert len(bot.sent) == 1
    assert bot.edits[-1] == "⛔ stopped"


@pytest.mark.parametrize("summary", [None, ""])
def test_append_summary_noop(summary):
    assert append_summary(["text"], summary) == ["text"]


def test_append_summary_goes_to_the_tail():
    chunks = append_summary(["text"], "✅ main · 3s")
    assert len(chunks) == 1
    assert chunks[0].startswith("text")
    assert chunks[0].endswith("_✅ main · 3s_")


def test_append_summary_spills_into_new_chunk():
    chunks = append_summary(["x" * 4090], "✅ main · 3s")
    assert len(chunks) == 2
    assert chunks[1] == "_✅ main · 3s_"


def test_render_reply_keeps_attachments_and_summary():
    outcome = RunOutcome(text="here\n[[send:/tmp/a.txt]]", summary="✅ main · 3s")
    chunks, attachments = render_reply(outcome)
    assert attachments == ["/tmp/a.txt"]
    assert chunks[-1].endswith("_✅ main · 3s_")


def test_render_reply_marks_errors():
    chunks, _ = render_reply(RunOutcome(error="boom", summary="⚠️ main · 3s"))
    assert "boom" in chunks[0]
    assert chunks[-1].endswith("_⚠️ main · 3s_")


def test_render_reply_renders_markdown():
    outcome = RunOutcome(text="**bold** and `code-1`", summary="✅ main · 3s")
    chunks, _ = render_reply(outcome)
    assert chunks[0].startswith("*bold* and `code-1`")


def test_strip_md_escapes_restores_plain_text():
    from nestbox.bot.formatting import escape_md, strip_md_escapes

    original = "total: 1-2 (three). once_more!"
    assert strip_md_escapes(escape_md(original)) == original


def test_markdown_fallback_retries_without_parse_mode():
    from aiogram.methods import SendMessage

    from nestbox.bot.middlewares import MarkdownFallbackMiddleware

    calls: list[SendMessage] = []

    async def make_request(bot, method):
        calls.append(method)
        if len(calls) == 1:
            raise TelegramBadRequest(method=method, message="can't parse entities: bad offset")
        return "sent"

    method = SendMessage(chat_id=1, text="a\\-b", parse_mode="MarkdownV2")
    result = run(MarkdownFallbackMiddleware()(make_request, None, method))
    assert result == "sent"
    assert calls[1].text == "a-b"
    assert calls[1].parse_mode is None


def test_markdown_fallback_reraises_other_errors():
    from aiogram.methods import SendMessage

    from nestbox.bot.middlewares import MarkdownFallbackMiddleware

    async def make_request(bot, method):
        raise TelegramBadRequest(method=method, message="chat not found")

    method = SendMessage(chat_id=1, text="hi", parse_mode="MarkdownV2")
    with pytest.raises(TelegramBadRequest):
        run(MarkdownFallbackMiddleware()(make_request, None, method))
