from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

MODES = ("ask", "work")


@dataclass(slots=True)
class Branch:
    thread_id: int
    agent: str
    title: str
    cwd: str | None = None
    mode: str = "ask"
    icon: str | None = None
    is_main: bool = False
    extra: dict = field(default_factory=dict)


class BranchStore:
    """A branch is a subagent, one to one. Only the orchestrator creates branches."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._branches: dict[int, Branch] = {}
        self._mtime: float | None = None

    async def _ensure_loaded(self) -> None:
        """The file can be rewritten from outside (the orchestrator creating a branch), so watch its mtime."""
        if not self._path.exists():
            return
        mtime = self._path.stat().st_mtime
        if mtime == self._mtime:
            return
        raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
        self._branches = {int(key): Branch(**value) for key, value in raw.items()}
        self._mtime = mtime

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {str(key): asdict(value) for key, value in self._branches.items()}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)
        self._mtime = self._path.stat().st_mtime

    async def get(self, thread_id: int | None) -> Branch | None:
        if thread_id is None:
            return None
        async with self._lock:
            await self._ensure_loaded()
            return self._branches.get(thread_id)

    async def main(self) -> Branch | None:
        async with self._lock:
            await self._ensure_loaded()
            return next((b for b in self._branches.values() if b.is_main), None)

    async def all(self) -> list[Branch]:
        async with self._lock:
            await self._ensure_loaded()
            return list(self._branches.values())

    async def add(self, branch: Branch) -> Branch:
        async with self._lock:
            await self._ensure_loaded()
            self._branches[branch.thread_id] = branch
            self._flush()
            return branch

    async def update(self, thread_id: int, **fields) -> Branch | None:
        async with self._lock:
            await self._ensure_loaded()
            branch = self._branches.get(thread_id)
            if branch is None:
                return None
            for key, value in fields.items():
                setattr(branch, key, value)
            self._flush()
            return branch

    async def remove(self, thread_id: int) -> bool:
        async with self._lock:
            await self._ensure_loaded()
            removed = self._branches.pop(thread_id, None) is not None
            if removed:
                self._flush()
            return removed
