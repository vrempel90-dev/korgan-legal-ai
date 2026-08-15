"""Неустойка за просрочку по ст. 353 ГК РК: считает код, а не модель."""

from datetime import date

import pytest

from korgan.legal_calc import (
    NEEDS_RATE_MARKER,
    base_rate_on,
    calc_late_payment_interest,
    late_interest_line,
)

# Дело № 3: расписка на 800 000 тенге, срок возврата — 10.04.2026.
DELO_3_PRINCIPAL = 800_000
DELO_3_DELAY_START = date(2026, 4, 11)


def test_base_rate_is_18_percent_before_june_2026_cut() -> None:
    assert base_rate_on(date(2026, 4, 10)) == 18.0
    assert base_rate_on(date(2026, 6, 4)) == 18.0


def test_base_rate_drops_to_17_percent_from_5_june_2026() -> None:
    assert base_rate_on(date(2026, 6, 5)) == 17.0


def test_base_rate_before_table_is_unknown() -> None:
    """Ставка до 10.10.2025 в справочнике отсутствует — угадывать её нельзя."""
    assert base_rate_on(date(2025, 1, 1)) is None


def test_delo_3_interest_uses_rate_on_due_date() -> None:
    interest = calc_late_payment_interest(DELO_3_PRINCIPAL, DELO_3_DELAY_START, date(2026, 8, 15))

    assert interest is not None
    assert interest.rate_percent == 18.0
    assert interest.days == 127
    # 800 000 × 18% × 127 / 365
    assert interest.amount == round(800_000 * 0.18 * 127 / 365)


def test_single_day_of_delay_is_counted() -> None:
    interest = calc_late_payment_interest(DELO_3_PRINCIPAL, DELO_3_DELAY_START, DELO_3_DELAY_START)

    assert interest is not None
    assert interest.days == 1


def test_unknown_rate_returns_none_not_a_guess() -> None:
    assert calc_late_payment_interest(DELO_3_PRINCIPAL, date(2025, 2, 1), date(2025, 3, 1)) is None


def test_explicit_rate_overrides_the_table() -> None:
    interest = calc_late_payment_interest(100_000, date(2026, 4, 11), date(2027, 4, 10), rate_percent=10.0)

    assert interest is not None
    assert interest.rate_percent == 10.0
    assert interest.amount == 10_000


def test_end_before_start_is_rejected() -> None:
    with pytest.raises(ValueError):
        calc_late_payment_interest(DELO_3_PRINCIPAL, date(2026, 4, 11), date(2026, 4, 10))


def test_non_positive_principal_is_rejected() -> None:
    with pytest.raises(ValueError):
        calc_late_payment_interest(0, date(2026, 4, 11), date(2026, 8, 15))


def test_line_states_period_rate_and_article() -> None:
    line = late_interest_line(calc_late_payment_interest(DELO_3_PRINCIPAL, DELO_3_DELAY_START, date(2026, 8, 15)))

    assert "11.04.2026" in line
    assert "15.08.2026" in line
    assert "18%" in line
    assert "353" in line


def test_line_without_rate_flags_only_the_rate() -> None:
    line = late_interest_line(None)

    assert line == NEEDS_RATE_MARKER
    assert "353" not in line
