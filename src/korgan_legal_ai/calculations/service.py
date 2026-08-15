from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from korgan_legal_ai.domain.models import CalculationResult, Financials


ZERO = Decimal("0")
HUNDRED = Decimal("100")
MONEY_QUANT = Decimal("0.01")


class CalculationLayer:
    def calculate_money(
        self,
        financials: Financials,
        *,
        obligation_due_date: date | None = None,
        as_of_date: date | None = None,
    ) -> CalculationResult:
        # The debt has exactly one source of truth. When the contract sum is known, the principal
        # is derived from it minus every payment credited against it, so the contract sum can never
        # also appear as an independent claimable position on top of the remaining balance.
        payments_total = sum(financials.payments, ZERO)
        contract_amount = financials.contract_amount
        principal_conflicts = False
        if contract_amount is not None:
            derived = contract_amount - payments_total
            principal = derived if derived > ZERO else ZERO
            # A separately stated principal is not silently overridden and does not silently win:
            # the disagreement is surfaced so a human resolves it.
            principal_conflicts = (
                financials.principal is not None and financials.principal != derived
            )
        else:
            principal = financials.principal or ZERO

        interest = financials.interest or ZERO

        other = financials.other or ZERO
        # "Иные суммы" must only ever carry amounts that are not already inside the debt. Echoing
        # the contract sum or the payments there double-counts one and the same operation.
        # Only an unambiguous echo is dropped: a genuine separate amount (damages, costs) that
        # happens to differ from the contract sum and the payments is kept in full.
        other_excluded = contract_amount is not None and other > ZERO and other in (
            contract_amount,
            payments_total,
        )
        if other_excluded:
            other = ZERO

        penalty = financials.penalty or ZERO
        penalty_days: int | None = None
        penalty_rate = financials.penalty_rate_percent_per_day
        penalty_cap_amount: Decimal | None = None

        if (
            financials.penalty is None
            and principal > ZERO
            and penalty_rate is not None
            and obligation_due_date is not None
            and as_of_date is not None
            and as_of_date > obligation_due_date
        ):
            penalty_days = (as_of_date - obligation_due_date).days
            raw_penalty = principal * penalty_rate / HUNDRED * Decimal(penalty_days)

            cap_percent = financials.penalty_cap_percent_of_principal
            if cap_percent is not None:
                penalty_cap_amount = (principal * cap_percent / HUNDRED).quantize(
                    MONEY_QUANT,
                    rounding=ROUND_HALF_UP,
                )
                raw_penalty = min(raw_penalty, penalty_cap_amount)

            penalty = raw_penalty.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

        total = principal + penalty + interest + other
        mismatch = financials.user_stated_total is not None and total != financials.user_stated_total
        return CalculationResult(
            contract_amount=contract_amount,
            payments_total=payments_total,
            principal_conflicts_with_payments=principal_conflicts,
            other_excluded_as_duplicate=other_excluded,
            principal=principal,
            penalty=penalty,
            interest=interest,
            other=other,
            total=total,
            currency=financials.currency,
            mismatch_with_user_total=mismatch,
            penalty_days=penalty_days,
            penalty_rate_percent_per_day=penalty_rate,
            penalty_cap_amount=penalty_cap_amount,
        )
