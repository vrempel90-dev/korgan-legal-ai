from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from korgan.article_authority import AUTHORITY_NOTE_PREFIX, enforce_article_authority
from korgan.claim_corpus_health import enforce_claim_corpus_health
from korgan.claim_filing_accuracy import apply_claim_filing_accuracy
from korgan.claim_money_ledger import build_claim_money_ledger
from korgan.claim_release_invariants import enforce_claim_release_invariants
from korgan.consumer_qualification import ConsumerStatus, consumer_status
from korgan.legal_calc import format_kzt
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

_DATA_PATH = Path(__file__).resolve().parent / "data" / "court_registry.json"

_VERIFIED_LINE_RE = re.compile(
    r"^(?P<statement>.*?)\s*\[основание:\s*(?P<article>.*?);\s*текст\s+нормы:",
    re.IGNORECASE | re.DOTALL,
)
_COURT_SOURCE_RE = re.compile(r"\[основание:\s*официальный перечень судов;\s*источник:", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"(?:статья|статьи|ст\.)\s*\d+(?:-\d+)?", re.IGNORECASE)
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
_CONSUMER_VENUE_RE = re.compile(r"стать(?:я|и)\s*30\b.*потребител|потребител.*стать(?:я|и)\s*30\b", re.IGNORECASE | re.DOTALL)
_GENERAL_VENUE_RE = re.compile(r"стать(?:я|и)\s*29\b", re.IGNORECASE)
_CLAIM_PRICE_NOTE_PREFIX = "Цена иска требует проверки: "
_NONPROPERTY_PRICE_LABEL = "не определяется (требование неимущественного характера)"

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
    verified = _verified_text(research)
    city = "Алматы" if "алмат" in (case_context or "").lower() else ""
    if not city:
        return

    entry: dict[str, str] | None = None
    # Часть 9 статьи 30 ГПК РК даёт выбор подсудности потребителю. Подтверждение
    # самой нормы не делает истца потребителем: пока цель приобретения не
    # установлена, иск идёт по общему правилу, иначе суд вернёт его по подсудности.
    consumer_venue = _CONSUMER_VENUE_RE.search(verified) and (
        consumer_status(case_context, draft) is ConsumerStatus.ESTABLISHED
    )
    if consumer_venue:
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


def _recalculate_price(draft: ClaimDraft) -> None:
    """Set one authoritative claim price from independent monetary remedies.

    State duty and court costs are excluded by the ledger. A prayer line that
    contains both components and an explicit total contributes only that total.
    If a multi-amount prayer is ambiguous, the existing price is preserved and
    the draft cannot silently become VERIFIED until the calculation is checked.
    """
    draft.verification_notes = [
        note for note in draft.verification_notes
        if not str(note).startswith(_CLAIM_PRICE_NOTE_PREFIX)
    ]

    ledger = build_claim_money_ledger(list(draft.requests or []))
    if ledger.unresolved_requests:
        sample = ledger.unresolved_requests[0]
        if len(sample) > 180:
            sample = sample[:177].rstrip() + "..."
        draft.verification_notes.append(
            _CLAIM_PRICE_NOTE_PREFIX
            + "в просительной части есть денежное требование, которое нельзя однозначно включить в цену иска; "
            + f"не использовать автоматический расчет госпошлины до проверки строки «{sample}»."
        )
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        return

    if ledger.total > 0:
        draft.price_of_claim = format_kzt(ledger.total)
    elif ledger.nonproperty_money_components:
        # A money-denominated moral-damage request remains non-property for the
        # ordinary civil duty route. Displaying "Цена иска: 0 тенге" would imply
        # a zero-valued property claim and is professionally misleading.
        draft.price_of_claim = _NONPROPERTY_PRICE_LABEL


def apply_article_authority(draft: ClaimDraft) -> None:
    """Оставить в документе только подтверждённые номера статей.

    Проверка идёт по всему черновику, а не по разделу правового обоснования:
    номер статьи в фактической части утверждает право ровно так же, как в
    мотивировочной, и до сих пор там не проверялся никем. Снятая ссылка уходит
    юристу отдельным сообщением и не превращается в пометку внутри судебного
    текста.
    """
    report = enforce_article_authority(draft)
    draft.citation_authority = report.as_dict()
    if not report.lawyer_notes:
        return
    draft.status = VerificationStatus.NEEDS_VERIFICATION
    for note in report.lawyer_notes:
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)


def finalize_professional_claim(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
    *,
    language: str | None = None,
) -> None:
    """Apply non-model professional drafting invariants before final release checks."""
    _resolve_court(case_context, research, draft)
    _apply_verified_legal_basis(research, draft)
    apply_claim_filing_accuracy(case_context, research, draft)
    enforce_claim_corpus_health(research, draft)
    _sanitize_relief(case_context, research, draft)
    enforce_claim_release_invariants(case_context, draft, language=language)
    apply_article_authority(draft)
    _recalculate_price(draft)

    draft.verification_notes = [
        note for note in draft.verification_notes
        if not str(note).startswith(("KORGAN QUALITY", "SENIOR_PREFLIGHT_SCORE:"))
    ]
    if not draft.verification_notes:
        draft.status = VerificationStatus.VERIFIED
