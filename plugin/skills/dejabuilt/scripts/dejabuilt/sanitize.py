"""Make text written by strangers safe to print. Pure.

Descriptions, asset names and release tags come from repository owners. They can
contain terminal escape sequences, invisible direction marks, Markdown and text
written to look like instructions. Nothing here makes such text trustworthy; it
only stops it from breaking the output it is embedded in.
"""

from __future__ import annotations

import unicodedata

ELLIPSIS = "…"

_MARKDOWN_SPECIALS = "\\`*_[]()|#~"


def clean(text: object, limit: int = 200) -> str:
    """One line of printable text, at most `limit` characters."""
    if not isinstance(text, str):
        return ""
    visible = "".join(" " if _is_space(ch) else ch for ch in text if _is_visible(ch))
    collapsed = " ".join(visible.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 1, 0)].rstrip() + ELLIPSIS


def markdown(text: str) -> str:
    """Escape text so it renders literally inside a Markdown table cell."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "".join("\\" + ch if ch in _MARKDOWN_SPECIALS else ch for ch in escaped)


def _is_space(ch: str) -> bool:
    return ch.isspace()


def _is_visible(ch: str) -> bool:
    """Drop control, format, surrogate, private-use and unassigned characters."""
    return ch.isspace() or not unicodedata.category(ch).startswith("C")
