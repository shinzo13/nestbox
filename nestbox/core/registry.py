from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


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
