from __future__ import annotations

import re

from nestbox.bot.formatting import escape_md

FENCE_RE = re.compile(r"```([^\n`]*)\n?([\s\S]*?)```", re.MULTILINE)
INLINE_RE = re.compile(
    r"(`[^`\n]+`)"
    r"|(\*\*[^\n*]+\*\*|__[^\n_]+__)"
    r"|(\[[^\]\n]+\]\([^)\s]+\))"
)
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")


def _escape_code(text: str) -> str:
    return text.replace("\\", "\\\\").replace("`", "\\`")


def _render_inline(text: str) -> str:
    out: list[str] = []
    position = 0
    for match in INLINE_RE.finditer(text):
        out.append(escape_md(text[position : match.start()]))
        code, strong, link = match.group(1), match.group(2), match.group(3)
        if code:
            out.append(f"`{_escape_code(code[1:-1])}`")
        elif strong:
            out.append(f"*{escape_md(strong[2:-2])}*")
        elif link:
            label, url = LINK_RE.match(link).groups()
            out.append(f"[{escape_md(label)}]({url.replace(')', '%29')})")
        position = match.end()
    out.append(escape_md(text[position:]))
    return "".join(out)


def _render_block(text: str) -> str:
    lines: list[str] = []
    for line in text.split("\n"):
        heading = HEADING_RE.match(line)
        if heading:
            lines.append(f"*{escape_md(heading.group(2).strip())}*")
            continue
        bullet = BULLET_RE.match(line)
        if bullet:
            indent, body = bullet.groups()
            lines.append(f"{indent}• {_render_inline(body)}")
            continue
        lines.append(_render_inline(line))
    return "\n".join(lines)


def to_telegram_markdown(text: str) -> str:
    out: list[str] = []
    position = 0
    for match in FENCE_RE.finditer(text):
        out.append(_render_block(text[position : match.start()]))
        language = match.group(1).strip()
        body = _escape_code(match.group(2).rstrip("\n"))
        out.append(f"```{language}\n{body}\n```")
        position = match.end()
    out.append(_render_block(text[position:]))
    return "".join(out)
