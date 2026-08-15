from datetime import date
from decimal import Decimal

from korgan_legal_ai.calculations.service import CalculationLayer
from korgan_legal_ai.domain.models import Financials


def test_money_is_deterministic():
    result = CalculationLayer().calculate_money(
        Financials(principal=Decimal("100"), penalty=Decimal("10"), interest=Decimal("5"))
    )
    assert result.total == Decimal("115")
    assert result.mismatch_with_user_total is False


def test_user_total_mismatch_is_detected():
    result = CalculationLayer().calculate_money(
        Financials(principal=Decimal("100"), user_stated_total=Decimal("101"))
    )
    assert result.mismatch_with_user_total is True


def test_daily_contract_penalty_is_calculated_from_locked_terms_and_dates():
    result = CalculationLayer().calculate_money(
        Financials(
            principal=Decimal("2400000"),
            penalty_rate_percent_per_day=Decimal("0.1"),
            penalty_cap_percent_of_principal=Decimal("10"),
        ),
        obligation_due_date=date(2026, 6, 10),
        as_of_date=date(2026, 8, 15),
    )

    assert result.penalty_days == 66
    assert result.penalty == Decimal("158400.00")
    assert result.penalty_cap_amount == Decimal("240000.00")
    assert result.total == Decimal("2558400.00")


def test_contract_penalty_cap_is_applied_deterministically():
    result = CalculationLayer().calculate_money(
        Financials(
            principal=Decimal("1000000"),
            penalty_rate_percent_per_day=Decimal("0.5"),
            penalty_cap_percent_of_principal=Decimal("10"),
        ),
        obligation_due_date=date(2026, 1, 1),
        as_of_date=date(2026, 2, 1),
    )

    assert result.penalty_days == 31
    assert result.penalty_cap_amount == Decimal("100000.00")
    assert result.penalty == Decimal("100000.00")
    assert result.total == Decimal("1100000.00")
