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
- `nestbox/bot/` — aiogram layer: handlers, live preview, formatting.
- `nestbox/bot/preview.py` — the single message a run lives in: placeholder, tool
  progress, then the answer itself.

## Code names

Branch agents get code names picked by the orchestrator (stars: `vega`,
`orion`, `lyra`, `mira`), never the project's own name — a topic called
`web` next to the web repo reads as the repo itself. The project the
agent works on stays in the agent's `description` and `cwd`, and the old name
survives as an alias.

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

The run summary (`✅ master · 1m19s · 15 tool calls`) is appended to the answer
itself, so a reply is always a single message.

The bot only answers `OWNER_ID`. Agents run with `bypassPermissions` by default;
override per agent in `config/agents.toml`.

## One message per run

A run starts by posting `⏳ master is working…`, which lists the tools as they are
called and is then edited into the answer itself — no extra messages, no
deletions. The run summary (`✅ master · 1m19s · 15 tool calls`) is appended to
the tail of that message. Answers longer than one Telegram message spill into
follow-up messages.

## Known gaps

- Nested markdown (lists inside quotes, tables) is flattened to plain text.
- Progress updates are throttled to one edit per 3s by Telegram's limits.
