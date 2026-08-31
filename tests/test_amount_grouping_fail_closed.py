"""Кривая группировка суммы обязана отклоняться, а не разбираться с хвоста.

Шаблон суммы не мог совпасть с начала «12 34 567 тенге», разбор
перезапускался после пробела и возвращал 34 567; «1234 567 тенге» давало
567. Дальше по конвейеру это становилось ценой иска и базой госпошлины —
иск уходил в суд с суммой, меньшей заявленной в разы.

Неверная сумма в исковом заявлении дороже отказа её разобрать, поэтому
поведение fail-closed: непонятная запись возвращает None, и требование
раскрытия суммы срабатывает выше по конвейеру.

Проверяется production-поведение: после ``import korgan.strict_bot`` —
в той же конфигурации патчей, в которой работает боевой разбор.
"""

from __future__ import annotations

import time

import pytest

from korgan import legal_calc


@pytest.fixture(scope="module")
def production_legal_calc():
    import korgan.strict_bot  # noqa: F401  — тот же импорт, что делает miniapp_api

    return legal_calc


# Записи, которые встречаются при OCR договора и при ручном вводе.
MALFORMED = (
    "12 34 567 тенге",
    "1234 567 тенге",
    "12 3456 тенге",
    "1 23 456 тенге",
)


@pytest.mark.parametrize("text", MALFORMED)
def test_malformed_grouping_is_rejected(production_legal_calc, text: str) -> None:
    assert production_legal_calc.parse_amount_kzt(text) is None, text


@pytest.mark.parametrize("text", MALFORMED)
def test_malformed_grouping_yields_no_amount_at_all(production_legal_calc, text: str) -> None:
    """Ни одна сумма не должна извлекаться: обрезок хуже отсутствия."""
    assert production_legal_calc.parse_all_amounts_kzt(text) == [], text


# Корректные формы обязаны продолжать разбираться — иначе цена fail-closed
# слишком высока и госпошлина перестанет считаться на нормальном вводе.
WELL_FORMED = (
    ("2 400 000 тенге", 2_400_000),
    ("1 234 567 тенге", 1_234_567),
    ("12 345 678 тенге", 12_345_678),
    ("2400000 тенге", 2_400_000),
    ("2 400 000 (два миллиона четыреста тысяч) тенге", 2_400_000),
    ("Цена иска: 1 500 000 тенге", 1_500_000),
    ("12 000 000,49 тенге", 12_000_000),
    ("по пункту 4.2 договора 100 000 тенге", 100_000),
)


@pytest.mark.parametrize(("text", "expected"), WELL_FORMED)
def test_well_formed_amounts_still_parse(production_legal_calc, text: str, expected: int) -> None:
    assert production_legal_calc.parse_amount_kzt(text) == expected


def test_several_amounts_in_one_line_are_all_found(production_legal_calc) -> None:
    text = "основной долг 2 300 000 тенге, неустойка 377 200 тенге, госпошлина 23 000 тенге"

    assert production_legal_calc.parse_all_amounts_kzt(text) == [2_300_000, 377_200, 23_000]


def test_parsing_stays_linear(production_legal_calc) -> None:
    """Дополнительный lookbehind не должен вернуть квадратичный разбор."""
    started = time.perf_counter()
    production_legal_calc.parse_amount_kzt("1 " * 30_000)

    assert time.perf_counter() - started < 1.0
