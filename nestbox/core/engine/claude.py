from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    RateLimitEvent,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)
from claude_agent_sdk import fork_session as sdk_fork_session

from nestbox.core.engine.base import (
    Capability,
    Engine,
    Event,
    Failed,
    Finished,
    RateLimitWarning,
    RunRequest,
    SessionStarted,
    TextChunk,
    ThinkingChunk,
    ToolFinished,
    ToolStarted,
)

TOOL_SUMMARY_KEYS = ("command", "file_path", "pattern", "path", "url", "prompt", "query")


def _summarize_tool_input(payload: dict) -> str:
    for key in TOOL_SUMMARY_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().splitlines()[0][:160]
    return ""


class ClaudeLiveSession:
    """Keeps the agent process up between messages (/wake)."""

    def __init__(self, engine: "ClaudeEngine", request: RunRequest) -> None:
        self._engine = engine
        self._request = request
        self._client: ClaudeSDKClient | None = None
        self.session_id = request.session_id

    async def open(self) -> None:
        options = self._engine._build_options(self._request)
        client = ClaudeSDKClient(options=options)
        await client.connect()
        self._client = client

    async def send(self, prompt: str) -> AsyncIterator[Event]:
        if self._client is None:
            raise RuntimeError("live session is not open")
        await self._client.query(prompt)
        async for message in self._client.receive_response():
            for event in self._engine._translate(message):
                if isinstance(event, SessionStarted):
                    self.session_id = event.session_id
                yield event

    async def interrupt(self) -> None:
        if self._client is not None:
            await self._client.interrupt()

    async def close(self) -> None:
        if self._client is None:
            return
        client, self._client = self._client, None
        await client.disconnect()


class ClaudeEngine(Engine):
    name = "claude"
    capabilities = frozenset(
        {
            Capability.FORK,
            Capability.RESUME,
            Capability.USAGE,
            Capability.INTERRUPT,
            Capability.LIVE,
        }
    )

    def __init__(self, setting_sources: list[str] | None = None) -> None:
        self._setting_sources = setting_sources or ["user", "project"]

    def _build_options(self, request: RunRequest) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cwd=request.cwd,
            resume=request.session_id,
            fork_session=request.fork,
            system_prompt=request.system_prompt,
            model=request.model,
            permission_mode=request.permission_mode or "bypassPermissions",
            skills=request.skills if request.skills is not None else "all",
            setting_sources=request.setting_sources or self._setting_sources,
            include_partial_messages=False,
            **request.extra,
        )

    async def run(self, request: RunRequest) -> AsyncIterator[Event]:
        options = self._build_options(request)
        reported_session = request.session_id if not request.fork else None
        try:
            async for message in query(prompt=request.prompt, options=options):
                for event in self._translate(message):
                    if isinstance(event, SessionStarted):
                        if event.session_id == reported_session:
                            continue
                        reported_session = event.session_id
                    yield event
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield Failed(message=f"{type(exc).__name__}: {exc}")

    def _translate(self, message: object) -> list[Event]:
        events: list[Event] = []
        if isinstance(message, AssistantMessage):
            session_id = getattr(message, "session_id", None)
            if session_id:
                events.append(SessionStarted(session_id=session_id))
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    events.append(TextChunk(text=block.text))
                elif isinstance(block, ThinkingBlock):
                    events.append(ThinkingChunk(text=block.thinking))
                elif isinstance(block, ToolUseBlock):
                    events.append(
                        ToolStarted(
                            name=block.name,
                            summary=_summarize_tool_input(block.input or {}),
                        )
                    )
                elif isinstance(block, ToolResultBlock):
                    events.append(
                        ToolFinished(name="", is_error=bool(block.is_error))
                    )
        elif isinstance(message, RateLimitEvent):
            info = message.rate_limit_info
            events.append(
                RateLimitWarning(
                    utilization=getattr(info, "utilization", None),
                    resets_at=str(getattr(info, "resets_at", "") or "") or None,
                    status=str(getattr(info, "status", "") or "unknown"),
                )
            )
        elif isinstance(message, ResultMessage):
            events.append(
                Finished(
                    session_id=message.session_id,
                    is_error=bool(message.is_error),
                    cost_usd=message.total_cost_usd,
                    duration_ms=message.duration_ms,
                    num_turns=message.num_turns,
                    text=message.result,
                )
            )
        return events

    def live(self, request: RunRequest) -> ClaudeLiveSession:
        return ClaudeLiveSession(self, request)

    async def fork(self, session_id: str, cwd: str | None = None) -> str:
        result = await asyncio.to_thread(sdk_fork_session, session_id, cwd)
        return result.session_id
