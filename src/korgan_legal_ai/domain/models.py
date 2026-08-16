from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


_RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_RU_DATE_RE = re.compile(
    r"^\s*(?P<day>\d{1,2})\s+(?P<month>[а-яё]+)\s+(?P<year>\d{4})(?:\s*(?:г\.|года))?\s*$",
    re.IGNORECASE,
)
_MIDNIGHT_DATETIME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[T ]00:00(?::00(?:\.0+)?)?(?:Z|[+-]00:00)?$"
)


def _normalize_explicit_date(value):
    """Normalize only unambiguous date literals without inferring missing information."""
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        if value.time().isoformat() == "00:00:00":
            return value.date()
        return value
    if not isinstance(value, str):
        return value

    raw = value.strip()
    if not raw:
        return value

    midnight = _MIDNIGHT_DATETIME_RE.fullmatch(raw)
    if midnight:
        raw = midnight.group("date")

    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass

    match = _RU_DATE_RE.fullmatch(raw)
    if match:
        month = _RU_MONTHS.get(match.group("month").lower())
        if month is not None:
            try:
                return date(int(match.group("year")), month, int(match.group("day")))
            except ValueError:
                return value
    return value


class DocumentType(StrEnum):
    CLAIM = "claim"
    RESPONSE = "response"
    CONTRACT = "contract"
    MOTION = "motion"
    CONSULTATION = "consultation"
    PRETRIAL_DEMAND = "pretrial_demand"
    COMPLAINT = "complaint"
    APPEAL = "appeal"


class LegalArea(StrEnum):
    DEBT_RECOVERY = "debt_recovery"
    COMMERCIAL_DISPUTE = "commercial_dispute"
    CONTRACT_DISPUTE = "contract_dispute"
    EMPLOYMENT = "employment"
    TORT = "tort"
    CIVIL_OTHER = "civil_other"
    UNKNOWN = "unknown"


class PartyRole(StrEnum):
    CLAIMANT = "claimant"
    DEFENDANT = "defendant"
    CREDITOR = "creditor"
    DEBTOR = "debtor"
    EMPLOYER = "employer"
    EMPLOYEE = "employee"
    OTHER = "other"


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReadinessStatus(StrEnum):
    PRELIMINARY_DRAFT = "PRELIMINARY DRAFT"
    LAWYER_REVIEW_DRAFT = "LAWYER-REVIEW DRAFT"
    READY_FOR_FINAL_HUMAN_REVIEW = "READY FOR FINAL HUMAN REVIEW"


class FilingMode(StrEnum):
    PAPER = "paper"
    ELECTRONIC = "electronic"


class RepresentativeKind(StrEnum):
    DIRECTOR = "director"
    EMPLOYEE = "employee"
    ADVOCATE = "advocate"
    LEGAL_CONSULTANT = "legal_consultant"
    OTHER = "other"


class EvidenceKind(StrEnum):
    CONTRACT = "contract"
    PRIMARY_DOCUMENT = "primary_document"
    PAYMENT = "payment"
    PRETRIAL_DEMAND = "pretrial_demand"
    PRETRIAL_DELIVERY = "pretrial_delivery"
    AUTHORITY = "authority"
    PROFESSIONAL_STATUS = "professional_status"
    REGISTRATION = "registration"
    STATE_DUTY_PAYMENT = "state_duty_payment"
    RECONCILIATION = "reconciliation"
    OTHER = "other"


