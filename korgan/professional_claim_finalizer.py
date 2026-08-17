from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from korgan.legal_calc import format_kzt
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

_DATA_PATH = Path(__file__).resolve().parent / "data" / "court_registry.json"

_VERIFIED_LINE_RE = re.compile(
    r"^(?P<statement>.*?)\s*\[основание:\s*(?P<article>.*?);\s*текст\s+нормы:",
    re.IGNORECASE | re.DOTALL,
)
_COURT_SOURCE_RE = re.compile(r"\[основание:\s*официальный перечень судов;\s*источник:", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"(?:статья|статьи|ст\.)\s*\d+(?:-\d+)?", re.IGNORECASE)
_MONEY_RE = re.compile(r"(?<!\d)(\d[\d\s\u00a0]*(?:[.,]\d{1,2})?)\s*(?:тенге|тг\b|₸)", re.IGNORECASE)
_MORAL_RE = re.compile(r"моральн\w*\s+вред|нравственн\w*\s+страдан|моральн\w*\s+страдан", re.IGNORECASE)
_SUBJECTIVE_RE = re.compile(
    r"переживан\w*|стресс\w*|нервн\w*|нравственн\w*\s+страдан\w*|"
    r"моральн\w*\s+страдан\w*|физическ\w*\s+страдан\w*|"
    r"бессонниц\w*|ухудшен\w*\s+(?:здоров|самочувств)|эмоциональн\w*\s+состояни\w*",
    re.IGNORECASE,
)
_PROCESS_MOTION_RE = re.compile(
    r"^(?:вызвать|допросить|истребовать|приобщить|назначить\s+экспертиз|обеспечить\s+иск)",
    re.IGNORECASE,
)
_TERMINATION_RE = re.compile(r"расторг|прекращен|прекратить\s+договор|признать\s+договор\s+прекращ", re.IGNORECASE)
_STATE_DUTY_RE = re.compile(r"пошлин", re.IGNORECASE)
_COST_RE = re.compile(r"судебн\w*\s+расход|расход\w*\s+по\s+оплат", re.IGNORECASE)
_ALTERNATIVE_RE = re.compile(r"альтернативн", re.IGNORECASE)
_CONSUMER_VENUE_RE = re.compile(r"стать(?:я|и)\s*30\b.*потребител|потребител.*стать(?:я|и)\s*30\b", re.IGNORECASE | re.DOTALL)
_GENERAL_VENUE_RE = re.compile(r"стать(?:я|и)\s*29\b", re.IGNORECASE)

# A model may reason internally in a long request item.  A court prayer must not
# contain that scratch structure: only the operative remedy belongs under
# «ПРОШУ СУД».  This directly prevents strings such as
# «Правовое основание: пункт 2 Республики Казахстан» from reaching Word.
_PRAYER_META_RE = re.compile(
    r"(?i)\s+(?:Фактические\s+основания|Правовое\s+основание|Юридическое\s+последствие|"
    r"Нақты\s+негіздер|Құқықтық\s+негіз|Құқықтық\s+салдар)\s*:"
)
_BROKEN_PRAYER_PREFIX_RE = re.compile(
    r"(?i)^\s*На\s+основании\s+(?:(?:пункт\w*|стать\w*)\s*\d+(?:-\d+)?\s+)?Республики\s+Казахстан\s*[,;:]?\s*"
)
_INTERNAL_LEGAL_TEXT_RE = re.compile(
    r"(?i)(?:\[\s*ТРЕБУЕТ\s+ПРОВЕРКИ\s*:|NEEDS_VERIFICATION|KORGAN\s+QA\s+STATUS|"
    r"source-bound|содержание\s+нормы\s+не\s+воспроизводится\s+до\s+сверки|"
    r"подлежит\s+сверке\s+по\s+официальному\s+источнику)"
)

_DISTRICTS = {
    "алатаус": "Алатауский",
    "алмалин": "Алмалинский",
    "ауэзов": "Ауэзовский",
    "бостандык": "Бостандыкский",
    "жетысу": "Жетысуский",
    "медеу": "Медеуский",
    "наурызбай": "Наурызбайский",
    "турксиб": "Турксибский",
}


@lru_cache(maxsize=1)
def _registry() -> list[dict[str, str]]:
    try:
        payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [dict(item) for item in payload.get("entries", []) if isinstance(item, dict)]


def _party_text(values: list[str]) -> str:
    return " ".join(str(value or "") for value in values)


def _district_from_text(text: str) -> str:
    lowered = (text or "").lower().replace("ё", "е")
    for stem, canonical in _DISTRICTS.items():
        if stem in lowered:
            return canonical
    return ""


def _court_for(city: str, district: str) -> dict[str, str] | None:
    if not city or not district:
        return None
    for item in _registry():
        if item.get("city", "").lower() == city.lower() and item.get("district", "").lower() == district.lower():
            return item
    return None


def _verified_text(research: LegalResearch) -> str:
    return "\n".join(research.verified_claims)


