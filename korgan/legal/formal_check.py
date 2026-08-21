"""Formal check of a statement of claim against ГПК РК form requirements.

The checks here are the ones a court registry applies before the case is even
read: is the court named, are the parties identifiable, is the claim price
supported by a calculation, was the pre-trial step taken where it is required,
do the annexes match the evidence the text relies on, is the title intact.

Defects are graded, because they are not equivalent. A missing annex is a gap
the claimant can close; an unnamed court means the document cannot be filed at
all. Critical defects mark the document explicitly rather than blocking its
generation — a marked draft can be fixed, a refused one leaves the user with
nothing to fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

FILING_BLOCKED_MARKER = "[ДОКУМЕНТ НЕ ГОТОВ К ПОДАЧЕ]"

PLACEHOLDER = re.compile(r"\[ТРЕБУЕТ[^\]]*\]", re.IGNORECASE)
_IDENTIFIER = re.compile(r"(?<!\d)\d{12}(?!\d)")
_COURT_NAME = re.compile(
    r"(?:районн\w*|городск\w*|межрайонн\w*|специализированн\w*|областн\w*)\s+суд|\bсмэс\b",
    re.IGNORECASE,
)
_AMOUNT = re.compile(r"\d[\d\s ]*(?:тенге|тг\b)", re.IGNORECASE)
# «что подтверждается распиской от 10.01.2026», «подтверждается договором»
_EVIDENCE_REFERENCE = re.compile(
    r"подтвержда\w*\s+(?:прилагаем\w+\s+)?([а-яё]+(?:\s+[а-яё]+){0,2})",
    re.IGNORECASE,
)
_DANGLING_TITLE_TAIL = re.compile(r"(?:[,\-–—:]|\b(?:о|об|и|в|на|по|для|с|от|при|за))\s*$", re.IGNORECASE)


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Defect:
    code: str
    severity: Severity
    message: str

    def render(self) -> str:
        prefix = "КРИТИЧНО" if self.severity is Severity.CRITICAL else "Замечание"
        return f"{prefix}: {self.message}"


@dataclass(slots=True)
class ClaimForm:
    title: str = ""
    court: str = ""
    claimant: list[str] = field(default_factory=list)
    defendant: list[str] = field(default_factory=list)
    price_of_claim: str = ""
    price_breakdown: str = ""
    facts: list[str] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    pretrial_required: bool = False
    pretrial_confirmed: bool = False


@dataclass(frozen=True, slots=True)
class FormalCheckResult:
    defects: tuple[Defect, ...]

    @property
    def critical(self) -> tuple[Defect, ...]:
        return tuple(item for item in self.defects if item.severity is Severity.CRITICAL)

    @property
    def warnings(self) -> tuple[Defect, ...]:
        return tuple(item for item in self.defects if item.severity is Severity.WARNING)

    @property
    def is_filing_ready(self) -> bool:
        return not self.critical

    def marker(self) -> str:
        """Explicit mark for a document that cannot be filed as it stands."""
        if self.is_filing_ready:
            return ""
        reasons = "; ".join(item.message for item in self.critical)
        return f"{FILING_BLOCKED_MARKER} {reasons}."

    def lines(self) -> list[str]:
        return [item.render() for item in self.defects]


def _has_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER.search(value or ""))


def _check_court(form: ClaimForm) -> list[Defect]:
    court = (form.court or "").strip()
    if not court or _has_placeholder(court):
        return [
            Defect(
                code="court_missing",
                severity=Severity.CRITICAL,
                message="суд не назван конкретно — подсудность не определена",
            )
        ]
    if not _COURT_NAME.search(court):
        return [
            Defect(
                code="court_unclear",
                severity=Severity.WARNING,
                message=f"наименование суда не похоже на конкретный суд: «{court}»",
            )
        ]
    return []


def _check_parties(form: ClaimForm) -> list[Defect]:
    defects: list[Defect] = []

    for role, values, severity in (
        ("истца", form.claimant, Severity.CRITICAL),
        ("ответчика", form.defendant, Severity.WARNING),
    ):
        text = " ".join(values)
        if not text.strip() or _has_placeholder(text):
            defects.append(
                Defect(
                    code=f"party_missing_{role}",
                    severity=Severity.CRITICAL,
                    message=f"не указаны данные {role}",
                )
            )
            continue
        if not _IDENTIFIER.search(text):
            defects.append(
                Defect(
                    code=f"identifier_missing_{role}",
                    severity=severity,
                    message=f"нет ИИН/БИН {role}",
                )
            )
    return defects


def _check_price(form: ClaimForm) -> list[Defect]:
    defects: list[Defect] = []
    price = (form.price_of_claim or "").strip()

    if not price or _has_placeholder(price) or not _AMOUNT.search(price):
        defects.append(
            Defect(
                code="price_missing",
                severity=Severity.CRITICAL,
                message="цена иска не указана суммой",
            )
        )
    if not (form.price_breakdown or "").strip():
        defects.append(
            Defect(
                code="price_breakdown_missing",
                severity=Severity.CRITICAL,
                message="отсутствует расчёт цены иска",
            )
        )
    return defects


def _check_pretrial(form: ClaimForm) -> list[Defect]:
    if form.pretrial_required and not form.pretrial_confirmed:
        return [
            Defect(
                code="pretrial_not_confirmed",
                severity=Severity.CRITICAL,
                message="обязательный досудебный порядок не подтверждён материалами",
            )
        ]
    return []


def _normalize_words(text: str) -> set[str]:
    return {word[:5] for word in re.findall(r"[а-яё]{4,}", text.lower())}


def _check_attachments(form: ClaimForm) -> list[Defect]:
    """Evidence the facts lean on must appear among the annexes."""
    annex_words = _normalize_words(" ".join(form.attachments))
    defects: list[Defect] = []
    reported: set[str] = set()

    for fact in form.facts:
        for match in _EVIDENCE_REFERENCE.finditer(fact):
            phrase = match.group(1).strip()
            words = _normalize_words(phrase)
            if not words or words & annex_words or phrase in reported:
                continue
            reported.add(phrase)
            defects.append(
                Defect(
                    code="attachment_missing",
                    severity=Severity.CRITICAL,
                    message=f"фактическая часть ссылается на «{phrase}», но в приложениях этого документа нет",
                )
            )
    return defects


def _check_title(form: ClaimForm) -> list[Defect]:
    title = (form.title or "").strip()
    if not title:
        return [Defect(code="title_missing", severity=Severity.CRITICAL, message="отсутствует заголовок документа")]
    if _DANGLING_TITLE_TAIL.search(title):
        return [
            Defect(
                code="title_truncated",
                severity=Severity.CRITICAL,
                message=f"заголовок оборван: «{title}»",
            )
        ]
    return []


def _check_requests(form: ClaimForm) -> list[Defect]:
    if not [item for item in form.requests if item.strip()]:
        return [
            Defect(
                code="requests_missing",
                severity=Severity.CRITICAL,
                message="отсутствует просительная часть",
            )
        ]
    return []


def check_claim_form(form: ClaimForm) -> FormalCheckResult:
    """Run every ГПК form check and return the defects found, most severe first."""
    defects: list[Defect] = []
    for check in (
        _check_title,
        _check_court,
        _check_parties,
        _check_price,
        _check_requests,
        _check_pretrial,
        _check_attachments,
    ):
        defects.extend(check(form))

    defects.sort(key=lambda item: 0 if item.severity is Severity.CRITICAL else 1)
    return FormalCheckResult(defects=tuple(defects))
