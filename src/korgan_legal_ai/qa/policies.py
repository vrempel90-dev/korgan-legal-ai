from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from korgan_legal_ai.domain.models import (
    CalculationResult,
    DocumentType,
    DraftDocument,
    LockedCase,
    ProceduralReport,
    QAViolation,
    ResearchCitation,
    VerificationStatus,
)


ARTICLE_RE = re.compile(
    r"\bстат(?:ья|ьи|ье|ью|ей)\s+"
    r"(?P<article>\d+(?:-\d+)?)"
    r"(?:\s*,?\s*(?:част(?:ь|и)|ч\.)\s*(?P<part>\d+))?"
    r"(?:\s*,?\s*(?:пункт(?:а|е|у|ом)?|п\.)\s*(?P<point>\d+(?:-\d+)?))?",
    re.IGNORECASE,
)
CITATION_LOCATOR_RE = re.compile(
    r"^\s*(?P<article>\d+(?:-\d+)?)"
    r"(?:\s*,\s*часть\s+(?P<part>\d+))?"
    r"(?:\s*,\s*пункт\s+(?P<point>\d+(?:-\d+)?))?\s*$",
    re.IGNORECASE,
)
TOTAL_RE = re.compile(r"(?im)^\s*Итого\s*:\s*([0-9][0-9\s\u00a0]*(?:[.,][0-9]{1,2})?)\s*(?:KZT|тенге)\b")
PRAYER_AMOUNT_RE = re.compile(
    r"(?is)ПРОШУ\s+СУД:.*?в\s+размере\s+([0-9][0-9\s\u00a0]*(?:[.,][0-9]{1,2})?)\s*(?:KZT|тенге)\b"
)
DATE_DMY_RE = re.compile(r"\b(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})\b")
DATE_ISO_RE = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b")


def _locator(article: str, part: str | None, point: str | None) -> tuple[str, str, str]:
    return article, part or "", point or ""


def _citation_locator(value: str) -> tuple[str, str, str] | None:
    match = CITATION_LOCATOR_RE.match(value)
    if match is None:
        return None
    return _locator(match.group("article"), match.group("part"), match.group("point"))


def _format_locator(value: tuple[str, str, str]) -> str:
    article, part, point = value
    result = article
    if part:
        result += f", часть {part}"
    if point:
        result += f", пункт {point}"
    return result


def _parse_money(raw: str) -> Decimal | None:
    normalized = raw.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _dates_in_text(text: str) -> tuple[set[date], list[str]]:
    values: set[date] = set()
    invalid: list[str] = []
    for pattern in (DATE_DMY_RE, DATE_ISO_RE):
        for match in pattern.finditer(text):
            raw = match.group(0)
            try:
                values.add(
                    date(
                        int(match.group("year")),
                        int(match.group("month")),
                        int(match.group("day")),
                    )
                )
            except ValueError:
                invalid.append(raw)
    return values, invalid


@dataclass(frozen=True)
class FinalQAPolicy:
    code: str

    def check(
        self,
        *,
        case: LockedCase,
        document: DraftDocument,
        citations: list[ResearchCitation],
        procedural: ProceduralReport | None = None,
        calculation: CalculationResult | None = None,
    ) -> list[QAViolation]:
        raise NotImplementedError


class PartyPresencePolicy(FinalQAPolicy):
    def check(self, *, case, document, citations, procedural=None, calculation=None):
        missing = [party.name for party in case.parties if party.name not in document.text]
        if not missing:
            return []
        return [QAViolation(code=self.code, message=f"В документе отсутствуют стороны: {', '.join(missing)}")]


class ExactCitationPolicy(FinalQAPolicy):
    """Require the exact canonical article/part/point locator used in the draft."""

    def check(self, *, case, document, citations, procedural=None, calculation=None):
        used = {
            _locator(match.group("article"), match.group("part"), match.group("point"))
            for match in ARTICLE_RE.finditer(document.text)
        }
        if not used:
            return []

        verified: set[tuple[str, str, str]] = set()
        for citation in citations:
            if citation.status != VerificationStatus.VERIFIED or not citation.article:
                continue
            parsed = _citation_locator(citation.article.strip())
            if parsed is not None:
                verified.add(parsed)

        unknown = sorted(_format_locator(value) for value in used if value not in verified)
        if not unknown:
            return []
        return [QAViolation(
            code=self.code,
            message="В тексте есть непроверенные или неточно процитированные нормы: " + ", ".join(unknown),
        )]


