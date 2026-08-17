"""Fail-closed guard for known Kazakhstan-law supersessions.

This module is deliberately additive: it does not decide substantive law and it
never promotes a source to VERIFIED.  It only prevents a small, explicit set of
known superseded Adilet documents from being used as ordinary current-law
sources after their replacement date.

Transitional provisions are accepted only when they are explicitly enumerated.
Unknown acts are left to KORGAN's existing source-bound verification path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class SupersessionRule:
    old_id: str
    replacement_id: str
    cutoff: date
    transitional_until: date | None = None
    transitional_articles: frozenset[str] = frozenset()
    transitional_article_parts: tuple[tuple[str, str], ...] = ()


# The dates/IDs below are intentionally explicit rather than inferred from titles.
# They are maintained from the official Adilet text/history of the acts.
SUPERSESSIONS: dict[str, SupersessionRule] = {
    # Constitution adopted 15.03.2026; Art. 94: effective 01.07.2026 with the
    # simultaneous termination of the previously adopted Constitution.
    "K950001000_": SupersessionRule(
        old_id="K950001000_",
        replacement_id="K2600000000",
        cutoff=date(2026, 7, 1),
    ),
    # The 2015 civil-service law was repealed by Law No. 290-VIII from 01.07.2026.
    "Z1500000416": SupersessionRule(
        old_id="Z1500000416",
        replacement_id="Z2600000290",
        cutoff=date(2026, 7, 1),
    ),
    # The 1995 banking law is no longer the general current banking act.  By
    # 01.07.2026 only Arts. 40-1..40-4 and Art. 50(7-2) remain until 01.01.2027.
    # KORGAN may use those exceptions only when the exact article/part is named.
    "Z950002444_": SupersessionRule(
        old_id="Z950002444_",
        replacement_id="Z2600000258",
        cutoff=date(2026, 7, 1),
        transitional_until=date(2027, 1, 1),
        transitional_articles=frozenset({"40-1", "40-2", "40-3", "40-4"}),
        transitional_article_parts=(("50", "7-2"),),
    ),
    # The 2017 Tax Code must not be used as the ordinary current Tax Code after
    # the 2025 Code entered into force.  KORGAN's existing research prompt also
    # independently blacklists this legacy ID for current state-duty work.
    "K1700000120": SupersessionRule(
        old_id="K1700000120",
        replacement_id="K2500000214",
        cutoff=date(2026, 1, 1),
    ),
}

_DOC_ID_RE = re.compile(r"^[A-ZА-ЯЁ]\d+[A-ZА-ЯЁ0-9_-]*$", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.|бап(?:тың|қа|та|ы)?|бабы)\s*(\d+(?:-\d+)?)")


def adilet_document_id(url: str) -> str:
    """Return the /docs/<ID> component for an Adilet URL, else an empty string."""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if host not in {"adilet.zan.kz", "www.adilet.zan.kz"}:
        return ""
    pieces = [piece for piece in parsed.path.split("/") if piece]
    try:
        index = pieces.index("docs")
    except ValueError:
        return ""
    if index + 1 >= len(pieces):
        return ""
    value = pieces[index + 1]
    return value if _DOC_ID_RE.match(value) else ""


def article_number(label: str) -> str:
    match = _ARTICLE_RE.search(str(label or ""))
    return match.group(1) if match else ""


def replacement_for(doc_id_or_url: str, *, on_date: date | None = None) -> str | None:
    value = str(doc_id_or_url or "")
    doc_id = adilet_document_id(value) or value
    rule = SUPERSESSIONS.get(doc_id)
    today = on_date or date.today()
    if rule is None or today < rule.cutoff:
        return None
    return rule.replacement_id


def is_current_source(
    url: str,
    *,
    article_label: str = "",
    on_date: date | None = None,
) -> bool:
    """Whether a known Adilet source can be used as current law on ``on_date``.

    Unknown/ordinary current Adilet IDs are not rejected here; they still must
    pass the existing KORGAN source-bound and citation checks.  Known superseded
    IDs fail closed after their cutoff, except for explicitly listed transition
    provisions.
    """
    doc_id = adilet_document_id(url)
    if not doc_id:
        return True
    rule = SUPERSESSIONS.get(doc_id)
    if rule is None:
        return True

    today = on_date or date.today()
    if today < rule.cutoff:
        return True

    if rule.transitional_until is None or today >= rule.transitional_until:
        return False

    number = article_number(article_label)
    if number in rule.transitional_articles:
        return True
    for article, required_part in rule.transitional_article_parts:
        if number == article and required_part in str(article_label or ""):
            return True
    return False


def current_source_defect(url: str, *, article_label: str = "", on_date: date | None = None) -> str | None:
    if is_current_source(url, article_label=article_label, on_date=on_date):
        return None
    doc_id = adilet_document_id(url)
    replacement = replacement_for(doc_id, on_date=on_date)
    if replacement:
        return f"источник {doc_id} не является текущей общей редакцией; проверь {replacement}"
    return f"источник {doc_id or url} не является текущей редакцией"