class Party(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    role: PartyRole
    iin_bin: str | None = None
    address: str | None = None


class Fact(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    statement: str
    event_date: date | None = None
    source: Literal["user"] = "user"
    locked: bool = True

    @field_validator("event_date", mode="before")
    @classmethod
    def normalize_event_date(cls, value):
        return _normalize_explicit_date(value)


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    description: str | None = None
    kind: EvidenceKind = EvidenceKind.OTHER
    supports_fact_ids: list[str] = Field(default_factory=list)


class Payment(BaseModel):
    """One payment credited against the debt, with the date it was actually made.

    The date is what lets the penalty accrue on the balance that was really outstanding in each
    period instead of on today's remainder. A payment without a date is still counted against the
    debt; it simply cannot narrow the accrual window.
    """

    amount: Decimal
    paid_on: date | None = None

    @field_validator("paid_on", mode="before")
    @classmethod
    def normalize_paid_on(cls, value):
        return _normalize_explicit_date(value)


class Financials(BaseModel):
    """Explicit monetary facts and contractual penalty parameters.

    ``penalty`` is a monetary amount only. Percentage clauses must be represented in the dedicated
    rate/cap fields so a percentage can never be mis-parsed as KZT.
    """

    contract_amount: Decimal | None = None
    payments: list[Decimal] = Field(default_factory=list)
    payment_schedule: list[Payment] = Field(default_factory=list)
    principal: Decimal | None = None
    penalty: Decimal | None = None
    interest: Decimal | None = None
    other: Decimal | None = None
    user_stated_total: Decimal | None = None
    currency: str = "KZT"
    penalty_rate_percent_per_day: Decimal | None = Field(default=None, ge=0)
    penalty_cap_percent_of_principal: Decimal | None = Field(default=None, ge=0)


class ProcedureFacts(BaseModel):
    """Only explicit filing/procedure facts locked from the user or supplied documents.

    None means unknown. Legal modules must never convert None into a guessed legal fact.
    """

    obligation_due_date: date | None = None
    pretrial_required_by_contract: bool | None = None
    pretrial_demand_sent_date: date | None = None
    representative_kind: RepresentativeKind | None = None
    representative_name: str | None = None
    representative_can_sign_claim: bool | None = None
    filing_mode: FilingMode | None = None
    third_party_count: int = Field(default=0, ge=0)
    copies_prepared: bool | None = None

    @field_validator("obligation_due_date", "pretrial_demand_sent_date", mode="before")
    @classmethod
    def normalize_procedure_dates(cls, value):
        return _normalize_explicit_date(value)


class LockedCase(BaseModel):
    case_id: str = Field(default_factory=lambda: uuid4().hex)
    raw_text: str
    parties: list[Party]
    facts: list[Fact]
    evidence: list[Evidence] = Field(default_factory=list)
    financials: Financials = Field(default_factory=Financials)
    procedure: ProcedureFacts = Field(default_factory=ProcedureFacts)
    ambiguities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_distinct_party_roles(self) -> "LockedCase":
        if len(self.parties) < 2:
            raise ValueError("At least two parties are required")
        fact_ids = {fact.id for fact in self.facts}
        dangling = {
            fact_id
            for evidence in self.evidence
            for fact_id in evidence.supports_fact_ids
            if fact_id not in fact_ids
        }
        if dangling:
            raise ValueError("Evidence cannot reference unknown fact ids")
        return self


class RoutingDecision(BaseModel):
    document_type: DocumentType
    legal_area: LegalArea
    confidence: float = Field(ge=0, le=1)
    rationale: str


class ResearchCitation(BaseModel):
    source_url: str | None = None
    source_title: str
    law_name: str | None = None
    article: str | None = None
    text_excerpt: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status: VerificationStatus
    verification_note: str | None = None
    # The corpus holds a planned re-verification date for each norm. A passed date does not make
    # the wording wrong, so the citation stays usable — but it must not be presented as freshly
    # confirmed either, so the fact travels with the citation instead of being dropped.
    review_overdue: bool = False
    next_review_date: date | None = None

    @field_validator("effective_from", "effective_to", mode="before")
    @classmethod
    def normalize_effective_dates(cls, value):
        return _normalize_explicit_date(value)


class ProceduralItem(BaseModel):
    name: str
    status: VerificationStatus
    conclusion: str
    sources: list[ResearchCitation] = Field(default_factory=list)


class ProceduralReport(BaseModel):
    items: list[ProceduralItem]

    @property
    def needs_verification(self) -> list[str]:
        return [item.name for item in self.items if item.status == VerificationStatus.NEEDS_VERIFICATION]


class EvidenceLink(BaseModel):
    fact_id: str
    evidence_ids: list[str]
    supported: bool


class EvidenceMap(BaseModel):
    links: list[EvidenceLink]

    @property
    def unsupported_fact_ids(self) -> list[str]:
        return [link.fact_id for link in self.links if not link.supported]


class PenaltyPeriod(BaseModel):
    start: date
    end: date
    days: int = Field(ge=0)
    outstanding: Decimal
    amount: Decimal


class CalculationResult(BaseModel):
    contract_amount: Decimal | None = None
    payments_total: Decimal = Decimal("0")
    principal: Decimal
    penalty: Decimal
    interest: Decimal
    other: Decimal
    total: Decimal
    currency: str
    mismatch_with_user_total: bool = False
    principal_conflicts_with_payments: bool = False
    other_excluded_as_duplicate: bool = False
    penalty_days: int | None = Field(default=None, ge=0)
    penalty_rate_percent_per_day: Decimal | None = Field(default=None, ge=0)
    penalty_cap_amount: Decimal | None = Field(default=None, ge=0)
    penalty_cap_applied: bool = False
    # True when "не более N% от суммы задолженности" would yield a different ceiling depending on
    # whether it is read against the defaulted debt or the remaining balance, and the choice
    # changes the result. The wording question belongs to a human, so it is reported, not resolved.
    penalty_cap_base_ambiguous: bool = False
    # Every accrual period the penalty was built from: start, end, days and the balance that was
    # actually outstanding during that period. This is what makes a period-based penalty auditable
    # by a human instead of being a single unexplained number.
    penalty_periods: list["PenaltyPeriod"] = Field(default_factory=list)


class DraftDocument(BaseModel):
    document_type: DocumentType
    text: str
    readiness: ReadinessStatus
    needs_verification: list[str] = Field(default_factory=list)
    summary: str


class QAViolation(BaseModel):
    code: str
    message: str
    blocking: bool = True


class QAResult(BaseModel):
    passed: bool
    violations: list[QAViolation] = Field(default_factory=list)


class WorkflowResult(BaseModel):
    locked_case: LockedCase
    routing: RoutingDecision
    procedural: ProceduralReport
    evidence_map: EvidenceMap
    calculation: CalculationResult
    document: DraftDocument
    qa: QAResult
    audit_head: str
