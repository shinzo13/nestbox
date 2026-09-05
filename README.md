# nestbox

Telegram front-end and orchestrator for Claude Code agents.

One forum topic = one branch = one agent session. The bot talks to Claude Code
through the Agent SDK, so tools, skills, MCP servers and `CLAUDE.md` all keep
working; only the transport is ours.

## Layout

- `nestbox/core/engine/` — the only place that knows about Claude Code.
  `base.py` is a neutral contract (`RunRequest` in, event stream out),
  `claude.py` implements it over the Agent SDK.
- `nestbox/core/registry.py` — agents defined in `config/agents.toml`, not in code.
- `nestbox/core/sessions.py` — topic to session mapping, JSON on disk.
- `nestbox/core/usage.py` — subscription limits via the OAuth usage endpoint.
- `nestbox/bot/` — aiogram layer: handlers, progress reporting, formatting.

## Commands

| command | what it does |
| --- | --- |
| `/agent <name>` | switch the current topic to another agent |
| `/agents` | list configured agents |
| `/new` | start a fresh session in this topic |
| `/btw <question>` | side question on a forked session, main branch untouched |
| `/usage` | remaining subscription limits |
| `/sessions` | active topics |
| `/stop` | cancel the running task |

## Setup

```bash
uv sync
cp .env.example .env   # BOT_TOKEN, OWNER_ID
uv run python -m nestbox
```

The bot only answers `OWNER_ID`. Agents run with `bypassPermissions` by default;
override per agent in `config/agents.toml`.

## Known gaps

- Replies are escaped as plain MarkdownV2 text, so model markdown (code blocks,
  bold) is not rendered yet.
- `/wake` and `/sleep` for long-lived background sessions are not implemented.
- No git operations, no file uploads, no attachment handling yet.
