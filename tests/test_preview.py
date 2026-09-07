import asyncio

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessageDraft

from nestbox.bot.preview import LivePreview
from nestbox.bot.runner import RunOutcome, append_summary, render_reply


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class FakeBot:
    def __init__(self, draft_error: bool = False) -> None:
        self.drafts: list[str] = []
        self.sent: list[str] = []
        self.edits: list[str] = []
        self.deleted: list[int] = []
        self._draft_error = draft_error

    async def __call__(self, method):
        assert isinstance(method, SendMessageDraft)
        if self._draft_error:
            raise TelegramBadRequest(method=method, message="TEXTDRAFT_PEER_INVALID")
        self.drafts.append(method.text)
        return True

    async def send_message(self, *, text, **kwargs):
        self.sent.append(text)
        return FakeMessage(len(self.sent))

    async def edit_message_text(self, *, text, **kwargs):
        self.edits.append(text)

    async def delete_message(self, *, chat_id, message_id):
        self.deleted.append(message_id)


def run(coro):
    return asyncio.run(coro)


def test_private_chat_streams_drafts():
    bot = FakeBot()
    preview = LivePreview(bot, 123456789, 23, stream=True)

    async def scenario():
        await preview.start("main")
        preview.partial("hel")
        await preview.flush(force=True)
        preview.partial("lo")
        await preview.flush(force=True)
        await preview.close()

    run(scenario())
    assert bot.sent == []
    assert bot.drafts[0].startswith("⏳")
    assert "hello" in bot.drafts[-1]
    assert bot.deleted == []


def test_group_falls_back_to_edits_and_cleans_up():
    bot = FakeBot(draft_error=True)
    preview = LivePreview(bot, -1001234567890, 23, stream=True)

    async def scenario():
        await preview.start("main")
        preview.partial("answer")
        await preview.flush(force=True)
        await preview.close()

    run(scenario())
    assert len(bot.sent) == 1
    assert "answer" in bot.edits[-1]
    assert bot.deleted == [1]


def test_stop_note_survives_as_message():
    bot = FakeBot()
    preview = LivePreview(bot, 123456789, 23, stream=True)

    async def scenario():
        await preview.start("main")
        await preview.close("⛔ stopped")

    run(scenario())
    assert bot.sent == ["⛔ stopped"]


def test_tools_are_shown_without_stream():
    bot = FakeBot()
    preview = LivePreview(bot, -100123, None, stream=False)

    async def scenario():
        await preview.start("web")
        preview.tool("Bash: git log")
        preview.partial("this must not reach the preview")
        await preview.flush(force=True)
        await preview.close()

    run(scenario())
    assert "Bash: git log" in bot.edits[-1].replace("\\", "")
    assert "must not" not in bot.edits[-1]


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
