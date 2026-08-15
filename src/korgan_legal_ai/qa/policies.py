from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from korgan_legal_ai.blueprints.models import DocumentBlueprint, SectionKind
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
_AMOUNT = r"([0-9][0-9\s\u00a0]*(?:[.,][0-9]{1,2})?)\s*(?:KZT|тенге)\b"
PRAYER_AMOUNT_RE = re.compile(r"(?is)ПРОШУ\s+СУД:.*?в\s+размере\s+" + _AMOUNT)


def prayer_amount_pattern(heading: str) -> re.Pattern[str]:
    """Build the prayer-amount probe for a document type's own closing heading.

    Every document that claims money must repeat the deterministic total in its demands, but the
    heading above those demands differs per document type ("ПРОШУ СУД:", "ТРЕБУЮ:", ...), so the
    probe is derived from the blueprint rather than assumed.
    """
    return re.compile(r"(?is)" + re.escape(heading) + r".*?в\s+размере\s+" + _AMOUNT)
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
        blueprint: "DocumentBlueprint | None" = None,
        practice: tuple = (),
    ) -> list[QAViolation]:
        raise NotImplementedError


class PartyPresencePolicy(FinalQAPolicy):
    def check(self, *, case, document, citations, procedural=None, calculation=None, blueprint=None, practice=()):
        missing = [party.name for party in case.parties if party.name not in document.text]
        if not missing:
            return []
        return [QAViolation(code=self.code, message=f"В документе отсутствуют стороны: {', '.join(missing)}")]


class ExactCitationPolicy(FinalQAPolicy):
    """Require the exact canonical article/part/point locator used in the draft."""

    def check(self, *, case, document, citations, procedural=None, calculation=None, blueprint=None, practice=()):
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

    def check(self, *, case, document, citations, procedural=None, calculation=None, blueprint=None, practice=()):
        claims_money = (
            blueprint.monetary
            if blueprint is not None
            else document.document_type == DocumentType.CLAIM
        )
        if not claims_money:
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
        prayer_heading = (
            blueprint.heading_for(SectionKind.PRAYER) if blueprint is not None else ""
        )
        prayer_pattern = (
            prayer_amount_pattern(prayer_heading) if prayer_heading else PRAYER_AMOUNT_RE
        )
        prayer_match = prayer_pattern.search(document.text)
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

    def check(self, *, case, document, citations, procedural=None, calculation=None, blueprint=None, practice=()):
        used, invalid = _dates_in_text(document.text)
        if invalid:
            return [QAViolation(code=self.code, message="В документе есть некорректные даты: " + ", ".join(invalid))]
        if not used:
            return []

        allowed = {fact.event_date for fact in case.facts if fact.event_date is not None}
        # A date written inside a locked fact — "договор № 14 от 12.02.2026" — is part of LockedCase
        # even when it was not extracted into a separate event_date field. This policy exists to
        # catch dates the drafter invented, and flagging one the user typed would be a false alarm
        # on determined data.
        for fact in case.facts:
            stated, _ = _dates_in_text(fact.statement)
            allowed.update(stated)
        for evidence in case.evidence:
            stated, _ = _dates_in_text(f"{evidence.title} {evidence.description or ''}")
            allowed.update(stated)
        if case.procedure.obligation_due_date is not None:
            allowed.add(case.procedure.obligation_due_date)
        if case.procedure.pretrial_demand_sent_date is not None:
            allowed.add(case.procedure.pretrial_demand_sent_date)
        # Locked payment dates and the accrual period boundaries the calculation layer derived from
        # them are deterministic output, on the same footing as a verified procedural conclusion.
        for payment in case.financials.payment_schedule:
            if payment.paid_on is not None:
                allowed.add(payment.paid_on)
        if calculation is not None:
            for period in calculation.penalty_periods:
                allowed.add(period.start)
                allowed.add(period.end)
        # A decision date comes from the reviewed practice corpus, on the same footing as a norm's
        # effective date: it is retrieved, not composed by the drafter.
        for hit in practice:
            allowed.add(hit.act.decided_on)
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

    def check(self, *, case, document, citations, procedural=None, calculation=None, blueprint=None, practice=()):
        lower = document.text.lower()
        if not any(phrase in lower for phrase in self.FORBIDDEN):
            return []
        return [QAViolation(code=self.code, message="Документ содержит недопустимую гарантию исхода дела.")]


class FilingReadinessLanguagePolicy(FinalQAPolicy):
    FORBIDDEN = ("готов к подаче", "можно подавать без проверки")

    def check(self, *, case, document, citations, procedural=None, calculation=None, blueprint=None, practice=()):
        lower = document.text.lower()
        if not any(phrase in lower for phrase in self.FORBIDDEN):
            return []
        return [QAViolation(
            code=self.code,
            message="Система не может объявлять документ готовым к подаче без финальной проверки человеком.",
        )]


class ClaimRoleDirectionPolicy(FinalQAPolicy):
    """Each side must be printed under the label that matches the role it was locked with.

    Presentation differs by document type — a claim is authored by the claimant, a response by the
    defendant — but the binding between a printed label and the locked party never does. Checking
    the label against the blueprint's role sets is what makes "who is suing whom" impossible to
    swap during drafting.
    """

    def check(self, *, case, document, citations, procedural=None, calculation=None, blueprint=None, practice=()):
        from korgan_legal_ai.domain.models import PartyRole

        if blueprint is not None:
            presentation = blueprint.parties
            pairs = (
                (presentation.author_label, presentation.author_roles),
                (presentation.opponent_label, presentation.opponent_roles),
            )
        elif document.document_type == DocumentType.CLAIM:
            pairs = (
                ("Истец", {PartyRole.CLAIMANT, PartyRole.CREDITOR}),
                ("Ответчик", {PartyRole.DEFENDANT, PartyRole.DEBTOR}),
            )
        else:
            return []

        violations: list[QAViolation] = []
        for label, roles in pairs:
            party = next((p for p in case.parties if p.role in roles), None)
            if party is None:
                continue
            if not re.search(
                rf"(?im)^\s*{re.escape(label)}\s*:\s*{re.escape(party.name)}\s*$", document.text
            ):
                violations.append(
                    QAViolation(
                        code=self.code,
                        message=f"Не подтверждено сохранение роли «{label}»: {party.name}",
                    )
                )
        return violations
