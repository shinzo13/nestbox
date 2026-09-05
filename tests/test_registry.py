import pytest

from nestbox.core.registry import AgentRegistry

CONFIG = """
default = "main"

[agents.main]
description = "orchestrator"
cwd = "/home/me"
aliases = ["boss"]

[agents.web]
description = "web app"
cwd = "/home/me/projects/web"
"""


@pytest.fixture
def registry(tmp_path):
    path = tmp_path / "agents.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return AgentRegistry.from_file(path)


def test_default_agent(registry):
    assert registry.default.name == "main"


def test_alias_resolves(registry):
    assert registry.get("boss").name == "main"


def test_missing_agent_raises(registry):
    with pytest.raises(KeyError):
        registry.get("nope")


def test_none_falls_back_to_default(registry):
    assert registry.get(None).name == "main"


def test_unknown_default_rejected(tmp_path):
    path = tmp_path / "agents.toml"
    path.write_text('default = "ghost"\n\n[agents.main]\n', encoding="utf-8")
    with pytest.raises(ValueError):
        AgentRegistry.from_file(path)
