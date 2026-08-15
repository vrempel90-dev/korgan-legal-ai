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
