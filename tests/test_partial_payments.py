"""Частичная оплата не должна молча исчезать из расчёта неустойки.

Разбор здесь намеренно узкий, и проверки делятся на две половины: что он
уверенно берёт и что он обязан пропустить мимо, не приняв за платёж. Вторая
половина важнее — ложный платёж занизил бы требование клиента так же незаметно,
как пропущенный завышает.
"""

from __future__ import annotations

from datetime import date

from korgan.partial_payments import find_partial_payments


def test_a_partial_payment_with_one_date_and_one_amount_is_parsed() -> None:
    scan = find_partial_payments(
        "11.03.2026 покупатель частично оплатил задолженность в размере 500 000 тенге."
    )

    assert scan.mentioned is True
    assert scan.unparsed == ()
    assert len(scan.payments) == 1
    assert scan.payments[0].on == date(2026, 3, 11)
    assert scan.payments[0].delta == -500_000


def test_several_partial_payments_are_all_found() -> None:
    scan = find_partial_payments(
        "Ответчик 11.03.2026 внёс в счёт погашения долга 500 000 тенге; "
        "21 марта 2026 года он частично оплатил ещё 300 000 тенге."
    )

    assert [(p.on, p.delta) for p in scan.payments] == [
        (date(2026, 3, 11), -500_000),
        (date(2026, 3, 21), -300_000),
    ]


def test_a_payment_without_a_date_is_reported_as_unparsed_not_ignored() -> None:
    """Оплата была, а когда — неизвестно: считать по-прежнему нельзя."""
    scan = find_partial_payments(
        "Ответчик частично оплатил задолженность в размере 500 000 тенге."
    )

    assert scan.mentioned is True
    assert scan.payments == ()
    assert len(scan.unparsed) == 1


def test_a_payment_without_an_amount_is_reported_as_unparsed() -> None:
    scan = find_partial_payments("11.03.2026 ответчик частично погасил долг.")

    assert scan.payments == ()
    assert len(scan.unparsed) == 1


def test_ambiguous_sentence_with_two_amounts_is_not_guessed() -> None:
    scan = find_partial_payments(
        "11.03.2026 ответчик частично оплатил долг: из 2 000 000 тенге внесено 500 000 тенге."
    )

    assert scan.payments == ()
    assert len(scan.unparsed) == 1


def test_a_promise_to_pay_is_not_a_payment() -> None:
    """«Обязался оплатить» — не платёж; принять его за платёж значило бы
    занизить требование на сумму, которой клиент не получал."""
    scan = find_partial_payments(
        "Ответчик обязался оплатить 2 000 000 тенге до 01.03.2026, оплата не произведена."
    )

    assert scan.mentioned is False
    assert scan.payments == ()


def test_a_denial_of_payment_is_not_a_payment() -> None:
    scan = find_partial_payments(
        "Долг частично не оплачен: 11.03.2026 поступило 0 тенге."
    )

    assert scan.payments == ()
    assert len(scan.unparsed) == 1


def test_a_case_without_any_payment_language_is_clean() -> None:
    scan = find_partial_payments(
        "Между сторонами заключён договор поставки; оплата в срок не поступила."
    )

    assert scan.mentioned is False
    assert scan.blocks_single_interval_calculation is False


def test_a_kazakh_partial_payment_is_noticed() -> None:
    scan = find_partial_payments("Жауапкер 11.03.2026 қарызды ішінара төледі.")

    assert scan.mentioned is True
    assert scan.blocks_single_interval_calculation is True
