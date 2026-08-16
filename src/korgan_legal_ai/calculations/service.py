from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from korgan_legal_ai.domain.models import (
    CalculationResult,
    Financials,
    Payment,
    PenaltyPeriod,
)
from korgan_legal_ai.positions import PositionRegistry, load_positions


ZERO = Decimal("0")
HUNDRED = Decimal("100")
MONEY_QUANT = Decimal("0.01")


class CalculationLayer:
    """Deterministic money and period arithmetic.

    Where a contractual phrase has more than one defensible reading, the choice is not decided here:
    it is read from the recorded firm position, so changing the firm's view is an edit to that
    record rather than a change to this code.
    """

    def __init__(self, positions: PositionRegistry | None = None) -> None:
        self.positions = positions or load_positions()

    @staticmethod
    def _payments_total(financials: Financials) -> Decimal:
        scheduled = sum((payment.amount for payment in financials.payment_schedule), ZERO)
        return sum(financials.payments, ZERO) + scheduled

    @staticmethod
    def _accrual_periods(
        *,
        base: Decimal,
        undated_total: Decimal,
        dated: list[Payment],
        obligation_due_date: date,
        as_of_date: date,
    ) -> list[tuple[date, date, int, Decimal]]:
        """Split the delay into periods bounded by the payments made during it.

        Within one period the outstanding balance is constant, so the penalty for the period is a
        plain multiplication. A payment made mid-delay therefore stops the penalty growing on the
        part of the debt it extinguished, which is the difference between a correct penalty and one
        calculated on today's remainder for the whole period.
        """
        boundaries = sorted(
            {
                payment.paid_on
                for payment in dated
                if payment.paid_on is not None
                and obligation_due_date < payment.paid_on < as_of_date
            }
        )
        marks = [obligation_due_date, *boundaries, as_of_date]

        periods: list[tuple[date, date, int, Decimal]] = []
        for start, end in zip(marks, marks[1:]):
            days = (end - start).days
            if days <= 0:
                continue
            paid_by_start = sum(
                (
                    payment.amount
                    for payment in dated
                    if payment.paid_on is not None and payment.paid_on <= start
                ),
                ZERO,
            )
            outstanding = base - undated_total - paid_by_start
            if outstanding < ZERO:
                outstanding = ZERO
            periods.append((start, end, days, outstanding))
        return periods

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
        payments_total = self._payments_total(financials)
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
        # the contract sum, the payments or the remaining balance there double-counts one and the
        # same operation. Only an unambiguous echo is dropped: a genuine separate amount (damages,
        # costs) that differs from every position already in the claim is kept in full.
        duplicate_candidates = {contract_amount, payments_total, principal}
        duplicate_candidates.update(financials.payments)
        duplicate_candidates.update(payment.amount for payment in financials.payment_schedule)
        other_excluded = (
            contract_amount is not None and other > ZERO and other in duplicate_candidates
        )
        if other_excluded:
            other = ZERO

        penalty = financials.penalty or ZERO
        penalty_days: int | None = None
        penalty_rate = financials.penalty_rate_percent_per_day
        penalty_cap_amount: Decimal | None = None
        penalty_cap_applied = False
        penalty_cap_base_ambiguous = False
        penalty_periods: list[PenaltyPeriod] = []

        dated = [
            payment for payment in financials.payment_schedule if payment.paid_on is not None
        ]
        undated_total = sum(financials.payments, ZERO) + sum(
            (
                payment.amount
                for payment in financials.payment_schedule
                if payment.paid_on is None
            ),
            ZERO,
        )
        # The balance the penalty starts from. With a contract sum it is the contract sum; without
        # one it is reconstructed from the stated remainder plus the payments that reduced it, so a
        # caller who only knows the balance keeps the previous behaviour exactly.
        if contract_amount is not None:
            base = contract_amount
        else:
            base = (financials.principal or ZERO) + sum(
                (payment.amount for payment in dated), ZERO
            )

        # A fully repaid debt still owes the penalty that accrued while it was unpaid, so accrual
        # depends on the balance during the delay, never on whether anything is left today.
        accrual_possible = base - undated_total > ZERO or principal > ZERO
        if (
            financials.penalty is None
            and accrual_possible
            and penalty_rate is not None
            and obligation_due_date is not None
            and as_of_date is not None
            and as_of_date > obligation_due_date
        ):
            penalty_days = (as_of_date - obligation_due_date).days
            raw_penalty = ZERO
            for start, end, days, outstanding in self._accrual_periods(
                base=base,
                undated_total=undated_total,
                dated=dated,
                obligation_due_date=obligation_due_date,
                as_of_date=as_of_date,
            ):
                amount = outstanding * penalty_rate / HUNDRED * Decimal(days)
                raw_penalty += amount
                penalty_periods.append(
                    PenaltyPeriod(
                        start=start,
                        end=end,
                        days=days,
                        outstanding=outstanding,
                        amount=amount.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP),
                    )
                )

            cap_percent = financials.penalty_cap_percent_of_principal
            if cap_percent is not None:
                # "Не более N% от суммы задолженности" can be read against the debt as it stood when
                # the delay began, or against whatever remains today. Both readings are computed;
                # which one applies is the recorded firm position, not a choice made here.
                defaulted_debt = base - undated_total
                remaining_balance = principal
                chosen = self.positions.decision("penalty_cap_base")
                cap_base = remaining_balance if chosen == "remaining_balance" else defaulted_debt
                other_base = defaulted_debt if chosen == "remaining_balance" else remaining_balance
                # A ceiling of zero would erase a penalty that genuinely accrued, so a fully repaid
                # debt falls back to the base that is still positive.
                if cap_base <= ZERO:
                    cap_base = other_base if other_base > ZERO else defaulted_debt

                penalty_cap_amount = (cap_base * cap_percent / HUNDRED).quantize(
                    MONEY_QUANT,
                    rounding=ROUND_HALF_UP,
                )
                # The readings only diverge once a payment lands during the delay, and only matter
                # when the ceiling actually binds under one of them. That is a question about the
                # contract's wording for this matter, so it is surfaced rather than settled here.
                alternative_cap = (other_base * cap_percent / HUNDRED).quantize(
                    MONEY_QUANT,
                    rounding=ROUND_HALF_UP,
                )
                penalty_cap_base_ambiguous = alternative_cap != penalty_cap_amount and (
                    raw_penalty > min(alternative_cap, penalty_cap_amount)
                )
                if raw_penalty > penalty_cap_amount:
                    raw_penalty = penalty_cap_amount
                    penalty_cap_applied = True

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
            penalty_cap_applied=penalty_cap_applied,
            penalty_cap_base_ambiguous=penalty_cap_base_ambiguous,
            penalty_periods=penalty_periods,
        )
