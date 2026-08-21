from __future__ import annotations

import re

from korgan.document_category_router import preferred_document_category

_RESPONSE_OBJECT = (
    r"(?:отзыв\w*\s+на\s+(?:исков\w*\s+заявлен\w*|иск\w*)|"
    r"возражен\w*\s+на\s+(?:исков\w*\s+заявлен\w*|иск\w*)|"
    r"ответ\w*\s+на\s+(?:исков\w*\s+заявлен\w*|иск\w*))"
)
_DIRECT_RESPONSE_REQUEST = re.compile(
    rf"(?:"
    rf"\b(?:(?:мне|нам)\s+)?(?:нужен|нужна|нужно|нужны|хочу|прошу)\s+(?:проект\s+)?{_RESPONSE_OBJECT}\b|"
    rf"^\s*{_RESPONSE_OBJECT}\s*$"
    rf")",
    re.IGNORECASE,
)


def is_response_to_claim_request(text: str | None) -> bool:
    """True only for an actual request to prepare a response to a court claim."""
    value = " ".join((text or "").split())
    if not value:
        return False

    explicit_category = preferred_document_category(value)
    if explicit_category is not None:
        return explicit_category == "response"

    return bool(_DIRECT_RESPONSE_REQUEST.search(value))
