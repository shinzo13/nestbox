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
- `nestbox/bot/preview.py` — what the answer looks like while it is being written:
  `sendMessageDraft` in private chats, an edited message everywhere else.
  Turn it off with `STREAM_REPLIES=0` and the preview falls back to the old
  list of tool calls.

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

The run summary (`✅ main · 1m19s · 15 tool calls`) is appended to the answer
itself, so a reply is always a single message.

The bot only answers `OWNER_ID`. Agents run with `bypassPermissions` by default;
override per agent in `config/agents.toml`.

## Streaming replies

`STREAM_REPLIES=1` (default) streams the answer as it is generated: partial text
is pushed into a live preview, which disappears once the final message is sent.
Private chats use `sendMessageDraft`; groups fall back to editing a placeholder
message, since Telegram rejects drafts outside private chats. Set
`STREAM_REPLIES=0` and restart to get the old behaviour (tool list only).

The run summary (`✅ main · 1m19s · 15 tool calls`) is appended to the end of the
reply instead of being sent as a separate message before it.

## Known gaps

- Replies are escaped as plain MarkdownV2 text, so model markdown (code blocks,
  bold) is not rendered yet.
- Streaming in groups relies on message edits, so it updates every 3s, not live.
