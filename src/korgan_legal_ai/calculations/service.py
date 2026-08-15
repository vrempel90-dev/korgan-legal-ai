from decimal import Decimal

from korgan_legal_ai.domain.models import CalculationResult, Financials


ZERO = Decimal("0")


class CalculationLayer:
    def calculate_money(self, financials: Financials) -> CalculationResult:
        principal = financials.principal or ZERO
        penalty = financials.penalty or ZERO
        interest = financials.interest or ZERO
        other = financials.other or ZERO
        total = principal + penalty + interest + other
        mismatch = financials.user_stated_total is not None and total != financials.user_stated_total
        return CalculationResult(
            principal=principal,
            penalty=penalty,
            interest=interest,
            other=other,
            total=total,
            currency=financials.currency,
            mismatch_with_user_total=mismatch,
        )
