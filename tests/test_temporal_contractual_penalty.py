from datetime import date

import pytest

from korgan.contractual_penalty import calc_temporal_contractual_penalty


def test_f2_supply_cap_reached_on_100th_delay_day() -> None:
    result = calc_temporal_contractual_penalty(
        base_amount=3_250_000,
        due_date=date(2026, 3, 7),
        rate_percent_per_day=0.2,
        cap_percent=20,
        payments=[],
        as_of_date=date(2026, 8, 25),
    )

    assert len(result.segments) == 1
    assert result.segments[0] == {
        "from": date(2026, 3, 8),
        "to": date(2026, 8, 25),
        "base": 3_250_000,
        "rate_per_day": 6_500,
        "days": 171,
        "amount": 1_111_500,
    }
    assert result.total_before_cap == 1_111_500
    assert result.cap_amount == 650_000
    assert result.cap_reached_date == date(2026, 6, 15)
    assert result.total == 650_000
    assert result.daily_after == 0
    assert result.outstanding_principal == 3_250_000
    assert result.no_penalty_clause is False
    assert result.convention["delay_start"] == "due_date + 1 calendar day"


def test_f3_services_partial_payment_changes_base_next_day() -> None:
    result = calc_temporal_contractual_penalty(
        base_amount=1_800_000,
        due_date=date(2026, 1, 20),
        rate_percent_per_day=0.1,
        cap_percent=None,
        payments=[(date(2026, 2, 28), 600_000)],
        as_of_date=date(2026, 8, 25),
    )

    assert result.segments == [
        {
            "from": date(2026, 1, 21),
            "to": date(2026, 2, 28),
            "base": 1_800_000,
            "rate_per_day": 1_800,
            "days": 39,
            "amount": 70_200,
        },
        {
            "from": date(2026, 3, 1),
            "to": date(2026, 8, 25),
            "base": 1_200_000,
            "rate_per_day": 1_200,
            "days": 178,
            "amount": 213_600,
        },
    ]
    assert result.total_before_cap == 283_800
    assert result.cap_amount is None
    assert result.cap_reached_date is None
    assert result.total == 283_800
    assert result.daily_after == 1_200
    assert result.outstanding_principal == 1_200_000
    assert result.convention["payment_day_base"] == "old principal applies on the payment date"
    assert result.convention["payment_effective"] == "payment reduces the accrual base from the next calendar day"
    assert result.convention["payment_allocation"] == "principal"


def test_f1_without_penalty_clause_does_not_invent_rate() -> None:
    result = calc_temporal_contractual_penalty(
        base_amount=8_400_000,
        due_date=date(2026, 1, 20),
        rate_percent_per_day=None,
        cap_percent=None,
        payments=[],
        as_of_date=date(2026, 8, 25),
    )

    assert result.segments == []
    assert result.total_before_cap is None
    assert result.total is None
    assert result.no_penalty_clause is True
    assert result.daily_after == 0
    assert result.outstanding_principal == 8_400_000


def test_payment_allocation_is_explicit_and_unsupported_policy_fails_closed() -> None:
    with pytest.raises(ValueError, match="Неподдерживаемый порядок погашения"):
        calc_temporal_contractual_penalty(
            base_amount=1_000_000,
            due_date=date(2026, 1, 1),
            rate_percent_per_day=0.1,
            cap_percent=None,
            payments=[],
            as_of_date=date(2026, 1, 2),
            payment_allocation="penalty_first",
        )
