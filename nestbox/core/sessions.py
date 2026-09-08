from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# counters the engine reports cumulatively for the whole session
SPENT_KEYS = ("cost_usd", "input_tokens", "output_tokens", "cache_read", "cache_write")


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    agent: str
    updated_at: float
    title: str | None = None
    spent: dict[str, float] = field(default_factory=dict)


class SessionStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._records: dict[str, SessionRecord] = {}
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
            self._records = {
                key: SessionRecord(**value) for key, value in raw.items()
            }
        self._loaded = True

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: asdict(value) for key, value in self._records.items()}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    @staticmethod
    def key(chat_id: int, thread_id: int | None) -> str:
        return f"{chat_id}:{thread_id or 0}"

    async def get(self, key: str) -> SessionRecord | None:
        async with self._lock:
            await self._ensure_loaded()
            return self._records.get(key)

    async def set(self, key: str, session_id: str, agent: str, title: str | None = None) -> None:
        async with self._lock:
            await self._ensure_loaded()
            existing = self._records.get(key)
            fresh = existing is None or existing.session_id != session_id
            self._records[key] = SessionRecord(
                session_id=session_id,
                agent=agent,
                updated_at=time.time(),
                title=title or (existing.title if existing else None),
                spent={} if fresh else dict(existing.spent),
            )
            self._flush()

    async def take_spent(self, key: str, totals: dict[str, float]) -> dict[str, float]:
        """The engine reports session totals, but a run should show its own cost: return the difference.

        The session may have started over: then the total is below the stored one and is its own delta.
        """
        async with self._lock:
            await self._ensure_loaded()
            record = self._records.get(key)
            previous = dict(record.spent) if record else {}
            delta = {}
            for name in SPENT_KEYS:
                now = float(totals.get(name) or 0.0)
                was = float(previous.get(name) or 0.0)
                delta[name] = now - was if now >= was else now
            if record is not None:
                record.spent = {name: float(totals.get(name) or 0.0) for name in SPENT_KEYS}
                record.updated_at = time.time()
                self._flush()
            return delta

    async def drop(self, key: str) -> bool:
        async with self._lock:
            await self._ensure_loaded()
            removed = self._records.pop(key, None) is not None
            if removed:
                self._flush()
            return removed

    async def all(self) -> dict[str, SessionRecord]:
        async with self._lock:
            await self._ensure_loaded()
            return dict(self._records)
