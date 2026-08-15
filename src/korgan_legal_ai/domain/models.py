from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class DocumentType(StrEnum):
    CLAIM = "claim"
    RESPONSE = "response"
    CONTRACT = "contract"
    MOTION = "motion"
    CONSULTATION = "consultation"


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


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    description: str | None = None
    kind: EvidenceKind = EvidenceKind.OTHER
    supports_fact_ids: list[str] = Field(default_factory=list)


class Financials(BaseModel):
    """Explicit monetary facts and contractual penalty parameters.

    ``penalty`` is a monetary amount only. Percentage clauses must be represented in the dedicated
    rate/cap fields so a percentage can never be mis-parsed as KZT.
    """

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


class CalculationResult(BaseModel):
    principal: Decimal
    penalty: Decimal
    interest: Decimal
    other: Decimal
    total: Decimal
    currency: str
    mismatch_with_user_total: bool = False
    penalty_days: int | None = Field(default=None, ge=0)
    penalty_rate_percent_per_day: Decimal | None = Field(default=None, ge=0)
    penalty_cap_amount: Decimal | None = Field(default=None, ge=0)


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
