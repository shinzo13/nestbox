from __future__ import annotations

MDV2_SPECIALS = r"_*[]()~`>#+-=|{}.!"
TELEGRAM_LIMIT = 4096


def escape_md(text: str) -> str:
    return "".join("\\" + ch if ch in MDV2_SPECIALS else ch for ch in text)


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return chunks


def human_duration(ms: int | None) -> str:
    if not ms:
        return ""
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}m{seconds:02d}s"
