from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Protocol


class Capability(StrEnum):
    FORK = "fork"
    LIVE = "live"
    RESUME = "resume"
    USAGE = "usage"
    BACKGROUND = "background"
    INTERRUPT = "interrupt"


@dataclass(slots=True)
class RunRequest:
    prompt: str
    cwd: str | None = None
    session_id: str | None = None
    fork: bool = False
    system_prompt: Any = None
    model: str | None = None
    permission_mode: str | None = None
    skills: list[str] | None = None
    setting_sources: list[str] | None = None
    disallowed_tools: list[str] = field(default_factory=list)
    stream: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Event:
    kind: ClassVar[str] = "event"


@dataclass(slots=True)
class SessionStarted(Event):
    session_id: str
    kind: ClassVar[str] = "session_started"


@dataclass(slots=True)
class TextChunk(Event):
    text: str
    kind: ClassVar[str] = "text"


@dataclass(slots=True)
class PartialText(Event):
    """A piece of text as it is generated, only for the live preview."""

    text: str
    kind: ClassVar[str] = "partial_text"


@dataclass(slots=True)
class ThinkingChunk(Event):
    text: str
    kind: ClassVar[str] = "thinking"


@dataclass(slots=True)
class ToolStarted(Event):
    name: str
    summary: str
    kind: ClassVar[str] = "tool_started"


@dataclass(slots=True)
class ToolFinished(Event):
    name: str
    is_error: bool
    kind: ClassVar[str] = "tool_finished"


@dataclass(slots=True)
class RateLimitWarning(Event):
    utilization: float | None
    resets_at: str | None
    status: str
    kind: ClassVar[str] = "rate_limit"


@dataclass(slots=True)
class Finished(Event):
    session_id: str | None
    is_error: bool
    cost_usd: float | None
    duration_ms: int | None
    num_turns: int | None
    text: str | None
    kind: ClassVar[str] = "finished"


@dataclass(slots=True)
class Failed(Event):
    message: str
    kind: ClassVar[str] = "failed"


class LiveSession(Protocol):
    """A live session: the agent process stays up between messages."""

    session_id: str | None

    async def open(self) -> None: ...

    def send(self, prompt: str) -> AsyncIterator[Event]: ...

    async def interrupt(self) -> None: ...

    async def close(self) -> None: ...


class Engine(Protocol):
    name: str
    capabilities: frozenset[Capability]

    def run(self, request: RunRequest) -> AsyncIterator[Event]: ...

    async def fork(self, session_id: str, cwd: str | None = None) -> str: ...

    def live(self, request: RunRequest) -> LiveSession: ...
