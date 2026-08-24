from __future__ import annotations

import re
from typing import Any

_PARTY_LABEL_RE = re.compile(
    r"(?i)^\s*(?:"
    r"кому|от|получатель|отправитель|адресат|истец|ответчик|заявитель|"
    r"алушы|жіберуші|талап\s+қоюшы|жауапкер"
    r")\s*:\s*"
)
_EDITORIAL_PREFIX_RE = re.compile(
    r"(?i)^\s*(?:сноска|ескерту)\s*[.:;-]"
)
_EDITORIAL_TAIL_RE = re.compile(
    r"(?is)\s+(?:сноска|ескерту)\s*[.:;-].*$"
)
_OPEN_FRAGMENT_RE = re.compile(
    r"(?i)\s*\(?\s*по\s+открытому\s+фрагменту\s*\)?"
)
_TECHNICAL_SOURCE_LINE_RE = re.compile(
    r"(?i)^\s*(?:источник|source)\s*:\s*https?://"
)


def strip_party_role_labels(value: str) -> str:
    """Remove renderer-owned party labels without changing the party data."""
    text = str(value or "").strip()
    previous = None
    while text and previous != text:
        previous = text
        text = _PARTY_LABEL_RE.sub("", text, count=1).strip()
    return text


def sanitize_client_legal_line(value: str) -> str:
    """Remove official-site editorial metadata, never the legal proposition itself."""
    text = " ".join(str(value or "").split()).strip()
    if not text or _EDITORIAL_PREFIX_RE.search(text) or _TECHNICAL_SOURCE_LINE_RE.search(text):
        return ""
    text = _EDITORIAL_TAIL_RE.sub("", text).strip()
    text = _OPEN_FRAGMENT_RE.sub("", text).strip()
    return text


def _clean_unique(values: list[str], cleaner) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = cleaner(str(raw or ""))
        if not value:
            continue
        key = re.sub(r"\W+", "", value.casefold())
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def sanitize_document_draft(draft: Any) -> None:
    """Apply client-facing sanitation without inventing or completing missing facts."""
    for attr in (
        "sender",
        "recipient",
        "claimant",
        "defendant",
        "plaintiff",
        "party_a",
        "party_b",
        "requisites_a",
        "requisites_b",
    ):
        values = getattr(draft, attr, None)
        if isinstance(values, list):
            setattr(draft, attr, _clean_unique([str(item) for item in values], strip_party_role_labels))

    legal_basis = getattr(draft, "legal_basis", None)
    if isinstance(legal_basis, list):
        draft.legal_basis = _clean_unique(
            [str(item) for item in legal_basis],
            sanitize_client_legal_line,
        )
