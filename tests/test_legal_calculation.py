"""Каждое денежное требование должно быть перепроверяемо юристом до тенге."""

from __future__ import annotations

from datetime import date

import pytest

from korgan.contractual_penalty import (
    ContractualPenaltyTerms,
    calc_contractual_penalty,
    parse_contractual_penalty_terms,
)
from korgan.legal_calculation import (
    CalculationGap,
    MoneyComponent,
    contractual_penalty_component,
    court_costs_component,
    late_interest_component,
    legal_services_component,
    principal_component,
    render_calculation,
    total_claim_price,
)
from korgan.legal_calc import calc_late_payment_penalty


def test_principal_component_shows_base_and_amount() -> None:
    component = principal_component(2_300_000, basis="договор подряда № 12 от 15.01.2026")

    assert component.amount == 2_300_000
    assert component.basis == "договор подряда № 12 от 15.01.2026"
    assert component.included_in_claim_price is True
    line = component.render()
    assert "2 300 000 тенге" in line
    assert "договор подряда № 12 от 15.01.2026" in line


def test_contractual_penalty_component_exposes_every_element() -> None:
    terms = ContractualPenaltyTerms(rate_percent_per_day=0.1, cap_percent=None, clause="6.3")
    penalty = calc_contractual_penalty(2_300_000, terms, date(2026, 3, 1), date(2026, 3, 31))
    component = contractual_penalty_component(penalty)

    assert component.penalty_base == 2_300_000
    assert component.penalty_rate == "0,1% за каждый день просрочки"
    assert component.start_date == date(2026, 3, 1)
    assert component.end_date == date(2026, 3, 31)
    assert component.days == 31
    assert component.amount == 71_300
    assert "пункт 6.3 договора" in component.basis
    line = component.render()
    assert "2 300 000 тенге × 0,1% × 31 дн. = 71 300 тенге" in line
    assert "01.03.2026" in line and "31.03.2026" in line


def test_contractual_penalty_cap_is_visible_in_the_calculation() -> None:
    terms = ContractualPenaltyTerms(rate_percent_per_day=0.5, cap_percent=10.0, clause="6.3")
    penalty = calc_contractual_penalty(1_000_000, terms, date(2026, 1, 1), date(2026, 3, 1))
    component = contractual_penalty_component(penalty)

    assert component.amount == 100_000
    assert "не более 10% " in component.render() or "не более 10%" in component.render()


def test_parser_integer_percent_cap_renders_without_losing_trailing_zero() -> None:
    terms = parse_contractual_penalty_terms(
        "Пунктом 6.3 договора предусмотрена неустойка 0,1% от суммы задолженности "
        "за каждый день просрочки, но не более 10% от суммы задолженности."
    )
    assert terms is not None

    penalty = calc_contractual_penalty(
        1_000_000,
        terms,
        date(2026, 1, 1),
        date(2026, 3, 1),
    )
    rendered = contractual_penalty_component(penalty).render()

    assert "не более 10%" in rendered
    assert "не более 1%" not in rendered


def test_late_interest_component_names_article_353() -> None:
    penalty = calc_late_payment_penalty(
        1_000_000, date(2026, 1, 1), date(2026, 1, 31), rate_date=date(2026, 1, 1)
    )
    assert penalty is not None
    component = late_interest_component(penalty)

    assert component.days == 31
    assert component.penalty_base == 1_000_000
    assert "353" in component.basis
    assert "базовая ставка" in component.penalty_rate


def test_legal_services_and_court_costs_are_separate_positions() -> None:
    services = legal_services_component(150_000, basis="договор об оказании юридических услуг от 01.02.2026")
    costs = court_costs_component(24_000, basis="платёжное поручение об уплате госпошлины")

    assert services.included_in_claim_price is False
    assert costs.included_in_claim_price is False
    assert "150 000 тенге" in services.render()
    assert "24 000 тенге" in costs.render()


def test_claim_price_counts_only_components_included_in_it() -> None:
    components = [
        principal_component(2_300_000, basis="договор"),
        legal_services_component(150_000, basis="договор об услугах"),
        court_costs_component(24_000, basis="госпошлина"),
    ]
    assert total_claim_price(components) == 2_300_000


def test_rendering_is_byte_identical_for_the_same_input() -> None:
    def build() -> list[MoneyComponent]:
        terms = ContractualPenaltyTerms(rate_percent_per_day=0.1, cap_percent=None, clause="6.3")
        penalty = calc_contractual_penalty(2_300_000, terms, date(2026, 3, 1), date(2026, 3, 31))
        return [
            principal_component(2_300_000, basis="договор подряда № 12"),
            contractual_penalty_component(penalty),
            legal_services_component(150_000, basis="договор об услугах"),
        ]

    assert render_calculation(build()) == render_calculation(build())


