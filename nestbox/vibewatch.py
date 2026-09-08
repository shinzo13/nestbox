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
import threading
import time
import urllib.request

NUDGE = str(Path(__file__).resolve().parents[1] / "bin" / "nudge")
RETRY_DELAY = 15.0
DEBOUNCE = 300.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vibewatch")


def wake(messages: list[tuple[str, str]], room: str) -> None:
    joined = "\n\n---\n\n".join(f"from {nick}:\n{body}" for nick, body in messages)
    plural = "messages" if len(messages) > 1 else "message"
    text = (
        f"{plural} in vibegram (room {room}):\n\n{joined}\n\n"
        "how to answer: see the vibegram skill. "
        "silence is a complete answer."
    )
    subprocess.run([NUDGE, text], check=False)


class Mailbox:
    """Collects messages and wakes once, after the other side goes quiet.

    The pause is not politeness: while it runs, the conversation may finish on
    its own, and then there is nobody to wake and no reason to.
    """

    def __init__(self, delay: float, room: str) -> None:
        self._delay = delay
        self._room = room
        self._pending: list[tuple[str, str]] = []
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def add(self, nick: str, body: str) -> None:
        with self._lock:
            self._pending.append((nick, body))
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            messages, self._pending = self._pending, []
            self._timer = None
        if messages:
            log.info("waking the orchestrator: %d messages", len(messages))
            wake(messages, self._room)


def stream(url: str, me: str, room: str, me_id: str, mailbox: "Mailbox") -> None:
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
            mailbox.add(nick, body.strip())


def main() -> None:
    parser = argparse.ArgumentParser(prog="vibewatch")
    parser.add_argument("--hub", required=True, help="hub base url")
    parser.add_argument("--view", required=True, help="room view token")
    parser.add_argument("--room", required=True, help="room name, only for the wake text")
    parser.add_argument("--me", required=True, help="own nick")
    parser.add_argument("--me-id", default="", help="own agent id: nicks in events can be stale")
    parser.add_argument("--debounce", type=float, default=DEBOUNCE, help="seconds of quiet to wait for")
    args = parser.parse_args()

    url = f"{args.hub}/api/stream?view={args.view}"
    mailbox = Mailbox(args.debounce, args.room)
    while True:
        try:
            log.info("listening to %s", args.room)
            stream(url, args.me, args.room, args.me_id, mailbox)
        except Exception as exc:  # noqa: BLE001 - the stream drops, that is normal
            log.warning("stream dropped: %s", exc)
        time.sleep(RETRY_DELAY)


if __name__ == "__main__":
    main()
