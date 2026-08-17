from __future__ import annotations

import re


_RESPONSE_PATTERNS = (
    r"\bотзыв\w*\b.{0,40}\bиск\w*\b",
    r"\bотзыв\w*\b.{0,40}\bисков\w*\b",
    r"\bвозражен\w*\b.{0,40}\bиск\w*\b",
    r"\bответ\w*\b.{0,30}\bна\s+иск\w*\b",
    r"талап\s+қою\s+арыз\w*.{0,50}(?:пікір\w*|қарсылық\w*)",
    r"(?:пікір\w*|қарсылық\w*).{0,50}талап\s+қою\s+арыз\w*",
    r"талап-арыз\w*.{0,50}(?:пікір\w*|қарсылық\w*)",
)
_ADVICE = re.compile(r"(?i)(?:^\s*(?:как|қалай)\b|\bқалай\b.{0,100}(?:дайында|жаса|құрастыр|әзірле))")


def is_response_to_claim_request(text: str | None) -> bool:
    value = " ".join((text or "").split()).lower()
    if not value or _ADVICE.search(value):
        return False
    return any(re.search(pattern, value, flags=re.IGNORECASE | re.DOTALL) for pattern in _RESPONSE_PATTERNS)
