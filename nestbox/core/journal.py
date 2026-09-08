"""The orchestrator's journal: what it writes for itself and reads the next day.

Memory keeps facts; the journal keeps the thread. The prompt gets not the journal
but summary.md, a digest the orchestrator rewrites for itself every night, plus
the entries the digest has not reached yet. Raw day files stay the source: the
summary can always be rebuilt from them.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("NESTBOX_TZ", "UTC"))
SUMMARY_NAME = "summary.md"
STATE_NAME = "summary.state.json"
SUMMARY_LIMIT = 8000
TAIL_LIMIT = 4000
DAY_FILE = re.compile(r"\d{4}-\d{2}-\d{2}\.md")

log = logging.getLogger(__name__)


class Journal:
    def __init__(self, folder: Path) -> None:
        self._folder = folder

    @property
    def folder(self) -> Path:
        return self._folder

    @property
    def summary_path(self) -> Path:
        return self._folder / SUMMARY_NAME

    @property
    def state_path(self) -> Path:
        """What exactly the summary has folded: each day's name and its size at folding time."""
        return self._folder / STATE_NAME

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

    def days(self) -> list[Path]:
        if not self._folder.exists():
            return []
        return sorted(p for p in self._folder.glob("*.md") if DAY_FILE.fullmatch(p.name))

    def read_summary(self) -> str:
        path = self.summary_path
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def write_summary(self, text: str, folded: list[Path] | None = None) -> Path:
        path = self.summary_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text.strip() + "\n", encoding="utf-8")
        tmp.replace(path)
        days = self.days() if folded is None else folded
        state = {day.name: day.stat().st_size for day in days}
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)
        return path

    def pending(self) -> list[Path]:
        """Days the summary has not seen. Size, not mtime: clocks lie, length does not.

        A day appended to after folding becomes pending again, which is the point.
        """
        if not self.summary_path.exists():
            return self.days()
        folded: dict[str, int] = {}
        if self.state_path.exists():
            try:
                folded = json.loads(self.state_path.read_text(encoding="utf-8"))
            except ValueError as exc:
                log.warning("summary state unreadable (%s), treating all days as pending", exc)
        return [day for day in self.days() if folded.get(day.name) != day.stat().st_size]

    def recent(self, summary_limit: int = SUMMARY_LIMIT, tail_limit: int = TAIL_LIMIT) -> str:
        """For the prompt: the whole summary plus the tail of pending days.

        A cut is always announced: a silently lost piece of the journal reads as
        "this never happened", the worst kind of error in a note to oneself.
        """
        parts: list[str] = []
        summary = self.read_summary()
        if len(summary) > summary_limit:
            dropped = len(summary) - summary_limit
            log.warning("summary.md is %d chars over budget, truncating", dropped)
            summary = (
                f"[summary over budget, {dropped} chars cut from the end, "
                f"full text in {self.summary_path}]\n" + summary[:summary_limit]
            )
        if summary:
            # the folding date travels with the summary and is never cut: if the
            # nightly run did not happen, it shows on first read, not a week later
            when = datetime.fromtimestamp(self.summary_path.stat().st_mtime, TZ)
            parts.append(f"[summary of {when:%Y-%m-%d %H:%M}]\n\n{summary}")

        pending = self.pending()
        if pending:
            text = "\n\n".join(p.read_text(encoding="utf-8").strip() for p in pending)
            if len(text) > tail_limit:
                dropped = len(text) - tail_limit
                text = (
                    f"[{dropped} chars cut from the start, full text in {self._folder}]\n"
                    + text[-tail_limit:]
                )
            parts.append("Entries not yet folded into the summary:\n\n" + text)
        return "\n\n---\n\n".join(parts).strip()
