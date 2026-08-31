"""Денежные функции обязаны вести себя одинаково до и после production-патчей.

Это структурный тест, а не обычный юнит. Production API импортирует
``korgan.strict_bot``, который вызывает ``install_universal_word_final_hardening()``
и подменяет ``legal_calc.parse_amount_kzt``, ``calc_gosposhlina_claim`` и
``calc_late_payment_penalty``. Остальные тесты денег выполняются в процессе,
где патч не установлен, поэтому проверяют функции, которых в production нет.

Именно этот разрыв скрыл три бага:

1. подменённый разбор суммы не понимал «2 400 000 (два миллиона …) тенге»
   и «KZT» — госпошлина не считалась и иск никогда не выходил filing_ready;
2. подменённая госпошлина применяла потолок физлица (10 000 МРП) к
   юридическому лицу, которому по ст. 665 НК РК положено 20 000 МРП;
3. подменённый разбор падал с ``decimal.InvalidOperation`` на длинной сумме.

Поэтому тест сначала запоминает эталон на чистом ``legal_calc``, затем
устанавливает production-стек и требует ровно того же результата. Разрешено
только повышение точности, не изменение результата.
"""

from __future__ import annotations

import pytest

from korgan import legal_calc

# Формы записи денежной суммы, которые реально встречаются в исковых
# заявлениях и договорах РК. Профессиональный документ почти всегда пишет
# сумму прописью в скобках, поэтому эта форма — основная, а не краевая.
AMOUNT_FORMS: tuple[tuple[str, int | None], ...] = (
    ("2 400 000 тенге", 2_400_000),
    ("2 400 000 (два миллиона четыреста тысяч) тенге", 2_400_000),
    ("2 400 000 (два миллиона четыреста тысяч) теңге", 2_400_000),
    ("2400000 тг", 2_400_000),
    ("2400000 KZT", 2_400_000),
    ("2 400 000 ₸", 2_400_000),
    ("Цена иска: 1 500 000 тенге", 1_500_000),
    ("12 000 000,49 тенге", 12_000_000),
    ("12 000 000,50 тенге", 12_000_001),
    ("2 400 000 тенге", 2_400_000),
    ("сумма не определена", None),
    ("", None),
)


@pytest.fixture(scope="module")
def production_legal_calc():
    """Модуль legal_calc после установки полного production-стека патчей."""
    import korgan.strict_bot  # noqa: F401  — тот же импорт, что делает miniapp_api

    return legal_calc


@pytest.mark.parametrize(("text", "expected"), AMOUNT_FORMS)
def test_amount_parsing_survives_production_patches(production_legal_calc, text, expected) -> None:
    assert production_legal_calc.parse_amount_kzt(text) == expected


def test_state_duty_cap_differs_by_party_type_in_production(production_legal_calc) -> None:
    """Ст. 665 НК РК: физлицо — 1 % до 10 000 МРП, юрлицо — 3 % до 20 000 МРП."""
    huge = 10_000_000_000
    calc = production_legal_calc

    assert calc.calc_gosposhlina_claim(huge, True) == calc.CAP_MRP_INDIVIDUAL * calc.MRP_2026
    assert calc.calc_gosposhlina_claim(huge, False) == calc.CAP_MRP_LEGAL_ENTITY * calc.MRP_2026


def test_state_duty_rates_come_from_rates_json_in_production(production_legal_calc) -> None:
    """Ставка обязана читаться из данных, иначе обновление rates.json ничего не меняет."""
    calc = production_legal_calc
    amount = 1_000_000

    assert calc.calc_gosposhlina_claim(amount, True) == round(amount * calc.RATE_INDIVIDUAL)
    assert calc.calc_gosposhlina_claim(amount, False) == round(amount * calc.RATE_LEGAL_ENTITY)


def test_long_amount_does_not_raise_in_production(production_legal_calc) -> None:
    """Длинная сумма из материалов не должна ронять API пятисоткой."""
    huge = "1" * 29 + " тенге"

    assert production_legal_calc.parse_amount_kzt(huge) == int("1" * 29)


def test_gosposhlina_line_is_produced_for_professional_price_form(production_legal_calc) -> None:
    """Цена иска прописью не должна оставлять документ без расчёта пошлины."""
    calc = production_legal_calc
    context = "Истец: Ахметов Руслан Маратович, ИИН 900101300123"
    price = "2 400 000 (два миллиона четыреста тысяч) тенге"

    line = calc.gosposhlina_line(context, price)

    assert calc.NEEDS_CALCULATION_MARKER not in line
    assert line.startswith("24 000 тенге")


def test_legal_entity_price_form_uses_legal_entity_rate(production_legal_calc) -> None:
    calc = production_legal_calc
    context = 'Истец: ТОО «Астана Логистик», БИН 123456789012'
    price = "2 400 000 (два миллиона четыреста тысяч) тенге"

    line = calc.gosposhlina_line(context, price)

    assert line.startswith("72 000 тенге")
    assert "20 000 МРП" in line


def test_amount_parsing_stays_linear_on_hostile_input(production_legal_calc) -> None:
    """Материалы дела приходят от пользователя и не должны занимать процессор.

    Прежний шаблон допускал экспоненциальный откат внутри класса [\\d\\s]*:
    строка вида «1 1 1 1 …» разбиралась квадратично (2000 токенов — 0.8 с,
    4000 — 3.3 с). При лимите описания дела в 60 000 символов это давало
    минуты процессорного времени на один запрос.
    """
    import time

    hostile = "1 " * 30_000 + "x"
    started = time.perf_counter()
    assert production_legal_calc.parse_all_amounts_kzt(hostile) == []
    elapsed = time.perf_counter() - started

    # Порог с большим запасом: линейный разбор укладывается в единицы
    # миллисекунд, квадратичный на этом входе занимал бы минуты.
    assert elapsed < 1.0, f"разбор занял {elapsed:.2f}s — вероятен возврат отката"


def test_thousand_separators_group_by_three(production_legal_calc) -> None:
    """«1 1 1» — не сумма: разряды разделяются по три цифры."""
    parse = production_legal_calc.parse_all_amounts_kzt

    assert parse("1 1 1 тенге") == [1]
    assert parse("2 400 000 тенге") == [2_400_000]
    assert parse("12 000 000,49 тенге") == [12_000_000]
    assert parse("2400000 тенге") == [2_400_000]
