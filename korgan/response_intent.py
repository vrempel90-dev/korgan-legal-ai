from __future__ import annotations

import re


_RESPONSE_PATTERNS = (
    r"\bотзыв\w*\b.{0,40}\bиск\w*\b",
    r"\bотзыв\w*\b.{0,40}\bисков\w*\b",
    r"\bвозражен\w*\b.{0,40}\bиск\w*\b",
    r"\bответ\w*\b.{0,30}\bна\s+иск\w*\b",
)


def is_response_to_claim_request(text: str | None) -> bool:
    """Return True only for a request to prepare a procedural response to a claim.

    Plain UI feedback such as «оставить отзыв» is intentionally not matched: an
    иск/исковое заявление must be present in the same request.
    """
    value = " ".join((text or "").split()).lower()
    return bool(value) and any(re.search(pattern, value, flags=re.IGNORECASE | re.DOTALL) for pattern in _RESPONSE_PATTERNS)
