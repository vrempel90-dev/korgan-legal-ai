"""Блок 3: калькуляторы. Ставки берутся из конфигурационного файла, не из кода."""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from korgan.legal.calc import (  # noqa: E402
    EXEMPTION_CONSUMER,
    EXEMPTION_DISABILITY,
    RATES_PATH,
    ClaimComponent,
    RateUnavailable,
    claim_price,
    daily_penalty,
    load_rates,
    money_use_interest,
    state_duty,
)


@pytest.fixture()
def rates():
    return load_rates(RATES_PATH)


# --- конфигурация ------------------------------------------------------------


def test_rates_live_in_a_dated_config_file() -> None:
    payload = json.loads(RATES_PATH.read_text(encoding="utf-8"))

    assert "actual_on" in payload
    assert payload["state_duty"]["individual_rate"] == 0.01
    assert payload["state_duty"]["legal_entity_rate"] == 0.03


def test_every_rate_carries_a_source(rates) -> None:
    assert rates.duty_source
    assert all(entry.source for entry in rates.mrp)
    assert all(entry.source for entry in rates.nb_base_rate)


def test_rate_before_the_table_is_not_approximated(rates) -> None:
    with pytest.raises(RateUnavailable, match="базовая ставка"):
        rates.base_rate_on(date(2020, 1, 1))


def test_custom_config_overrides_defaults(tmp_path: Path) -> None:
    """Смена ставки — правка данных, а не кода."""
    payload = json.loads(RATES_PATH.read_text(encoding="utf-8"))
    payload["state_duty"]["individual_rate"] = 0.02
    config_path = tmp_path / "rates.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    duty = state_duty(1_000_000, rates=load_rates(config_path))

    assert duty.amount == 20_000


# --- цена иска ---------------------------------------------------------------


def test_claim_price_excludes_non_pecuniary_demands() -> None:
    price = claim_price(
        [
            ClaimComponent("Основной долг", 800_000),
            ClaimComponent("Неустойка", 120_000),
            ClaimComponent("Моральный вред", 500_000, pecuniary=False),
        ]
    )

    assert price.total == 920_000
    assert [item.title for item in price.excluded] == ["Моральный вред"]


def test_claim_price_breakdown_lists_components() -> None:
    price = claim_price([ClaimComponent("Основной долг", 800_000), ClaimComponent("Неустойка", 24_000)])

    assert "Основной долг — 800 000 тенге" in price.breakdown()
    assert price.breakdown().endswith("Итого цена иска: 824 000 тенге")


def test_negative_component_is_rejected() -> None:
    with pytest.raises(ValueError, match="отрицательная сумма"):
        claim_price([ClaimComponent("Ошибка", -1)])


# --- госпошлина --------------------------------------------------------------


def test_individual_pays_one_percent() -> None:
    assert state_duty(2_400_000).amount == 24_000


def test_legal_entity_pays_three_percent() -> None:
    assert state_duty(2_400_000, is_individual=False).amount == 72_000


def test_consumer_is_exempt_from_the_duty() -> None:
    """Освобождение потребителя: пошлина не начисляется вовсе."""
    duty = state_duty(920_000, exemptions=[EXEMPTION_CONSUMER])

    assert duty.exempt
    assert duty.amount == 0
    assert "защите прав потребителей" in duty.explain()


def test_disability_exemption_also_zeroes_the_duty() -> None:
    assert state_duty(5_000_000, exemptions=[EXEMPTION_DISABILITY]).amount == 0


def test_unknown_exemption_does_not_zero_the_duty() -> None:
    duty = state_duty(1_000_000, exemptions=["дальний_родственник_судьи"])

    assert not duty.exempt
    assert duty.amount == 10_000


def test_duty_is_capped_at_10000_mrp(rates) -> None:
    duty = state_duty(10_000_000_000, day=date(2026, 8, 16))

    assert duty.amount == duty.cap
    assert duty.cap == 10_000 * 4325


def test_duty_explanation_states_rate_and_source() -> None:
    explanation = state_duty(2_400_000).explain()

    assert "24 000 тенге" in explanation
    assert "665" in explanation


# --- неустойка по дням -------------------------------------------------------


def test_daily_penalty_accrues_per_day() -> None:
    penalty = daily_penalty(100_000, 10, rate_per_day=0.03)

    assert penalty.amount == 30_000
    assert not penalty.capped


def test_penalty_is_limited_by_the_order_price() -> None:
    """Ограничение неустойки ценой заказа: 50 дней по 3% дали бы 150%."""
    penalty = daily_penalty(400_000, 50, rate_per_day=0.03, cap=400_000)

    assert penalty.uncapped == 600_000
    assert penalty.amount == 400_000
    assert penalty.capped
    assert "ограничено ценой заказа" in penalty.formula()


def test_penalty_below_the_cap_is_not_touched() -> None:
    penalty = daily_penalty(400_000, 5, rate_per_day=0.03, cap=400_000)

    assert penalty.amount == 60_000
    assert not penalty.capped


def test_penalty_uses_the_configured_consumer_rate(rates) -> None:
    penalty = daily_penalty(100_000, 1)

    assert penalty.rate_per_day == rates.consumer_penalty_rate_per_day
    assert penalty.source


def test_zero_days_gives_no_penalty() -> None:
    assert daily_penalty(100_000, 0, rate_per_day=0.03).amount == 0


def test_negative_days_are_rejected() -> None:
    with pytest.raises(ValueError, match="дней просрочки"):
        daily_penalty(100_000, -1)


# --- проценты за пользование чужими деньгами ---------------------------------


def test_interest_uses_the_base_rate_effective_at_the_start() -> None:
    interest = money_use_interest(800_000, date(2026, 4, 11), date(2026, 8, 15))

    assert interest.annual_rate == 18.0
    assert interest.days == 127
    assert interest.amount == 50_104


def test_interest_after_the_june_cut_uses_the_lower_rate() -> None:
    interest = money_use_interest(800_000, date(2026, 6, 10), date(2026, 8, 15))

    assert interest.annual_rate == 17.0


def test_interest_period_and_formula_are_stated() -> None:
    interest = money_use_interest(800_000, date(2026, 4, 11), date(2026, 8, 15))

    assert interest.period() == "с 11.04.2026 по 15.08.2026"
    assert "800 000 тенге × 18% × 127 дн. / 365" in interest.formula()


def test_interest_without_a_configured_rate_raises() -> None:
    with pytest.raises(RateUnavailable):
        money_use_interest(800_000, date(2024, 1, 1), date(2024, 3, 1))


def test_explicit_rate_bypasses_the_table() -> None:
    interest = money_use_interest(100_000, date(2026, 4, 11), date(2027, 4, 10), annual_rate=10.0)

    assert interest.amount == 10_000
    assert not interest.verified


def test_end_before_start_is_rejected() -> None:
    with pytest.raises(ValueError, match="раньше его начала"):
        money_use_interest(100_000, date(2026, 4, 11), date(2026, 4, 10))
