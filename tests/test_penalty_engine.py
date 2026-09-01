"""Обязательные регрессионные проверки расчёта неустойки.

Каждая проверка соответствует ошибке, которая в реальном иске стоит денег или
самого иска: перепутанный порядок ставки, неучтённая частичная оплата, неустойка
на уже погашенный долг, предел из ниоткуда, статья без источника. Числа здесь
посчитаны вручную и записаны литералами — если сверять их выражением на тех же
операциях, что и в модуле, проверка подтвердит любую арифметику, включая
неверную.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from korgan.calculation_document_gate import (
    DocumentAmounts,
    check_calculation_against_document,
)
from korgan.penalty_engine import (
    CalculationStatus,
    PenaltyTerms,
    PrincipalEvent,
    RateType,
    calculate_penalty,
)


def daily(rate: str = "0.1", **kwargs) -> PenaltyTerms:
    """Обычное договорное условие: процент за каждый день просрочки."""
    options = {
        "contract_basis": "пункт 5.2 договора",
        "rate_source": "пункт 5.2 договора поставки № 12 от 01.02.2026",
    }
    options.update(kwargs)
    return PenaltyTerms(rate=Decimal(rate), rate_type=RateType.PER_DAY, **options)


# 1. Порядок величины ставки.

def test_tenth_of_a_percent_per_day_is_one_thousandth_not_one_tenth() -> None:
    """0,1% в день — это 0,001 от долга, а не 0,1.

    Ошибка в сто раз не выглядит ошибкой: сумма остаётся правдоподобной,
    просто иск подаётся на неустойку, равную всему долгу за десять дней.
    """
    result = calculate_penalty(1_000_000, date(2026, 3, 1), date(2026, 3, 10), daily())

    assert result.status is CalculationStatus.CALCULATED
    assert result.total == 10_000
    assert result.total != 1_000_000


# 2. Один долг, оплат не было.

def test_single_debt_without_payments_is_one_interval() -> None:
    result = calculate_penalty(2_000_000, date(2026, 3, 1), date(2026, 3, 31), daily())

    assert result.total == 62_000
    assert len(result.intervals) == 1
    assert result.intervals[0].days == 31


# 3. Одна частичная оплата.

def test_partial_payment_splits_the_period_and_lowers_the_base() -> None:
    """После частичной оплаты неустойка идёт на остаток, а не на весь долг."""
    result = calculate_penalty(
        2_000_000,
        date(2026, 3, 1),
        date(2026, 3, 20),
        daily(),
        events=[PrincipalEvent(date(2026, 3, 11), -500_000, basis="платёжное поручение № 4")],
    )

    assert [(i.period_from, i.period_to, i.principal, i.subtotal) for i in result.intervals] == [
        (date(2026, 3, 1), date(2026, 3, 10), 2_000_000, 20_000),
        (date(2026, 3, 11), date(2026, 3, 20), 1_500_000, 15_000),
    ]
    assert result.total == 35_000
    assert "платёжное поручение № 4" in result.intervals[0].event_ending_period


# 4. Несколько частичных оплат.

def test_several_partial_payments_produce_several_intervals() -> None:
    result = calculate_penalty(
        3_000_000,
        date(2026, 1, 1),
        date(2026, 1, 31),
        daily(),
        events=[
            PrincipalEvent(date(2026, 1, 11), -1_000_000, basis="платёж № 1"),
            PrincipalEvent(date(2026, 1, 21), -1_000_000, basis="платёж № 2"),
        ],
    )

    assert [(i.days, i.principal, i.subtotal) for i in result.intervals] == [
        (10, 3_000_000, 30_000),
        (10, 2_000_000, 20_000),
        (11, 1_000_000, 11_000),
    ]
    assert result.total == 61_000


# 5. Полное погашение внутри периода.

def test_full_repayment_stops_the_accrual_that_day() -> None:
    """После погашения неустойка не начисляется — начислять не на что."""
    result = calculate_penalty(
        1_000_000,
        date(2026, 3, 1),
        date(2026, 3, 31),
        daily(),
        events=[PrincipalEvent(date(2026, 3, 16), -1_000_000, basis="платёж")],
    )

    assert len(result.intervals) == 1
    assert result.intervals[0].period_to == date(2026, 3, 15)
    assert result.total == 15_000


# 6. Разный размер долга в разные периоды.

def test_additional_supply_raises_the_base_from_its_own_date() -> None:
    result = calculate_penalty(
        1_000_000,
        date(2026, 2, 1),
        date(2026, 2, 20),
        daily(),
        events=[PrincipalEvent(date(2026, 2, 11), 500_000, basis="накладная № 7", kind="supply")],
    )

    assert [(i.principal, i.subtotal) for i in result.intervals] == [
        (1_000_000, 10_000),
        (1_500_000, 15_000),
    ]
    assert result.total == 25_000


# 7. Клиент ошибся в числе дней.

def test_client_miscounted_days_does_not_change_the_result() -> None:
    result = calculate_penalty(
        2_000_000,
        date(2026, 3, 1),
        date(2026, 3, 31),
        daily(),
        claimed_amount=80_000,  # клиент посчитал 40 дней вместо 31
    )

    assert result.total == 62_000
    assert result.claim_matches is False


# 8. Клиент ошибся в размере неустойки.

def test_client_amount_never_overrides_the_calculation() -> None:
    result = calculate_penalty(
        1_000_000, date(2026, 3, 1), date(2026, 3, 10), daily(), claimed_amount=100_000
    )

    assert result.total == 10_000
    assert result.claimed_amount == 100_000
    assert result.claim_matches is False


# 9. Неверная база: вся цена договора вместо остатка.

def test_payments_made_before_the_delay_reduce_the_opening_base() -> None:
    """Просрочена часть цены — неустойка считается от неё, а не от всей цены."""
    result = calculate_penalty(
        5_000_000,
        date(2026, 3, 1),
        date(2026, 3, 10),
        daily(),
        events=[PrincipalEvent(date(2026, 2, 20), -3_000_000, basis="платёж до просрочки")],
    )

    assert result.intervals[0].principal == 2_000_000
    assert result.total == 20_000
    assert result.total != 50_000


# 10. Договорной ставки нет.

def test_penalty_without_any_basis_is_not_calculated() -> None:
    terms = PenaltyTerms(
        rate=Decimal("0.1"), rate_type=RateType.PER_DAY, rate_source="со слов клиента"
    )
    result = calculate_penalty(1_000_000, date(2026, 3, 1), date(2026, 3, 10), terms)

    assert result.status is CalculationStatus.NEEDS_VERIFICATION
    assert result.total == 0
    assert any("основание" in reason for reason in result.reasons)


# 11. Ставка есть, но за другое нарушение.

def test_rate_for_another_breach_is_not_applied() -> None:
    """Пункт о просрочке поставки не взыскивает неустойку за просрочку оплаты."""
    result = calculate_penalty(
        1_000_000,
        date(2026, 3, 1),
        date(2026, 3, 10),
        daily(breach="просрочка поставки"),
        breach="просрочка оплаты",
    )

    assert result.status is CalculationStatus.NEEDS_VERIFICATION
    assert any("просрочка поставки" in reason for reason in result.reasons)


# 12. Максимальный договорной предел.

def test_confirmed_contractual_cap_limits_the_claim() -> None:
    result = calculate_penalty(
        1_000_000,
        date(2026, 1, 1),
        date(2026, 12, 31),
        daily(cap_percent=Decimal(10), cap_verified=True),
    )

    assert result.raw_total == 365_000
    assert result.cap_amount == 100_000
    assert result.total == 100_000
    assert result.capped is True


# 13. Законный предел — только при подтверждении.

def test_unconfirmed_cap_blocks_the_calculation_instead_of_being_applied() -> None:
    result = calculate_penalty(
        1_000_000,
        date(2026, 1, 1),
        date(2026, 12, 31),
        daily(cap_percent=Decimal(10)),
    )

    assert result.status is CalculationStatus.NEEDS_VERIFICATION
    assert result.total == result.raw_total == 365_000
    assert result.cap_amount == 100_000
    assert any("предел" in reason for reason in result.reasons)


# 14. Период проходит через конец месяца и года.

def test_period_across_the_year_boundary_counts_calendar_days() -> None:
    result = calculate_penalty(1_000_000, date(2025, 12, 25), date(2026, 1, 5), daily())

    assert result.intervals[0].days == 12
    assert result.total == 12_000


# 15. Високосный год.

def test_leap_year_has_three_hundred_sixty_six_days() -> None:
    """366 дней просрочки — это 366, даже если в году договора их 365."""
    result = calculate_penalty(
        1_000_000,
        date(2028, 1, 1),
        date(2028, 12, 31),
        PenaltyTerms(
            rate=Decimal(18),
            rate_type=RateType.PER_YEAR,
            legal_basis="статья 353 Гражданского кодекса Республики Казахстан",
            legal_basis_source="adilet.zan.kz, ГК РК (Особенная часть)",
            rate_source="базовая ставка Национального Банка Республики Казахстан",
        ),
    )

    assert result.intervals[0].days == 366
    assert result.total == 180_493


# 16. Один день просрочки.

def test_a_single_day_of_delay_is_one_day() -> None:
    result = calculate_penalty(1_000_000, date(2026, 3, 1), date(2026, 3, 1), daily())

    assert result.intervals[0].days == 1
    assert result.total == 1_000


# 17. Нулевая просрочка.

def test_zero_delay_gives_zero_without_a_verification_marker() -> None:
    """Отсутствие просрочки — это ноль, а не повод для ручной проверки."""
    result = calculate_penalty(1_000_000, date(2026, 3, 10), date(2026, 3, 9), daily())

    assert result.status is CalculationStatus.CALCULATED
    assert result.intervals == ()
    assert result.total == 0


# 18. Просрочка ещё не наступила.

def test_delay_that_has_not_started_yet_accrues_nothing() -> None:
    result = calculate_penalty(1_000_000, date(2026, 12, 1), date(2026, 9, 1), daily())

    assert result.total == 0
    assert result.status is CalculationStatus.CALCULATED


# 19. Переплата или отсутствие долга.

def test_overpayment_is_not_a_penalty_it_is_a_question_to_the_lawyer() -> None:
    result = calculate_penalty(
        1_000_000,
        date(2026, 3, 1),
        date(2026, 3, 10),
        daily(),
        events=[PrincipalEvent(date(2026, 2, 1), -1_200_000, basis="платёж")],
    )

    assert result.status is CalculationStatus.NEEDS_VERIFICATION
    assert result.total == 0


# 20. Некорректные исходные данные.

def test_impossible_inputs_raise_instead_of_producing_a_number() -> None:
    with pytest.raises(ValueError):
        calculate_penalty(-1, date(2026, 3, 1), date(2026, 3, 10), daily())
    with pytest.raises(ValueError):
        calculate_penalty(1_000_000, "01.03.2026", date(2026, 3, 10), daily())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        daily(rate="0")
    with pytest.raises(ValueError):
        PrincipalEvent(date(2026, 3, 1), 0, basis="ничего")
    with pytest.raises(ValueError):
        daily(cap_amount=100_000, cap_percent=Decimal(10))


# 21 и 22. Русское и казахское дело считаются одинаково.

def test_the_language_of_the_case_does_not_change_the_arithmetic() -> None:
    """Числа не зависят от языка формулировок — иначе казахское дело считалось
    бы по другой ветке кода, которую никто не проверяет."""
    russian = calculate_penalty(
        2_000_000,
        date(2026, 3, 1),
        date(2026, 3, 20),
        daily(
            contract_basis="пункт 5.2 договора",
            rate_source="пункт 5.2 договора поставки № 12 от 01.02.2026",
        ),
        events=[PrincipalEvent(date(2026, 3, 11), -500_000, basis="платёжное поручение")],
    )
    kazakh = calculate_penalty(
        2_000_000,
        date(2026, 3, 1),
        date(2026, 3, 20),
        daily(
            contract_basis="шарттың 5.2-тармағы",
            rate_source="01.02.2026 жылғы № 12 жеткізу шартының 5.2-тармағы",
        ),
        events=[PrincipalEvent(date(2026, 3, 11), -500_000, basis="төлем тапсырмасы")],
    )

    assert russian.total == kazakh.total == 35_000
    assert [i.subtotal for i in russian.intervals] == [i.subtotal for i in kazakh.intervals]


# 23. Расчёт не совпал с просительной частью.

def test_document_is_blocked_when_the_relief_does_not_match_the_calculation() -> None:
    result = calculate_penalty(2_000_000, date(2026, 3, 1), date(2026, 3, 31), daily())
    gate = check_calculation_against_document(
        result,
        DocumentAmounts(
            principal_in_document=2_000_000,
            penalty_in_reasoning=62_000,
            penalty_in_calculation=62_000,
            penalty_in_relief=70_000,  # просительную часть правили отдельно
            principal_in_relief=2_000_000,
            total_in_relief=2_070_000,
        ),
        principal=2_000_000,
    )

    assert gate.ready is False
    assert any("просительной части" in reason for reason in gate.reasons)


def test_document_passes_when_every_figure_agrees() -> None:
    result = calculate_penalty(2_000_000, date(2026, 3, 1), date(2026, 3, 31), daily())
    gate = check_calculation_against_document(
        result,
        DocumentAmounts(
            principal_in_document=2_000_000,
            penalty_in_reasoning=62_000,
            penalty_in_calculation=62_000,
            penalty_in_relief=62_000,
            principal_in_relief=2_000_000,
            total_in_relief=2_062_000,
        ),
        principal=2_000_000,
    )

    assert gate.ready is True
    assert gate.reasons == ()


# 24. Статья не подтверждена официальным источником.

def test_unverified_article_blocks_the_document() -> None:
    """Статью нельзя поставить в иск только потому, что модель её помнит."""
    terms = PenaltyTerms(
        rate=Decimal(18),
        rate_type=RateType.PER_YEAR,
        legal_basis="статья 353 Гражданского кодекса Республики Казахстан",
        rate_source="базовая ставка Национального Банка Республики Казахстан",
    )
    result = calculate_penalty(1_000_000, date(2026, 3, 1), date(2026, 3, 31), terms)

    assert result.status is CalculationStatus.NEEDS_VERIFICATION
    assert any("официальным источником" in reason for reason in result.reasons)

    gate = check_calculation_against_document(
        result,
        DocumentAmounts(
            principal_in_document=1_000_000,
            penalty_in_reasoning=0,
            penalty_in_calculation=0,
            penalty_in_relief=0,
            principal_in_relief=1_000_000,
            total_in_relief=1_000_000,
        ),
        principal=1_000_000,
    )
    assert gate.ready is False


# 25. Ставка не подтверждена.

def test_unverified_rate_blocks_the_document() -> None:
    terms = PenaltyTerms(
        rate=Decimal("0.5"),
        rate_type=RateType.PER_DAY,
        contract_basis="пункт 5.2 договора",
    )
    result = calculate_penalty(1_000_000, date(2026, 3, 1), date(2026, 3, 31), terms)

    assert result.status is CalculationStatus.NEEDS_VERIFICATION
    assert any("ставка" in reason for reason in result.reasons)

    gate = check_calculation_against_document(
        result,
        DocumentAmounts(
            principal_in_document=1_000_000,
            penalty_in_reasoning=0,
            penalty_in_calculation=0,
            penalty_in_relief=0,
            principal_in_relief=1_000_000,
            total_in_relief=1_000_000,
        ),
        principal=1_000_000,
    )
    assert gate.ready is False


# Дополнительно: месячная ставка режется по календарным месяцам.

def test_monthly_rate_is_prorated_by_the_actual_length_of_each_month() -> None:
    """«Месяц» с 15 февраля по 15 марта — не месяц, а два неполных."""
    result = calculate_penalty(
        1_000_000,
        date(2026, 2, 15),
        date(2026, 3, 15),
        PenaltyTerms(
            rate=Decimal(3),
            rate_type=RateType.PER_MONTH,
            contract_basis="пункт 6.1 договора",
            rate_source="пункт 6.1 договора аренды № 3 от 10.01.2026",
        ),
    )

    # 14 дней февраля из 28 и 15 дней марта из 31.
    assert [(i.days, i.subtotal) for i in result.intervals] == [(14, 15_000), (15, 14_516)]
    assert result.total == 29_516


def test_the_calculation_table_carries_every_field_the_document_needs() -> None:
    result = calculate_penalty(
        2_000_000,
        date(2026, 3, 1),
        date(2026, 3, 20),
        daily(),
        events=[PrincipalEvent(date(2026, 3, 11), -500_000, basis="платёжное поручение № 4")],
    )
    rows = result.table()

    assert len(rows) == 2
    assert set(rows[0]) == {
        "period_from",
        "period_to",
        "days",
        "principal",
        "rate",
        "formula",
        "subtotal",
        "event_ending_period",
    }
    assert sum(row["subtotal"] for row in rows) == result.total
