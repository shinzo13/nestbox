"""Vibegram room subscription: someone else's message wakes the orchestrator.

The hub serves SSE for a view token, so it is enough to hold the stream and drop
an event into the bot's queue for every message that is not ours. From there it
is an ordinary run.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import time
import urllib.request

NUDGE = str(Path(__file__).resolve().parents[1] / "bin" / "nudge")
RETRY_DELAY = 15.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vibewatch")


def wake(nick: str, body: str, room: str) -> None:
    text = (
        f"message in vibegram from {nick} (room {room}):\n\n{body}\n\n"
        "read it, decide whether it needs an answer, and if so answer yourself "
        "with the vibegram client. "
        "tell the owner briefly what it was about."
    )
    subprocess.run([NUDGE, text], check=False)


def stream(url: str, me: str, room: str, me_id: str = "") -> None:
    # without an explicit Accept the hub answers 403: it expects a stream subscriber
    request = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(request, timeout=None) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if event.get("kind") != "message":
                continue
            nick = event.get("nick") or "?"
            if nick == me or (me_id and event.get("agentId") == me_id):
                continue
            body = (event.get("payload") or {}).get("body") or ""
            if not body.strip():
                continue
            log.info("message from %s", nick)
            wake(nick, body.strip(), room)


def main() -> None:
    parser = argparse.ArgumentParser(prog="vibewatch")
    parser.add_argument("--hub", required=True, help="hub base url")
    parser.add_argument("--view", required=True, help="room view token")
    parser.add_argument("--room", required=True, help="room name, only for the wake text")
    parser.add_argument("--me", required=True, help="own nick")
    parser.add_argument("--me-id", default="", help="own agent id: nicks in events can be stale")
    args = parser.parse_args()

    url = f"{args.hub}/api/stream?view={args.view}"
    while True:
        try:
            log.info("listening to %s", args.room)
            stream(url, args.me, args.room, args.me_id)
        except Exception as exc:  # noqa: BLE001 - the stream drops, that is normal
            log.warning("stream dropped: %s", exc)
        time.sleep(RETRY_DELAY)


if __name__ == "__main__":
    main()
