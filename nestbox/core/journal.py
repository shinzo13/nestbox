"""The orchestrator's journal: what it writes for itself and reads the next day.

Memory keeps facts; the journal keeps the thread: what happened, what it understood,
what it wants. Entries are mixed into the system prompt at startup, so
a new session does not start from a blank page.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("NESTBOX_TZ", "UTC"))
RECENT_DAYS = 5
RECENT_LIMIT = 6000


class Journal:
    def __init__(self, folder: Path) -> None:
        self._folder = folder

    def path_for(self, day: datetime | None = None) -> Path:
        day = day or datetime.now(TZ)
        return self._folder / f"{day:%Y-%m-%d}.md"

    def append(self, text: str) -> Path:
        path = self.path_for()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(TZ).strftime("%H:%M")
        head = "" if path.exists() else f"# {datetime.now(TZ):%Y-%m-%d}\n\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{head}## {stamp}\n\n{text.strip()}\n\n")
        return path

    def recent(self, days: int = RECENT_DAYS, limit: int = RECENT_LIMIT) -> str:
        if not self._folder.exists():
            return ""
        files = sorted(self._folder.glob("*.md"))[-days:]
        text = "\n\n".join(path.read_text(encoding="utf-8").strip() for path in files)
        if len(text) > limit:
            text = "…\n" + text[-limit:]
        return text.strip()
