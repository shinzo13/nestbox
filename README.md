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

## Delegation

The orchestrator carries an in-process MCP server (`nestbox/core/delegation.py`)
with `agents`, `delegate`, `new_branch` and `drop_branch`. `delegate` runs the
task in the target branch through the same runner, so the exchange shows up in
that branch's topic and the report comes back to the orchestrator.

Outside events reach the orchestrator through `data/events`: `bin/nudge <text>`
drops a file there, `EventPump` picks it up and turns it into a run in the
orchestrator's branch. Cron watchers (a container watcher, a log watcher)
use it instead of messaging the owner, so a container problem lands on the
orchestrator first. If the bot is down, `nudge` falls back to a direct alert.

## Names

A topic is named after what it is for (`master`, `web`, `api`) while
the agent behind it is `claude-<that>`: `claude-master`, `claude-web`. Older
names stay as aliases so the toml keeps resolving them.

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

The run summary (`✅ claude-master · 1m19s · 15 tool calls`) is appended to the answer
itself, so a reply is always a single message.

The bot only answers `OWNER_ID`. Agents run with `bypassPermissions` by default;
override per agent in `config/agents.toml`.

## One message per run

A run starts by posting `⏳ claude-master is working…`, which lists the tools as they are
called and is then edited into the answer itself — no extra messages, no
deletions. The run summary (`✅ claude-master · 1m19s · 15 tool calls`) is appended to
the tail of that message. Answers longer than one Telegram message spill into
follow-up messages.

## Known gaps

- Nested markdown (lists inside quotes, tables) is flattened to plain text.
- Progress updates are throttled to one edit per 3s by Telegram's limits.