def test_rendered_calculation_ends_with_a_reconcilable_total() -> None:
    terms = ContractualPenaltyTerms(rate_percent_per_day=0.1, cap_percent=None, clause="6.3")
    penalty = calc_contractual_penalty(2_300_000, terms, date(2026, 3, 1), date(2026, 3, 31))
    lines = render_calculation([
        principal_component(2_300_000, basis="договор подряда № 12"),
        contractual_penalty_component(penalty),
        legal_services_component(150_000, basis="договор об услугах"),
    ])

    assert any("Итого цена иска: 2 371 300 тенге" in line for line in lines)
    assert any("150 000 тенге" in line and "не входит в цену иска" in line for line in lines)


# --- отказ считать при нехватке данных ------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected_gap"),
    [
        ({"principal": 0}, "не установлена сумма основного долга"),
        ({"rate_percent_per_day": None}, "не установлена ставка договорной неустойки"),
        ({"start": None}, "не установлена дата начала просрочки"),
        ({"end": None}, "не установлена дата окончания периода просрочки"),
    ],
)
def test_missing_element_is_reported_not_invented(kwargs: dict, expected_gap: str) -> None:
    from korgan.legal_calculation import try_contractual_penalty_component

    base = {
        "principal": 2_300_000,
        "rate_percent_per_day": 0.1,
        "cap_percent": None,
        "clause": "6.3",
        "start": date(2026, 3, 1),
        "end": date(2026, 3, 31),
    }
    base.update(kwargs)

    result = try_contractual_penalty_component(**base)

    assert isinstance(result, CalculationGap)
    assert result.note == expected_gap
    assert result.amount is None


def test_a_complete_input_produces_a_component_not_a_gap() -> None:
    from korgan.legal_calculation import try_contractual_penalty_component

    result = try_contractual_penalty_component(
        principal=2_300_000,
        rate_percent_per_day=0.1,
        cap_percent=None,
        clause="6.3",
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
    )
    assert isinstance(result, MoneyComponent)
    assert result.amount == 71_300


def test_contractual_penalty_rounds_half_up_not_to_even() -> None:
    """Ровно половина тенге округляется вверх, как в бухгалтерском расчёте.

    Встроенный round() в Python округляет половину к чётному: 100 тенге под
    0,5% за один день дают ровно 0.5 тенге, и float-путь вернул бы 0. Юрист,
    перепроверяющий расчёт на калькуляторе, получит 1.
    """
    terms = ContractualPenaltyTerms(rate_percent_per_day=0.5, cap_percent=None, clause="5.1")
    penalty = calc_contractual_penalty(100, terms, date(2026, 1, 1), date(2026, 1, 1))

    assert penalty.amount == 1


def test_contractual_penalty_cap_rounds_half_up_too() -> None:
    """Потолок неустойки считается той же арифметикой, что и сама неустойка."""
    terms = ContractualPenaltyTerms(rate_percent_per_day=1.0, cap_percent=0.05, clause="5.1")
    penalty = calc_contractual_penalty(1_000, terms, date(2026, 1, 1), date(2026, 12, 31))

    assert penalty.cap_amount == 1
    assert penalty.amount == 1
    assert penalty.capped is True


def test_contractual_penalty_keeps_precision_above_float_limit() -> None:
    terms = ContractualPenaltyTerms(rate_percent_per_day=0.07, cap_percent=None, clause="5.1")
    penalty = calc_contractual_penalty(9_007_199_254_740_993, terms, date(2026, 1, 1), date(2026, 1, 1))

    # 9007199254740993 × 0.07 / 100 = 6305039478318.6951 -> 6305039478319
    assert penalty.amount == 6_305_039_478_319


def test_contractual_penalty_never_replaces_the_agreed_rate_with_article_353() -> None:
    """Договорная ставка должна остаться договорной, даже если она мельче."""
    terms = ContractualPenaltyTerms(rate_percent_per_day=0.01, cap_percent=None, clause="6.3")
    penalty = calc_contractual_penalty(1_000_000, terms, date(2026, 1, 1), date(2026, 1, 31))
    component = contractual_penalty_component(penalty)

    assert "0,01%" in component.penalty_rate
    assert "353" not in component.render()
