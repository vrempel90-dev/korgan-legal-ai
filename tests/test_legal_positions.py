"""A recorded firm position changes what the engine computes without a code change."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from korgan_legal_ai.calculations.service import CalculationLayer
from korgan_legal_ai.domain.models import Financials, Payment
from korgan_legal_ai.positions import KNOWN_QUESTIONS, LegalPosition, PositionRegistry
from korgan_legal_ai.positions.registry import load_positions, save_position

CAP_CASE = Financials(
    contract_amount=Decimal("12500000"),
    payment_schedule=[Payment(amount=Decimal("4500000"), paid_on=date(2026, 5, 25))],
    penalty_rate_percent_per_day=Decimal("0.2"),
    penalty_cap_percent_of_principal=Decimal("15"),
)
DUE = date(2026, 5, 20)
AS_OF = date(2026, 8, 15)


def _registry(decision: str) -> PositionRegistry:
    return PositionRegistry(
        version=1,
        positions={
            "penalty_cap_base": LegalPosition(
                key="penalty_cap_base",
                question=KNOWN_QUESTIONS["penalty_cap_base"][0],
                decision=decision,
                options=KNOWN_QUESTIONS["penalty_cap_base"][1],
                rationale="тестовая позиция",
                decided_by="тест",
                decided_at=date(2026, 8, 15),
            )
        },
    )


def _calculate(registry: PositionRegistry):
    return CalculationLayer(positions=registry).calculate_money(
        CAP_CASE, obligation_due_date=DUE, as_of_date=AS_OF
    )


def test_the_recorded_position_decides_which_debt_the_ceiling_applies_to() -> None:
    defaulted = _calculate(_registry("defaulted_debt"))
    remaining = _calculate(_registry("remaining_balance"))

    # 15% of the debt at default (12 500 000) versus 15% of what is left (8 000 000).
    assert defaulted.penalty_cap_amount == Decimal("1875000.00")
    assert remaining.penalty_cap_amount == Decimal("1200000.00")
    # The reading changes the amount actually claimed, which is exactly why it is recorded.
    assert defaulted.penalty == Decimal("1437000.00")
    assert remaining.penalty == Decimal("1200000.00")
    assert defaulted.total != remaining.total


def test_the_ambiguity_is_reported_under_either_reading() -> None:
    for decision in ("defaulted_debt", "remaining_balance"):
        result = _calculate(_registry(decision))
        # Recording a position settles what the engine does; it does not settle the contract.
        assert result.penalty_cap_base_ambiguous is True


def test_a_repaid_debt_never_gets_a_zero_ceiling_under_either_reading() -> None:
    repaid = Financials(
        contract_amount=Decimal("5000000"),
        payment_schedule=[Payment(amount=Decimal("5000000"), paid_on=date(2026, 5, 1))],
        penalty_rate_percent_per_day=Decimal("0.1"),
        penalty_cap_percent_of_principal=Decimal("10"),
    )
    for decision in ("defaulted_debt", "remaining_balance"):
        result = CalculationLayer(positions=_registry(decision)).calculate_money(
            repaid, obligation_due_date=date(2026, 3, 1), as_of_date=AS_OF
        )
        # A ceiling of zero would erase a penalty that genuinely accrued while the debt was unpaid.
        assert result.penalty_cap_amount == Decimal("500000.00")
        assert result.penalty == Decimal("305000.00")


def test_an_unrecorded_question_falls_back_to_the_documented_default() -> None:
    empty = PositionRegistry(version=1, positions={})

    assert empty.unanswered() == ("penalty_cap_base",)
    assert empty.decision("penalty_cap_base") == KNOWN_QUESTIONS["penalty_cap_base"][2]
    with pytest.raises(KeyError):
        empty.decision("no_such_question")


def test_a_position_outside_the_allowed_options_is_refused() -> None:
    invalid = LegalPosition(
        key="penalty_cap_base",
        question="q",
        decision="что-то третье",
        options=KNOWN_QUESTIONS["penalty_cap_base"][1],
        rationale="r",
        decided_by="кто-то",
        decided_at=date(2026, 8, 15),
    )

    assert any("не входит в допустимые" in problem for problem in invalid.validate())
    with pytest.raises(ValueError, match="не входит"):
        save_position(invalid)


def test_a_position_without_rationale_or_author_is_refused() -> None:
    """Who decided and why is the whole value of the record."""
    invalid = LegalPosition(
        key="penalty_cap_base",
        question="q",
        decision="defaulted_debt",
        options=KNOWN_QUESTIONS["penalty_cap_base"][1],
        rationale="",
        decided_by="",
        decided_at=date(2026, 8, 15),
    )

    problems = "; ".join(invalid.validate())
    assert "rationale" in problems
    assert "decided_by" in problems


def test_practice_backed_and_internal_positions_are_labelled_differently() -> None:
    common = {
        "key": "penalty_cap_base",
        "question": "q",
        "decision": "defaulted_debt",
        "options": KNOWN_QUESTIONS["penalty_cap_base"][1],
        "rationale": "r",
        "decided_by": "юротдел",
        "decided_at": date(2026, 8, 15),
    }
    internal = LegalPosition(**common)
    backed = LegalPosition(**common, practice_reference="СМЭС Алматы, дело № 2-1/2026")

    assert internal.source_label == "внутренняя позиция юридического отдела"
    assert backed.source_label == "СМЭС Алматы, дело № 2-1/2026"


def test_the_bundled_registry_loads_and_reports_what_is_still_open() -> None:
    registry = load_positions()

    # Every question the engine must answer is either recorded or listed as open — never silent.
    known = set(KNOWN_QUESTIONS)
    recorded = {position.key for position in registry.all()}
    assert recorded | set(registry.unanswered()) == known
