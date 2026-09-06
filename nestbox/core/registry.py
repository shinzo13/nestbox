from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUBAGENT_PROMPT = """You are a separate subagent session in the user's working setup.
You are driven not by the user directly but by the main orchestrator agent: messages come from it, and you report back to it.

Your area: {area}. Stay inside it and keep out of other directories.
The orchestrator's shared memory is not yours to manage; you may keep your own notes inside your directory.

Answer briefly: what was done, what matters, what broke. No walls of text, no recaps."""


@dataclass(slots=True)
class AgentSpec:
    name: str
    description: str = ""
    cwd: str | None = None
    system_prompt: str | None = None
    model: str | None = None
    permission_mode: str | None = None
    skills: list[str] | None = None
    aliases: list[str] = field(default_factory=list)
    setting_sources: list[str] | None = None
    inherit_user_context: bool = False

    @property
    def area(self) -> str:
        parts = [self.description or self.name]
        if self.cwd:
            parts.append(self.cwd)
        return " · ".join(parts)

    def build_system_prompt(self) -> Any:
        """The orchestrator runs with the full user context, subagents with a bare one."""
        if self.inherit_user_context and not self.system_prompt:
            return None
        append = self.system_prompt or SUBAGENT_PROMPT.format(area=self.area)
        return {"type": "preset", "preset": "claude_code", "append": append}

    def effective_setting_sources(self) -> list[str]:
        if self.setting_sources is not None:
            return self.setting_sources
        return ["user", "project"] if self.inherit_user_context else ["project"]


class AgentRegistry:
    def __init__(self, agents: dict[str, AgentSpec], default: str) -> None:
        self._agents = agents
        self._default = default
        self._by_alias = {
            alias: spec.name for spec in agents.values() for alias in spec.aliases
        }

    @classmethod
    def from_file(cls, path: Path) -> "AgentRegistry":
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        entries = raw.get("agents", {})
        agents = {
            name: AgentSpec(name=name, **body) for name, body in entries.items()
        }
        default = raw.get("default", next(iter(agents), "main"))
        if default not in agents:
            raise ValueError(f"default agent {default!r} is not defined")
        return cls(agents, default)

    @property
    def default(self) -> AgentSpec:
        return self._agents[self._default]

    def get(self, name: str | None) -> AgentSpec:
        if not name:
            return self.default
        resolved = self._by_alias.get(name, name)
        if resolved not in self._agents:
            raise KeyError(name)
        return self._agents[resolved]

    def all(self) -> list[AgentSpec]:
        return list(self._agents.values())