def _resolve_court(case_context: str, research: LegalResearch, draft: ClaimDraft) -> None:
    """Resolve a court only from verified venue law + versioned official court directory.

    Consumer cases prefer the plaintiff's residence when that venue is source-bound
    verified because it is expressly a plaintiff choice and usually avoids forcing a
    consumer to litigate at the business location. If that rule is not verified, the
    ordinary defendant-location path is used only when Article 29 is source-bound.
    """
    verified = _verified_text(research)
    city = "Алматы" if "алмат" in (case_context or "").lower() else ""
    if not city:
        return

    entry: dict[str, str] | None = None
    if _CONSUMER_VENUE_RE.search(verified):
        entry = _court_for(city, _district_from_text(_party_text(draft.claimant)))
    elif _GENERAL_VENUE_RE.search(verified):
        entry = _court_for(city, _district_from_text(_party_text(draft.defendant)))

    if not entry:
        return

    court = str(entry.get("court", "")).strip()
    if not court:
        return
    draft.court = court
    note = f"VERIFIED_COURT: {court}"
    if note not in research.notes:
        research.notes.append(note)
    source = str(entry.get("source_url", "")).strip()
    if source and source not in research.source_urls:
        research.source_urls.append(source)

    draft.verification_notes = [
        value for value in draft.verification_notes
        if not ("суд" in str(value).lower() and any(token in str(value).lower() for token in ("уточн", "не подтверж", "наименование")))
    ]


def _verified_legal_basis(research: LegalResearch) -> list[str]:
    result: list[str] = []
    for line in research.verified_claims:
        if _COURT_SOURCE_RE.search(line):
            continue
        match = _VERIFIED_LINE_RE.search(line)
        if not match:
            continue
        statement = " ".join(match.group("statement").split()).strip(" .")
        article = " ".join(match.group("article").split()).strip(" .")
        if not statement or not article or not _ARTICLE_RE.search(article):
            continue
        rendered = f"{statement}. Правовое основание: {article}."
        if rendered not in result:
            result.append(rendered)
    return result


def _apply_verified_legal_basis(research: LegalResearch, draft: ClaimDraft) -> None:
    basis = _verified_legal_basis(research)
    if basis:
        draft.legal_basis = basis


def _sanitize_filing_legal_basis(draft: ClaimDraft) -> None:
    """Internal verification prose may live in notes/logs, never in the pleading."""
    draft.legal_basis = [
        " ".join(str(item).split()).strip()
        for item in draft.legal_basis
        if str(item).strip() and not _INTERNAL_LEGAL_TEXT_RE.search(str(item))
    ]


def _clean_prayer_item(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    split = _PRAYER_META_RE.split(text, maxsplit=1)
    text = split[0].strip(" ;")
    text = _BROKEN_PRAYER_PREFIX_RE.sub("", text).strip(" ;")
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def sanitize_prayer_requests(draft: ClaimDraft) -> None:
    """Keep only executable court remedies under the prayer for relief."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in draft.requests:
        item = _clean_prayer_item(str(raw))
        key = re.sub(r"\W+", "", item.lower())
        if item and key and key not in seen:
            cleaned.append(item)
            seen.add(key)
    draft.requests = cleaned


def _moral_facts_supplied(case_context: str) -> bool:
    return bool(_SUBJECTIVE_RE.search(case_context or ""))


def _remedy_decisions(research: LegalResearch) -> list[str]:
    return [str(note) for note in research.notes if str(note).startswith("REMEDY:")]


def _termination_is_included(research: LegalResearch) -> bool:
    for note in _remedy_decisions(research):
        lowered = note.lower()
        if "include" in lowered and _TERMINATION_RE.search(lowered):
            return True
    return False


def _sanitize_relief(case_context: str, research: LegalResearch, draft: ClaimDraft) -> None:
    has_moral_facts = _moral_facts_supplied(case_context)

    if not has_moral_facts:
        draft.facts = [item for item in draft.facts if not (_MORAL_RE.search(item) or _SUBJECTIVE_RE.search(item))]
        draft.requests = [item for item in draft.requests if not _MORAL_RE.search(item)]
        draft.legal_basis = [item for item in draft.legal_basis if not _MORAL_RE.search(item)]
        draft.verification_notes = [item for item in draft.verification_notes if "моральн" not in str(item).lower()]
        draft.title = re.sub(
            r",?\s*(?:о\s+)?компенсаци\w*\s+моральн\w*\s+вред\w*",
            "",
            draft.title,
            flags=re.IGNORECASE,
        ).strip(" ,")

    draft.requests = [
        item for item in draft.requests
        if not (_PROCESS_MOTION_RE.search(item.strip()) and item.lower() not in (case_context or "").lower())
    ]

    if not _termination_is_included(research):
        draft.requests = [item for item in draft.requests if not _TERMINATION_RE.search(item)]


def _parse_amount(value: str) -> int:
    digits = re.sub(r"[\s\u00a0]", "", value).replace(",", ".")
    try:
        return round(float(digits))
    except ValueError:
        return 0


def _recalculate_price(draft: ClaimDraft) -> None:
    amounts: list[int] = []
    for request in draft.requests:
        if _STATE_DUTY_RE.search(request) or _COST_RE.search(request) or _ALTERNATIVE_RE.search(request):
            continue
        for match in _MONEY_RE.finditer(request):
            amount = _parse_amount(match.group(1))
            if amount > 0:
                amounts.append(amount)
    if amounts:
        draft.price_of_claim = format_kzt(sum(amounts))


def finalize_professional_claim(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
) -> None:
    """Apply non-model professional release invariants before scoring/export."""
    _resolve_court(case_context, research, draft)
    _apply_verified_legal_basis(research, draft)
    _sanitize_filing_legal_basis(draft)
    _sanitize_relief(case_context, research, draft)
    sanitize_prayer_requests(draft)
    _recalculate_price(draft)

    draft.verification_notes = [
        note for note in draft.verification_notes
        if not str(note).startswith(("KORGAN QUALITY", "SENIOR_PREFLIGHT_SCORE:"))
    ]
    if not draft.verification_notes:
        draft.status = VerificationStatus.VERIFIED
