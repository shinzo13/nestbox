from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from nestbox.bot.formatting import escape_md, human_duration, split_message
from nestbox.core.engine.base import (
    Engine,
    Failed,
    Finished,
    RateLimitWarning,
    RunRequest,
    SessionStarted,
    TextChunk,
    ToolStarted,
)
from nestbox.core.registry import AgentSpec
from nestbox.core.sessions import SessionStore

PROGRESS_INTERVAL = 3.0
MAX_PROGRESS_LINES = 6


@dataclass(slots=True)
class RunOutcome:
    session_id: str | None = None
    text: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    error: str | None = None
    rate_limit: RateLimitWarning | None = None
    tools: list[str] = field(default_factory=list)


class ProgressReporter:
    def __init__(self, bot: Bot, chat_id: int, thread_id: int | None) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._thread_id = thread_id
        self._message_id: int | None = None
        self._lines: list[str] = []
        self._last_edit = 0.0
        self._last_payload = ""

    async def start(self, agent: str) -> None:
        message = await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=self._thread_id,
            text=escape_md(f"⏳ {agent} is working…"),
            parse_mode="MarkdownV2",
        )
        self._message_id = message.message_id

    def add(self, line: str) -> None:
        self._lines.append(line)
        del self._lines[:-MAX_PROGRESS_LINES]

    async def flush(self, agent: str, force: bool = False) -> None:
        if self._message_id is None:
            return
        now = time.monotonic()
        if not force and now - self._last_edit < PROGRESS_INTERVAL:
            return
        body = "\n".join(f"· {line}" for line in self._lines)
        payload = escape_md(f"⏳ {agent} is working…\n{body}".strip())
        if payload == self._last_payload:
            return
        self._last_edit = now
        self._last_payload = payload
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=self._message_id,
                text=payload,
                parse_mode="MarkdownV2",
            )
        except TelegramBadRequest:
            pass

    async def finish(self, summary: str) -> None:
        if self._message_id is None:
            return
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=self._message_id,
                text=escape_md(summary),
                parse_mode="MarkdownV2",
            )
        except TelegramBadRequest:
            pass


class AgentRunner:
    def __init__(self, engine: Engine, store: SessionStore) -> None:
        self._engine = engine
        self._store = store
        self._active: dict[str, asyncio.Task] = {}

    def is_busy(self, key: str) -> bool:
        task = self._active.get(key)
        return task is not None and not task.done()

    def cancel(self, key: str) -> bool:
        task = self._active.get(key)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def run(
        self,
        *,
        bot: Bot,
        chat_id: int,
        thread_id: int | None,
        spec: AgentSpec,
        prompt: str,
        resume_session: str | None,
        fork: bool = False,
        persist: bool = True,
    ) -> RunOutcome:
        key = SessionStore.key(chat_id, thread_id)
        reporter = ProgressReporter(bot, chat_id, thread_id)
        await reporter.start(spec.name)

        request = RunRequest(
            prompt=prompt,
            cwd=spec.cwd,
            session_id=resume_session,
            fork=fork,
            system_prompt=spec.system_prompt,
            model=spec.model,
            permission_mode=spec.permission_mode,
            skills=spec.skills,
        )

        outcome = RunOutcome()
        texts: list[str] = []
        task = asyncio.current_task()
        if task is not None:
            self._active[key] = task

        try:
            async for event in self._engine.run(request):
                if isinstance(event, SessionStarted):
                    outcome.session_id = event.session_id
                    if persist:
                        await self._store.set(key, event.session_id, spec.name)
                elif isinstance(event, ToolStarted):
                    label = f"{event.name}: {event.summary}" if event.summary else event.name
                    outcome.tools.append(event.name)
                    reporter.add(label)
                    await reporter.flush(spec.name)
                elif isinstance(event, TextChunk):
                    texts.append(event.text)
                elif isinstance(event, RateLimitWarning):
                    outcome.rate_limit = event
                elif isinstance(event, Finished):
                    outcome.session_id = event.session_id or outcome.session_id
                    outcome.cost_usd = event.cost_usd
                    outcome.duration_ms = event.duration_ms
                    if event.is_error:
                        outcome.error = event.text or "run failed"
                    elif event.text:
                        texts.append(event.text)
                elif isinstance(event, Failed):
                    outcome.error = event.message
        except asyncio.CancelledError:
            await reporter.finish("⛔ stopped")
            raise
        finally:
            self._active.pop(key, None)

        outcome.text = self._pick_text(texts)
        summary = self._summary_line(spec.name, outcome)
        await reporter.finish(summary)
        return outcome

    @staticmethod
    def _pick_text(texts: list[str]) -> str | None:
        cleaned = [text.strip() for text in texts if text and text.strip()]
        if not cleaned:
            return None
        last = cleaned[-1]
        for candidate in reversed(cleaned[:-1]):
            if candidate == last:
                continue
            break
        return last

    @staticmethod
    def _summary_line(agent: str, outcome: RunOutcome) -> str:
        parts = [f"✅ {agent}"]
        if outcome.error:
            parts = [f"⚠️ {agent}"]
        duration = human_duration(outcome.duration_ms)
        if duration:
            parts.append(duration)
        if outcome.cost_usd:
            parts.append(f"${outcome.cost_usd:.2f}")
        if outcome.tools:
            parts.append(f"{len(outcome.tools)} tool calls")
        return " · ".join(parts)


def render_reply(outcome: RunOutcome) -> list[str]:
    if outcome.error:
        return split_message(escape_md(f"⚠️ {outcome.error}"))
    if not outcome.text:
        return split_message(escape_md("(empty answer)"))
    return [escape_md(chunk) for chunk in split_message(outcome.text)]
