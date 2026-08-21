"""Small versioned registry of official KORGAN legal-source hints.

This module does NOT make a provision VERIFIED by itself.  It only preserves
article references already mentioned during a consultation so the next legal
research pass can search for them again.  Final legal assertions must still
survive KORGAN's source-bound Adilet web-search verification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

CHECKED_ON = date(2026, 8, 16)

GK_GENERAL = "https://adilet.zan.kz/rus/docs/K940001000_/compare"
GK_SPECIAL = "https://adilet.zan.kz/rus/docs/K990000409_"
GPK = "https://adilet.zan.kz/rus/docs/K1500000377"


@dataclass(frozen=True, slots=True)
class ProvisionHint:
    code: str
    article: str
    source_url: str
    checked_on: date = CHECKED_ON


PROVISION_HINTS: dict[str, ProvisionHint] = {
    "ст. 353 ГК": ProvisionHint("ГК", "353", GK_GENERAL),
    "ст. 715 ГК": ProvisionHint("ГК", "715", GK_SPECIAL),
    "ст. 716 ГК": ProvisionHint("ГК", "716", GK_SPECIAL),
    "ст. 717 ГК": ProvisionHint("ГК", "717", GK_SPECIAL),
    "ст. 722 ГК": ProvisionHint("ГК", "722", GK_SPECIAL),
    "ст. 29 ГПК": ProvisionHint("ГПК", "29", GPK),
    "ст. 148 ГПК": ProvisionHint("ГПК", "148", GPK),
    "ст. 149 ГПК": ProvisionHint("ГПК", "149", GPK),
}

# Handles common singular citation forms.  The returned strings are search hints
# only and must never be inserted into VERIFIED without the normal web-search
# source binding.
_ARTICLE_PATTERN = re.compile(
    r"(?:стат(?:ья|ьи|ье|ьей|ью)|ст\.)\s*(\d+(?:-\d+)?)"
    r"[^.;:\n]{0,45}?(ГК|ГПК|НК|УК|АППК|КоАП)",
    re.IGNORECASE,
)


def extract_cited_articles(text: str) -> list[str]:
    """Extract article references from a consultation answer for later research."""
    seen: list[str] = []
    for match in _ARTICLE_PATTERN.finditer(text or ""):
        number = match.group(1)
        code = match.group(2).upper()
        citation = f"ст. {number} {code}"
        if citation not in seen:
            seen.append(citation)
    return seen
