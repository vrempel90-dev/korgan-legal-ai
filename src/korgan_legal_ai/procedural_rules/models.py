from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from korgan_legal_ai.domain.models import ResearchCitation, VerificationStatus


class StructuredRuleStatus(StrEnum):
    CANONICAL = "canonical"
    PENDING_REVIEW = "pending_review"


class RuleBasis(BaseModel):
    code_id: str
    article_number: str
    part: str = ""
    point: str = ""

    @property
    def locator(self) -> str:
        value = self.article_number
        if self.part:
            value += f", часть {self.part}"
        if self.point:
            value += f", пункт {self.point}"
        return value


class VersionedRule(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    effective_from: date
    effective_to: date | None = None
    status: StructuredRuleStatus = StructuredRuleStatus.CANONICAL
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def valid_range(self) -> "VersionedRule":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        return self


class StateDutyRule(VersionedRule):
    rule_code: str
    claimant_type: str
    claim_type: str
    rate_percent: Decimal
    cap_mrp: Decimal | None = None
    basis: RuleBasis


class MrpValue(VersionedRule):
    value_year: int
    value_kzt: Decimal
    basis: RuleBasis


class JurisdictionRule(VersionedRule):
    rule_code: str
    dimension: str
    plaintiff_type: str
    defendant_type: str
    dispute_type: str
    result_code: str
    basis: RuleBasis


class DeadlineRule(VersionedRule):
    rule_code: str
    deadline_type: str
    duration_value: int
    duration_unit: str
    trigger_event: str
    start_offset_days: int = 1
    requires_workday_calendar: bool = True
    bases: list[RuleBasis]


class StateDutyResult(BaseModel):
    status: VerificationStatus
    amount_kzt: Decimal | None = None
    uncapped_amount_kzt: Decimal | None = None
    cap_kzt: Decimal | None = None
    rate_percent: Decimal | None = None
    rule_code: str | None = None
    citations: list[ResearchCitation] = Field(default_factory=list)
    verification_note: str | None = None


class JurisdictionResult(BaseModel):
    status: VerificationStatus
    court_type: str | None = None
    territorial_rule: str | None = None
    citations: list[ResearchCitation] = Field(default_factory=list)
    verification_note: str | None = None


class DeadlineResult(BaseModel):
    status: VerificationStatus
    rule_code: str | None = None
    period_start: date | None = None
    nominal_deadline: date | None = None
    final_deadline: date | None = None
    citations: list[ResearchCitation] = Field(default_factory=list)
    verification_note: str | None = None
