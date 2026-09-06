from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from nestbox.bot.formatting import escape_md, human_duration, split_message
from nestbox.core.engine.base import (
    Engine,
    LiveSession,
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
IDLE_SLEEP_AFTER = 1800.0
JANITOR_INTERVAL = 60.0


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


@dataclass(slots=True)
class LiveHandle:
    session: LiveSession
    agent: str
    touched_at: float


class AgentRunner:
    def __init__(self, engine: Engine, store: SessionStore) -> None:
        self._engine = engine
        self._store = store
        self._active: dict[str, asyncio.Task] = {}
        self._live: dict[str, LiveHandle] = {}
        self._janitor: asyncio.Task | None = None

    def is_busy(self, key: str) -> bool:
        task = self._active.get(key)
        return task is not None and not task.done()

    def is_awake(self, key: str) -> bool:
        return key in self._live

    def awake_keys(self) -> set[str]:
        return set(self._live)

    def cancel(self, key: str) -> bool:
        handle = self._live.get(key)
        task = self._active.get(key)
        busy = task is not None and not task.done()
        if handle is not None and busy:
            asyncio.create_task(handle.session.interrupt())
            return True
        if busy:
            task.cancel()
            return True
        return False

    async def wake(self, spec: AgentSpec, key: str, resume_session: str | None) -> None:
        await self.sleep(key)
        session = self._engine.live(self._build_request("", spec, resume_session))
        await session.open()
        self._live[key] = LiveHandle(session=session, agent=spec.name, touched_at=time.monotonic())

    async def sleep(self, key: str) -> bool:
        handle = self._live.pop(key, None)
        if handle is None:
            return False
        await handle.session.close()
        return True

    def start_janitor(self) -> None:
        if self._janitor is None or self._janitor.done():
            self._janitor = asyncio.create_task(self._janitor_loop())

    async def _janitor_loop(self) -> None:
        while True:
            await asyncio.sleep(JANITOR_INTERVAL)
            now = time.monotonic()
            stale = [
                key
                for key, handle in self._live.items()
                if now - handle.touched_at > IDLE_SLEEP_AFTER and not self.is_busy(key)
            ]
            for key in stale:
                await self.sleep(key)

    @staticmethod
    def _build_request(
        prompt: str, spec: AgentSpec, resume_session: str | None, fork: bool = False
    ) -> RunRequest:
        return RunRequest(
            prompt=prompt,
            cwd=spec.cwd,
            session_id=resume_session,
            fork=fork,
            system_prompt=spec.build_system_prompt(),
            model=spec.model,
            permission_mode=spec.permission_mode,
            skills=spec.skills,
            setting_sources=spec.effective_setting_sources(),
        )

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

        handle = None if fork else self._live.get(key)
        if handle is not None and handle.agent == spec.name:
            handle.touched_at = time.monotonic()
            stream = handle.session.send(prompt)
        else:
            handle = None
            stream = self._engine.run(self._build_request(prompt, spec, resume_session, fork))

        outcome = RunOutcome()
        texts: list[str] = []
        task = asyncio.current_task()
        if task is not None:
            self._active[key] = task

        try:
            async for event in stream:
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
            if handle is not None:
                handle.touched_at = time.monotonic()

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
        if outcome.tools:
            parts.append(f"{len(outcome.tools)} tool calls")
        return " · ".join(parts)


def render_reply(outcome: RunOutcome) -> list[str]:
    if outcome.error:
        return split_message(escape_md(f"⚠️ {outcome.error}"))
    if not outcome.text:
        return split_message(escape_md("(empty answer)"))
    return [escape_md(chunk) for chunk in split_message(outcome.text)]
