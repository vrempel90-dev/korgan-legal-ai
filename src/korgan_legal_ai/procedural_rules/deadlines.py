from __future__ import annotations

import calendar
from abc import ABC, abstractmethod
from datetime import date, timedelta

from korgan_legal_ai.domain.models import VerificationStatus
from korgan_legal_ai.procedural_rules.basis import LegalBasisVerifier
from korgan_legal_ai.procedural_rules.models import DeadlineResult
from korgan_legal_ai.procedural_rules.repository import ProceduralRuleRepository


class WorkingDayCalendar(ABC):
    """Must be backed by a verified work/non-work calendar; None means unknown."""

    @abstractmethod
    def is_working_day(self, value: date) -> bool | None:
        raise NotImplementedError


class FailClosedWorkingDayCalendar(WorkingDayCalendar):
    def is_working_day(self, value: date) -> bool | None:
        return None


def _add_months(value: date, months: int) -> date:
    target_index = value.year * 12 + (value.month - 1) + months
    year, month_index = divmod(target_index, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _add_years(value: date, years: int) -> date:
    target_year = value.year + years
    day = min(value.day, calendar.monthrange(target_year, value.month)[1])
    return date(target_year, value.month, day)


class DeadlineCalculator:
    def __init__(
        self, repository: ProceduralRuleRepository, basis_verifier: LegalBasisVerifier,
        workday_calendar: WorkingDayCalendar | None = None,
    ) -> None:
        self.repository = repository
        self.basis_verifier = basis_verifier
        self.workday_calendar = workday_calendar or FailClosedWorkingDayCalendar()

    @staticmethod
    def _nominal(trigger_date: date, value: int, unit: str) -> date:
        if unit == "years":
            return _add_years(trigger_date, value)
        if unit == "months":
            return _add_months(trigger_date, value)
        if unit == "days":
            return trigger_date + timedelta(days=value)
        raise ValueError(f"Unsupported deadline unit: {unit}")

    def calculate(self, *, rule_code: str, trigger_date: date, event_date: date) -> DeadlineResult:
        rule = self.repository.find_deadline(rule_code=rule_code, event_date=event_date)
        if rule is None:
            return DeadlineResult(
                status=VerificationStatus.NEEDS_VERIFICATION,
                verification_note="No canonical versioned deadline formula applies to this event date.",
            )
        citations = []
        for basis in rule.bases:
            citation = self.basis_verifier.verify(basis, event_date=event_date)
            if citation is None:
                return DeadlineResult(
                    status=VerificationStatus.NEEDS_VERIFICATION,
                    rule_code=rule.rule_code,
                    citations=citations,
                    verification_note="Deadline formula exists, but at least one legal basis is not VERIFIED.",
                )
            citations.append(citation)

        period_start = trigger_date + timedelta(days=rule.start_offset_days)
        nominal = self._nominal(trigger_date, rule.duration_value, rule.duration_unit)
        final = nominal
        if rule.requires_workday_calendar:
            for _ in range(14):
                working = self.workday_calendar.is_working_day(final)
                if working is None:
                    return DeadlineResult(
                        status=VerificationStatus.NEEDS_VERIFICATION,
                        rule_code=rule.rule_code,
                        period_start=period_start,
                        nominal_deadline=nominal,
                        final_deadline=None,
                        citations=citations,
                        verification_note=(
                            "Statutory formula is VERIFIED, but final filing date needs a verified "
                            "work/non-work calendar before any non-working-day adjustment."
                        ),
                    )
                if working:
                    break
                final += timedelta(days=1)
            else:
                return DeadlineResult(
                    status=VerificationStatus.NEEDS_VERIFICATION,
                    rule_code=rule.rule_code,
                    period_start=period_start,
                    nominal_deadline=nominal,
                    citations=citations,
                    verification_note="Verified workday calendar did not resolve an ending working day.",
                )

        return DeadlineResult(
            status=VerificationStatus.VERIFIED,
            rule_code=rule.rule_code,
            period_start=period_start,
            nominal_deadline=nominal,
            final_deadline=final,
            citations=citations,
            verification_note="Deadline calculated from a canonical structured formula and VERIFIED bases.",
        )
