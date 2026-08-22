"""Assemble Telegram captions without cutting words in half.

`caption[:1000]` is the same class of defect as a truncated model response: it
ends the text wherever the budget runs out, mid-word, and the user reads the
remains as a broken document. Captions are built here instead, so a list that
does not fit loses whole items and says so.
"""

from __future__ import annotations

TELEGRAM_CAPTION_LIMIT = 1024
_ELLIPSIS = "…"


def bullets(items: list[str]) -> str:
    return "\n".join(f"• {item}" for item in items if str(item).strip())


def fit_caption(text: str, *, limit: int = TELEGRAM_CAPTION_LIMIT) -> str:
    """Trim ``text`` to ``limit`` on a whole-line, then whole-word boundary."""
    if len(text) <= limit:
        return text

    lines = text.split("\n")
    kept: list[str] = []
    used = 0
    for line in lines:
        extra = len(line) + (1 if kept else 0)
        if used + extra > limit - len(_ELLIPSIS):
            break
        kept.append(line)
        used += extra

    if kept:
        return "\n".join(kept) + _ELLIPSIS

    # A single line longer than the whole budget: cut on a word boundary.
    head = text[: limit - len(_ELLIPSIS)]
    boundary = head.rfind(" ")
    if boundary > 0:
        head = head[:boundary]
    return head.rstrip(" ,;:") + _ELLIPSIS
