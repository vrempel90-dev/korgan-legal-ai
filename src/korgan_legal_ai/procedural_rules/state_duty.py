from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from korgan_legal_ai.domain.models import VerificationStatus
from korgan_legal_ai.procedural_rules.basis import LegalBasisVerifier
from korgan_legal_ai.procedural_rules.models import StateDutyResult
from korgan_legal_ai.procedural_rules.repository import ProceduralRuleRepository

_MONEY = Decimal("0.01")


class StateDutyCalculator:
    def __init__(self, repository: ProceduralRuleRepository, basis_verifier: LegalBasisVerifier) -> None:
        self.repository = repository
        self.basis_verifier = basis_verifier

    def calculate(
        self, *, claim_amount_kzt: Decimal, claimant_type: str,
        claim_type: str, event_date: date
    ) -> StateDutyResult:
        if claim_amount_kzt < 0:
            raise ValueError("claim_amount_kzt cannot be negative")
        rule = self.repository.find_state_duty(
            claimant_type=claimant_type, claim_type=claim_type, event_date=event_date
        )
        if rule is None:
            return StateDutyResult(
                status=VerificationStatus.NEEDS_VERIFICATION,
                verification_note="No canonical versioned state-duty rule applies to this case/date.",
            )
        rate_citation = self.basis_verifier.verify(rule.basis, event_date=event_date)
        if rate_citation is None:
            return StateDutyResult(
                status=VerificationStatus.NEEDS_VERIFICATION,
                rule_code=rule.rule_code,
                verification_note="State-duty rule exists, but its legal basis is not VERIFIED.",
            )

        uncapped = (claim_amount_kzt * rule.rate_percent / Decimal("100")).quantize(
            _MONEY, rounding=ROUND_HALF_UP
        )
        citations = [rate_citation]
        cap_kzt: Decimal | None = None
        if rule.cap_mrp is not None:
            mrp = self.repository.find_mrp(event_date=event_date)
            if mrp is None:
                return StateDutyResult(
                    status=VerificationStatus.NEEDS_VERIFICATION,
                    rule_code=rule.rule_code,
                    citations=citations,
                    verification_note="State-duty cap requires an applicable canonical MRP value.",
                )
            mrp_citation = self.basis_verifier.verify(mrp.basis, event_date=event_date)
            if mrp_citation is None:
                return StateDutyResult(
                    status=VerificationStatus.NEEDS_VERIFICATION,
                    rule_code=rule.rule_code,
                    citations=citations,
                    verification_note="MRP value exists, but its legal basis is not VERIFIED.",
                )
            citations.append(mrp_citation)
            cap_kzt = (mrp.value_kzt * rule.cap_mrp).quantize(_MONEY, rounding=ROUND_HALF_UP)

        amount = min(uncapped, cap_kzt) if cap_kzt is not None else uncapped
        return StateDutyResult(
            status=VerificationStatus.VERIFIED,
            amount_kzt=amount,
            uncapped_amount_kzt=uncapped,
            cap_kzt=cap_kzt,
            rate_percent=rule.rate_percent,
            rule_code=rule.rule_code,
            citations=citations,
            verification_note="Calculated only from canonical structured rate/MRP rows with VERIFIED bases.",
        )