class AmountConsistencyPolicy(FinalQAPolicy):
    """The total in calculations and the prayer must exactly match deterministic CalculationLayer."""

    def check(self, *, case, document, citations, procedural=None, calculation=None):
        if document.document_type != DocumentType.CLAIM:
            return []
        expected = calculation.total if calculation is not None else sum(
            (
                case.financials.principal or Decimal("0"),
                case.financials.penalty or Decimal("0"),
                case.financials.interest or Decimal("0"),
                case.financials.other or Decimal("0"),
            ),
            Decimal("0"),
        )
        if expected <= 0:
            return []

        violations: list[QAViolation] = []
        total_match = TOTAL_RE.search(document.text)
        prayer_match = PRAYER_AMOUNT_RE.search(document.text)
        for label, match in (("итоговый расчет", total_match), ("просительная часть", prayer_match)):
            if match is None:
                violations.append(QAViolation(code=self.code, message=f"Не найдена проверяемая сумма: {label}."))
                continue
            actual = _parse_money(match.group(1))
            if actual != expected:
                violations.append(QAViolation(
                    code=self.code,
                    message=f"Несовпадение суммы в разделе «{label}»: ожидается {expected}, найдено {actual}.",
                ))
        return violations


class DateConsistencyPolicy(FinalQAPolicy):
    """Block dates invented by the drafter outside LockedCase or deterministic procedural output."""

    def check(self, *, case, document, citations, procedural=None, calculation=None):
        used, invalid = _dates_in_text(document.text)
        if invalid:
            return [QAViolation(code=self.code, message="В документе есть некорректные даты: " + ", ".join(invalid))]
        if not used:
            return []

        allowed = {fact.event_date for fact in case.facts if fact.event_date is not None}
        if case.procedure.obligation_due_date is not None:
            allowed.add(case.procedure.obligation_due_date)
        if case.procedure.pretrial_demand_sent_date is not None:
            allowed.add(case.procedure.pretrial_demand_sent_date)
        for citation in citations:
            if citation.effective_from is not None:
                allowed.add(citation.effective_from)
            if citation.effective_to is not None:
                allowed.add(citation.effective_to)
        if procedural is not None:
            for item in procedural.items:
                derived, _ = _dates_in_text(item.conclusion)
                allowed.update(derived)

        unknown = sorted(value.isoformat() for value in used if value not in allowed)
        if not unknown:
            return []
        return [QAViolation(
            code=self.code,
            message="В тексте появились даты, отсутствующие в LockedCase/verified procedural output: " + ", ".join(unknown),
        )]


class OutcomeGuaranteePolicy(FinalQAPolicy):
    FORBIDDEN = ("вы точно выиграете", "суд обязательно удовлетворит", "гарантированно выигра")

    def check(self, *, case, document, citations, procedural=None, calculation=None):
        lower = document.text.lower()
        if not any(phrase in lower for phrase in self.FORBIDDEN):
            return []
        return [QAViolation(code=self.code, message="Документ содержит недопустимую гарантию исхода дела.")]


class FilingReadinessLanguagePolicy(FinalQAPolicy):
    FORBIDDEN = ("готов к подаче", "можно подавать без проверки")

    def check(self, *, case, document, citations, procedural=None, calculation=None):
        lower = document.text.lower()
        if not any(phrase in lower for phrase in self.FORBIDDEN):
            return []
        return [QAViolation(
            code=self.code,
            message="Система не может объявлять документ готовым к подаче без финальной проверки человеком.",
        )]


class ClaimRoleDirectionPolicy(FinalQAPolicy):
    def check(self, *, case, document, citations, procedural=None, calculation=None):
        from korgan_legal_ai.domain.models import PartyRole

        if document.document_type != DocumentType.CLAIM:
            return []
        claimant = next((p for p in case.parties if p.role in {PartyRole.CLAIMANT, PartyRole.CREDITOR}), None)
        defendant = next((p for p in case.parties if p.role in {PartyRole.DEFENDANT, PartyRole.DEBTOR}), None)
        violations: list[QAViolation] = []
        if claimant and not re.search(rf"(?im)^\s*Истец\s*:\s*{re.escape(claimant.name)}\s*$", document.text):
            violations.append(QAViolation(code=self.code, message=f"Не подтверждено сохранение роли истца/кредитора: {claimant.name}"))
        if defendant and not re.search(rf"(?im)^\s*Ответчик\s*:\s*{re.escape(defendant.name)}\s*$", document.text):
            violations.append(QAViolation(code=self.code, message=f"Не подтверждено сохранение роли ответчика/должника: {defendant.name}"))
        return violations
