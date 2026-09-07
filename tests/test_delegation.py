import asyncio
from pathlib import Path

from nestbox.bot.events import EventPump
from nestbox.core.branches import Branch, BranchStore
from nestbox.core.registry import AgentRegistry
from nestbox.core.sessions import SessionStore


def run(coro):
    return asyncio.run(coro)


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.busy = set()

    def is_busy(self, key):
        return key in self.busy

    def is_awake(self, key):
        return False

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        from nestbox.bot.runner import RunOutcome

        return RunOutcome(text="done", summary="✅")


def test_orchestrator_gets_tools_but_subagents_do_not(tmp_path):
    toml = tmp_path / "agents.toml"
    toml.write_text(
        'default = "claude-master"\n\n[agents.claude-master]\ncwd = "/home"\n'
        '\n[agents.claude-web]\ncwd = "/tmp"\n',
        encoding="utf-8",
    )
    registry = AgentRegistry.from_file(toml)
    registry.set_orchestrator_tools({"type": "sdk"})
    main = Branch(thread_id=1, agent="claude-master", title="master", is_main=True)
    sub = Branch(thread_id=2, agent="claude-web", title="web")
    assert registry.for_branch(main).extra == {"mcp_servers": {"nestbox": {"type": "sdk"}}}
    assert registry.for_branch(sub).extra == {}


def test_event_pump_runs_the_orchestrator(tmp_path):
    from types import SimpleNamespace

    branches = BranchStore(tmp_path / "branches.json")
    sessions = SessionStore(tmp_path / "sessions.json")
    runner = FakeRunner()
    toml = tmp_path / "agents.toml"
    toml.write_text('default = "claude-master"\n\n[agents.claude-master]\ncwd = "/home"\n', encoding="utf-8")
    deps = SimpleNamespace(
        branches=branches,
        sessions=sessions,
        runner=runner,
        registry=AgentRegistry.from_file(toml),
        chat_id=-100,
        maintenance_lock=tmp_path / "absent.lock",
    )
    folder = tmp_path / "events"
    folder.mkdir()
    (folder / "1.txt").write_text("container is down", encoding="utf-8")
    pump = EventPump(deps, bot=None, folder=folder)

    async def scenario():
        await branches.add(Branch(thread_id=7, agent="claude-master", title="master", is_main=True))
        await pump.tick()

    run(scenario())
    assert runner.calls[0]["prompt"] == "container is down"
    assert runner.calls[0]["thread_id"] == 7
    assert list(folder.glob("*.txt")) == []


def test_event_pump_waits_while_busy(tmp_path):
    from types import SimpleNamespace

    branches = BranchStore(tmp_path / "branches.json")
    sessions = SessionStore(tmp_path / "sessions.json")
    runner = FakeRunner()
    toml = tmp_path / "agents.toml"
    toml.write_text('default = "claude-master"\n\n[agents.claude-master]\ncwd = "/home"\n', encoding="utf-8")
    deps = SimpleNamespace(
        branches=branches,
        sessions=sessions,
        runner=runner,
        registry=AgentRegistry.from_file(toml),
        chat_id=-100,
        maintenance_lock=tmp_path / "absent.lock",
    )
    folder = tmp_path / "events"
    folder.mkdir()
    (folder / "1.txt").write_text("hold on", encoding="utf-8")
    runner.busy.add(SessionStore.key(-100, 7))
    pump = EventPump(deps, bot=None, folder=folder)

    async def scenario():
        await branches.add(Branch(thread_id=7, agent="claude-master", title="master", is_main=True))
        await pump.tick()

    run(scenario())
    assert runner.calls == []
    assert len(list(folder.glob("*.txt"))) == 1
