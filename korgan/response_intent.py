from __future__ import annotations

import re

_RESPONSE_PATTERNS = (
    r"\bотзыв\w*\b.{0,40}\bиск\w*\b",
    r"\bотзыв\w*\b.{0,40}\bисков\w*\b",
    r"\bвозражен\w*\b.{0,40}\bиск\w*\b",
    r"\bответ\w*\b.{0,30}\bна\s+иск\w*\b",
    r"\bталап\w*\b.{0,40}\bпікір\w*\b",
    r"\bпікір\w*\b.{0,40}\bталап\w*\b",
    r"\bталап\s+қою\s+арыз\w*\b.{0,60}\bқарсылық\w*\b",
    r"\bқарсылық\w*\b.{0,60}\bталап\s+қою\s+арыз\w*\b",
)


def is_response_to_claim_request(text: str | None) -> bool:
    value = " ".join((text or "").split()).lower()
    return bool(value) and any(re.search(pattern, value, flags=re.IGNORECASE | re.DOTALL) for pattern in _RESPONSE_PATTERNS)
