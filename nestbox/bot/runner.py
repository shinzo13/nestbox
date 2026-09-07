from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from nestbox.bot.formatting import (
    MARKDOWN_LIMIT,
    TELEGRAM_LIMIT,
    escape_md,
    extract_attachments,
    human_duration,
    split_message,
)
from nestbox.bot.markdown import to_telegram_markdown
from nestbox.bot.preview import LivePreview
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
    summary: str | None = None
    attachments: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LiveHandle:
    session: LiveSession
    agent: str
    touched_at: float
    pinned: bool = False


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

    async def wake(
        self, spec: AgentSpec, key: str, resume_session: str | None, pinned: bool = False
    ) -> None:
        await self.sleep(key)
        session = self._engine.live(self._build_request("", spec, resume_session))
        await session.open()
        self._live[key] = LiveHandle(
            session=session, agent=spec.name, touched_at=time.monotonic(), pinned=pinned
        )

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
                if not handle.pinned
                and now - handle.touched_at > IDLE_SLEEP_AFTER
                and not self.is_busy(key)
            ]
            for key in stale:
                await self.sleep(key)

    def _build_request(
        self, prompt: str, spec: AgentSpec, resume_session: str | None, fork: bool = False
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
            disallowed_tools=spec.disallowed_tools,
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
        preview = LivePreview(bot, chat_id, thread_id)
        await preview.start(spec.name)

        handle = None if fork else self._live.get(key)
        if handle is not None and handle.agent == spec.name:
            handle.touched_at = time.monotonic()
            events = handle.session.send(prompt)
        else:
            handle = None
            events = self._engine.run(self._build_request(prompt, spec, resume_session, fork))

        outcome = RunOutcome()
        texts: list[str] = []
        task = asyncio.current_task()
        if task is not None:
            self._active[key] = task

        try:
            async for event in events:
                if isinstance(event, SessionStarted):
                    outcome.session_id = event.session_id
                    if persist:
                        await self._store.set(key, event.session_id, spec.name)
                elif isinstance(event, ToolStarted):
                    label = f"{event.name}: {event.summary}" if event.summary else event.name
                    outcome.tools.append(event.name)
                    preview.tool(label)
                    await preview.flush()
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
            await preview.fail("⛔ stopped")
            raise
        finally:
            self._active.pop(key, None)
            if handle is not None:
                handle.touched_at = time.monotonic()

        outcome.text = self._pick_text(texts)
        outcome.summary = self._summary_line(spec.name, outcome)
        chunks, outcome.attachments = render_reply(outcome)
        await preview.finish(chunks)
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


def append_summary(chunks: list[str], summary: str | None) -> list[str]:
    """The run summary lives at the tail of the answer, not as a message before it."""
    if not summary:
        return chunks
    tail = f"_{escape_md(summary)}_"
    if chunks and len(chunks[-1]) + len(tail) + 2 <= TELEGRAM_LIMIT:
        chunks[-1] = f"{chunks[-1]}\n\n{tail}"
    else:
        chunks.append(tail)
    return chunks


def render_reply(outcome: RunOutcome) -> tuple[list[str], list[str]]:
    if outcome.error:
        chunks = split_message(escape_md(f"⚠️ {outcome.error}"))
        return append_summary(chunks, outcome.summary), []
    if not outcome.text:
        return append_summary(split_message(escape_md("(empty answer)")), outcome.summary), []
    text, attachments = extract_attachments(outcome.text)
    if not text:
        text = "done"
    chunks = [to_telegram_markdown(chunk) for chunk in split_message(text, MARKDOWN_LIMIT)]
    return append_summary(chunks, outcome.summary), attachments
