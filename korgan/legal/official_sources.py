from __future__ import annotations

import re
from urllib.parse import ParseResult, urlparse

from korgan.legal.corpus import (
    ACT_CONSUMER,
    ACT_GK_GENERAL,
    ACT_GK_SPECIAL,
    ACT_GPK,
    ACT_LABOR,
    ACT_TAX_DUTY,
)

ADILET_HOSTS = {"adilet.zan.kz", "www.adilet.zan.kz"}
ZAN_HOSTS = {"zan.gov.kz", "www.zan.gov.kz"}

# Stable registry IDs in the Ministry of Justice electronic reference bank.
ZAN_DOCUMENT_IDS: dict[str, int] = {
    ACT_GK_GENERAL: 879,
    ACT_GK_SPECIAL: 3559,
    ACT_GPK: 95109,
    ACT_TAX_DUTY: 212543,
    ACT_CONSUMER: 52483,
    ACT_LABOR: 95666,
}

# Independent identity markers that must be present in the extracted official
# ZAN document before it is allowed to refresh a KORGAN act.
ZAN_IDENTITY_MARKERS: dict[str, tuple[str, ...]] = {
    ACT_GK_GENERAL: (
        "Гражданский кодекс Республики Казахстан",
        "27 декабря 1994",
        "268-XIII",
    ),
    ACT_GK_SPECIAL: (
        "Гражданский кодекс Республики Казахстан",
        "особенная часть",
        "1 июля 1999",
        "409",
    ),
    ACT_GPK: (
        "Гражданский процессуальный кодекс Республики Казахстан",
        "31 октября 2015",
        "377-V",
    ),
    ACT_TAX_DUTY: (
        "Налоговый кодекс Республики Казахстан",
        "18 июля 2025",
        "214-VIII",
    ),
    ACT_CONSUMER: (
        "О защите прав потребителей",
        "4 мая 2010",
        "274-IV",
    ),
    ACT_LABOR: (
        "Трудовой кодекс Республики Казахстан",
        "23 ноября 2015",
        "414-V",
    ),
}

_ZAN_PDF_PATH_RE = re.compile(
    r"^/api/documents/(?P<document_id>\d+)/rus(?:/(?P<edition>\d{2}\.\d{2}\.\d{4}))?/download/pdf$"
)
_ZAN_IDS = frozenset(ZAN_DOCUMENT_IDS.values())


def _parsed_https(url: str) -> ParseResult | None:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    if port not in (None, 443):
        return None
    if parsed.query or parsed.fragment:
        return None
    return parsed


def is_allowed_adilet_url(url: str) -> bool:
    parsed = _parsed_https(url)
    return bool(
        parsed
        and (parsed.hostname or "").lower() in ADILET_HOSTS
        and parsed.path.startswith("/rus/")
    )


def zan_pdf_url(act_id: str) -> str:
    document_id = ZAN_DOCUMENT_IDS[act_id]
    return f"https://zan.gov.kz/api/documents/{document_id}/rus/download/pdf"


def zan_pdf_url_details(url: str) -> tuple[int, str] | None:
    parsed = _parsed_https(url)
    if not parsed or (parsed.hostname or "").lower() not in ZAN_HOSTS:
        return None
    match = _ZAN_PDF_PATH_RE.fullmatch(parsed.path)
    if match is None:
        return None
    return int(match.group("document_id")), (match.group("edition") or "")


def is_allowed_zan_pdf_url(url: str, *, act_id: str | None = None) -> bool:
    details = zan_pdf_url_details(url)
    if details is None:
        return False
    document_id, _ = details
    if act_id is None:
        return document_id in _ZAN_IDS
    return ZAN_DOCUMENT_IDS.get(act_id) == document_id


def official_source_kind(url: str) -> str | None:
    if is_allowed_adilet_url(url):
        return "adilet"
    if is_allowed_zan_pdf_url(url):
        return "zan"
    return None
