from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUBAGENT_PROMPT = """You are a separate subagent session in the user's working setup.
Above you is the orchestrator, claude-master. Tasks come two ways: straight from the owner in this topic, and from the orchestrator (marked "task from the orchestrator"); in the second case your answer goes back to it.

Your area: {area}. Stay inside it and keep out of other directories.
The orchestrator's shared memory is not yours to manage; you may keep your own notes inside your directory.

Answer briefly: what was done, what matters, what broke. No walls of text, no recaps."""

JOURNAL_HINT = """Your journal for the last few days. You wrote it for yourself, so that life does not start over every session:

{entries}

Append to it yourself when a day turns out to matter: `uv run python -c` with nestbox.core.journal.Journal, or just append to the file. Write for yourself, not as a report."""

FILE_HINT = """To hand a file to the person you are talking to, put [[send:/absolute/path]] on its own line in the answer: the bot strips the line and sends the file as an attachment.
Files sent to you arrive as a path in the message text; read them from disk."""


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
    disallowed_tools: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    journal: str = ""

    @property
    def area(self) -> str:
        parts = [self.description or self.name]
        if self.cwd:
            parts.append(self.cwd)
        return " · ".join(parts)

    def build_system_prompt(self) -> Any:
        """The orchestrator runs with the full user context, subagents with a bare one."""
        parts = []
        if not self.inherit_user_context or self.system_prompt:
            parts.append(self.system_prompt or SUBAGENT_PROMPT.format(area=self.area))
        parts.append(FILE_HINT)
        if self.journal:
            parts.append(JOURNAL_HINT.format(entries=self.journal, folder=self.journal_folder or "the journal folder"))
        return {"type": "preset", "preset": "claude_code", "append": "\n\n".join(parts)}

    def effective_setting_sources(self) -> list[str]:
        if self.setting_sources is not None:
            return self.setting_sources
        return ["user", "project"] if self.inherit_user_context else ["project"]


WRITE_TOOLS = ["Edit", "Write", "NotebookEdit"]


def tools_for_mode(mode: str) -> list[str]:
    """ask: the agent only looks and explains; work: it edits."""
    return list(WRITE_TOOLS) if mode == "ask" else []


class AgentRegistry:
    def __init__(self, agents: dict[str, AgentSpec], default: str) -> None:
        self._agents = agents
        self._default = default
        self._orchestrator_extra: dict[str, Any] = {}
        self._journal = ""
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
        default = raw.get("default", next(iter(agents), "master"))
        if default not in agents:
            raise ValueError(f"default agent {default!r} is not defined")
        return cls(agents, default)

    def set_journal(self, text: str) -> None:
        """Fresh journal entries go into the orchestrator's prompt at startup."""
        self._journal = text.strip()

    def set_orchestrator_tools(self, server: Any, name: str = "nestbox") -> None:
        """Only the orchestrator gets the delegation handles."""
        self._orchestrator_extra = {"mcp_servers": {name: server}}

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

    def for_branch(self, branch) -> AgentSpec:
        """The branch is the source of truth: the toml template only fills the gaps."""
        try:
            template = self.get(branch.agent)
        except KeyError:
            template = AgentSpec(name=branch.agent, description=branch.title)
        return AgentSpec(
            name=template.name,
            description=template.description or branch.title,
            cwd=branch.cwd or template.cwd,
            system_prompt=template.system_prompt,
            model=template.model,
            permission_mode=template.permission_mode,
            skills=template.skills,
            aliases=template.aliases,
            setting_sources=template.setting_sources,
            inherit_user_context=branch.is_main or template.inherit_user_context,
            disallowed_tools=tools_for_mode(branch.mode),
            extra=dict(self._orchestrator_extra) if branch.is_main else {},
            journal=self._journal if branch.is_main else "",
        )
