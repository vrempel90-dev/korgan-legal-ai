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


def test_partial_payment_is_not_double_counted():
    """The contract sum is an input to the balance, never a second claimable position."""
    result = CalculationLayer().calculate_money(
        Financials(
            contract_amount=Decimal("3600000"),
            payments=[Decimal("1200000")],
            penalty=Decimal("158400"),
        )
    )

    assert result.principal == Decimal("2400000")
    assert result.payments_total == Decimal("1200000")
    # 2 400 000 + 158 400, not 2 400 000 + 158 400 + 3 600 000.
    assert result.total == Decimal("2558400")
    assert result.total != Decimal("6158400")


def test_no_payment_counts_the_contract_sum_once():
    result = CalculationLayer().calculate_money(
        Financials(contract_amount=Decimal("3600000"))
    )

    assert result.principal == Decimal("3600000")
    assert result.total == Decimal("3600000")


def test_multiple_partial_payments_are_all_subtracted():
    result = CalculationLayer().calculate_money(
        Financials(
            contract_amount=Decimal("3600000"),
            payments=[Decimal("600000"), Decimal("600000"), Decimal("300000")],
        )
    )

    assert result.payments_total == Decimal("1500000")
    assert result.principal == Decimal("2100000")


def test_full_payment_leaves_penalty_only():
    result = CalculationLayer().calculate_money(
        Financials(
            contract_amount=Decimal("3600000"),
            payments=[Decimal("3600000")],
            penalty=Decimal("237600"),
        )
    )

    assert result.principal == Decimal("0")
    assert result.total == Decimal("237600")


def test_overpayment_never_becomes_a_negative_debt():
    result = CalculationLayer().calculate_money(
        Financials(contract_amount=Decimal("1000000"), payments=[Decimal("1500000")])
    )

    assert result.principal == Decimal("0")
    assert result.total == Decimal("0")


def test_other_amount_echoing_the_contract_sum_is_excluded_and_flagged():
    result = CalculationLayer().calculate_money(
        Financials(
            contract_amount=Decimal("3600000"),
            payments=[Decimal("1200000")],
            penalty=Decimal("158400"),
            other=Decimal("3600000"),
        )
    )

    assert result.other == Decimal("0")
    assert result.other_excluded_as_duplicate is True
    assert result.total == Decimal("2558400")


def test_genuine_other_amount_is_kept_intact():
    """An amount truly outside the debt is not touched by the duplicate guard."""
    result = CalculationLayer().calculate_money(
        Financials(
            contract_amount=Decimal("3600000"),
            payments=[Decimal("1200000")],
            other=Decimal("450000"),
        )
    )

    assert result.other == Decimal("450000")
    assert result.other_excluded_as_duplicate is False
    assert result.total == Decimal("2850000")


def test_stated_principal_conflicting_with_payments_is_flagged_not_silently_used():
    result = CalculationLayer().calculate_money(
        Financials(
            contract_amount=Decimal("3600000"),
            payments=[Decimal("1200000")],
            principal=Decimal("3600000"),
        )
    )

    assert result.principal == Decimal("2400000")
    assert result.principal_conflicts_with_payments is True


def test_explicit_principal_without_contract_sum_still_works():
    """Existing callers that only know the balance keep their behaviour."""
    result = CalculationLayer().calculate_money(
        Financials(principal=Decimal("100"), penalty=Decimal("10"))
    )

    assert result.principal == Decimal("100")
    assert result.contract_amount is None
    assert result.principal_conflicts_with_payments is False
    assert result.total == Decimal("110")


def test_claim_block_shows_the_derivation_and_omits_empty_positions():
    """The drafted block must make the subtraction visible and never print a zero filler row."""
    from korgan_legal_ai.domain.models import (
        DocumentType,
        EvidenceMap,
        Fact,
        LockedCase,
        Party,
        PartyRole,
        ProceduralReport,
        ProcedureFacts,
    )
    from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter

    case = LockedCase(
        raw_text="test",
        parties=[
            Party(name="ТОО Истец", role=PartyRole.CLAIMANT),
            Party(name="ТОО Ответчик", role=PartyRole.DEFENDANT),
        ],
        facts=[Fact(statement="Оплата не поступила")],
        financials=Financials(
            contract_amount=Decimal("3600000"),
            payments=[Decimal("1200000")],
            penalty=Decimal("158400"),
        ),
        procedure=ProcedureFacts(),
    )
    calculation = CalculationLayer().calculate_money(case.financials)
    document = DebtClaimDrafter().draft(
        case,
        ProceduralReport(items=[]),
        EvidenceMap(links=[]),
        calculation,
    )

    assert document.document_type == DocumentType.CLAIM
    text = document.text
    assert "Стоимость по договору: 3600000 KZT" in text
    assert "Оплачено: 1200000 KZT" in text
    assert "Основной долг: 2400000 KZT" in text
    assert "Итого: 2558400 KZT" in text
    # No empty catch-all rows that invite a duplicate to be filled in.
    assert "Иные суммы" not in text
    assert "Проценты" not in text
    assert "3600000 KZT\nИтого" not in text
