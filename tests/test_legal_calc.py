from datetime import date, timedelta

import pytest

from korgan.legal_calc import (
    CAP_MRP_INDIVIDUAL,
    CAP_MRP_LEGAL_ENTITY,
    MRP_2026,
    NB_RATE_TABLE_VALID_THROUGH,
    NEEDS_CALCULATION_MARKER,
    rates_freshness,
    calc_gosposhlina_claim,
    calc_mixed_state_duty,
    calc_nonproperty_state_duty,
    base_rate_on,
    claimant_is_individual,
    format_kzt,
    gosposhlina_line,
    mrp_on,
    parse_all_amounts_kzt,
    parse_amount_kzt,
)

DELO_2_CONTEXT = (
    "Файл: KORGAN_TEST_DELO_2.docx\n"
    "Стороны: Займодавец (истец): Ахметов Руслан Маратович; Заёмщик (ответчик): Садыков Тимур Ерланович\n"
    "Идентификаторы: Ахметов Руслан Маратович, ИИН 000000000101; Садыков Тимур Ерланович, ИИН 000000000202\n"
    "Суммы: 2 400 000 тенге — сумма займа\n"
)


def test_delo_2_state_duty_is_24000() -> None:
    assert calc_gosposhlina_claim(2_400_000, True) == 24_000


def test_legal_entity_pays_three_percent() -> None:
    assert calc_gosposhlina_claim(2_400_000, False) == 72_000


def test_caps_differ_for_individual_and_legal_entity() -> None:
    huge = 10_000_000_000
    assert calc_gosposhlina_claim(huge, True) == CAP_MRP_INDIVIDUAL * MRP_2026
    assert calc_gosposhlina_claim(huge, False) == CAP_MRP_LEGAL_ENTITY * MRP_2026
    assert CAP_MRP_INDIVIDUAL == 10_000
    assert CAP_MRP_LEGAL_ENTITY == 20_000


def test_zero_claim_gives_zero_duty() -> None:
    assert calc_gosposhlina_claim(0, True) == 0


def test_mrp_is_chosen_by_the_day_and_not_by_position_in_the_file() -> None:
    """Будущий МРП не может считать сегодняшнюю пошлину.

    МРП устанавливает закон о бюджете сразу на три года, поэтому в справочнике
    ставок штатно появляется строка со следующим годом. Значение бралось
    последним по списку, без учёта даты введения: добавление законной будущей
    строки молча меняло бы пошлину по иску, подаваемому сегодня.
    """
    rows = [
        {"from": "2026-01-01", "value": 4325},
        {"from": "2027-01-01", "value": 4600},
    ]

    assert mrp_on(date(2026, 9, 1), rows=rows) == 4325
    assert mrp_on(date(2026, 12, 31), rows=rows) == 4325
    assert mrp_on(date(2027, 1, 1), rows=rows) == 4600


def test_mrp_rows_out_of_order_do_not_change_the_answer() -> None:
    """Порядок строк в файле — оформление, а не право."""
    rows = [
        {"from": "2027-01-01", "value": 4600},
        {"from": "2026-01-01", "value": 4325},
    ]

    assert mrp_on(date(2026, 9, 1), rows=rows) == 4325


def test_a_day_before_every_known_mrp_fails_closed() -> None:
    """Отсутствие ставки — отказ считать, а не ближайшее подходящее число."""
    rows = [{"from": "2026-01-01", "value": 4325}]

    with pytest.raises(RuntimeError):
        mrp_on(date(2025, 12, 31), rows=rows)


def test_base_rate_is_chosen_by_the_day_and_not_by_position_in_the_file() -> None:
    """Решение Нацбанка действует с даты, а не с места в списке.

    Ставка выбиралась перебором строк в порядке файла, и последняя подошедшая
    выигрывала. Новую ставку естественно дописать в начало списка — после этого
    неустойка считалась бы по прежней, уже отменённой ставке.
    """
    rows = [
        {"from": "2026-06-08", "value": 17.0},
        {"from": "2025-10-13", "value": 18.0},
    ]

    assert base_rate_on(date(2026, 7, 1), rows=rows) == 17.0
    assert base_rate_on(date(2026, 1, 1), rows=rows) == 18.0


def test_base_rate_before_the_table_is_not_approximated() -> None:
    """До первой известной ставки считать нечем — это не повод взять ближайшую."""
    rows = [{"from": "2025-10-13", "value": 18.0}]

    assert base_rate_on(date(2025, 1, 1), rows=rows) is None


def test_rate_table_covers_every_decision_that_changed_the_rate() -> None:
    """Каждое решение Нацбанка, менявшее ставку, должно быть в справочнике.

    Строк с «сохранением» в файле нет намеренно — они ничего не меняют. А вот
    пропуск решения, менявшего ставку, тих и опасен: неустойка за период после
    него считалась бы по прежней ставке, и сумма в просительной части иска
    разошлась бы с ручной перепроверкой юриста.

    Раньше таблица начиналась с октября 2025 года, и обычный долг начала
    2025-го вовсе не поддавался расчёту.
    """
    known = {
        date(2025, 1, 20): 15.25,
        date(2025, 3, 11): 16.5,
        date(2025, 10, 13): 18.0,
        date(2026, 6, 8): 17.0,
        date(2026, 7, 27): 16.75,
    }

    for day, rate in known.items():
        assert base_rate_on(day) == rate, f"ставка на {day.isoformat()}"
        # Накануне решения обязана действовать предыдущая, а не новая.
        previous = base_rate_on(day - timedelta(days=1))
        assert previous != rate or previous is None, f"ставка не менялась {day.isoformat()}"


def test_rate_table_expiry_is_visible_before_it_reaches_a_client() -> None:
    """Обрыв справочника обязан быть виден снаружи, а не только в документе.

    После `valid_through` ставки нет, и неустойка честно не считается. Отказ
    правильный, но безмолвный: без этого поля о нём узнавали бы по маркеру
    «требует проверки», уже попавшему клиенту в исковое заявление.
    """
    fresh = rates_freshness(NB_RATE_TABLE_VALID_THROUGH)
    assert fresh["nb_base_rate_stale"] is False
    assert fresh["nb_base_rate_days_left"] == 0

    expired = rates_freshness(NB_RATE_TABLE_VALID_THROUGH + timedelta(days=1))
    assert expired["nb_base_rate_stale"] is True
    assert expired["nb_base_rate_days_left"] == -1
    # То, о чём предупреждает поле, обязано и вправду происходить.
    assert base_rate_on(NB_RATE_TABLE_VALID_THROUGH + timedelta(days=1)) is None


def test_state_duty_cap_uses_the_mrp_effective_today() -> None:
    huge = 10_000_000_000
    today_mrp = mrp_on()

    assert calc_gosposhlina_claim(huge, True) == CAP_MRP_INDIVIDUAL * today_mrp
    # Половина МРП округляется вверх по ROUND_HALF_UP, а не банковским round().
    assert calc_nonproperty_state_duty(demands=1) == (today_mrp + 1) // 2


def test_negative_claim_is_rejected() -> None:
    with pytest.raises(ValueError):
        calc_gosposhlina_claim(-1, True)


def test_nonproperty_component_is_half_mrp() -> None:
    assert calc_nonproperty_state_duty() == 2_163


def test_mixed_claim_adds_property_and_nonproperty_components() -> None:
    assert calc_mixed_state_duty(2_400_000, True) == 24_000 + 2_163


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2 400 000 тенге", 2_400_000),
        ("2 400 000 (два миллиона четыреста тысяч) тенге", 2_400_000),
        ("2400000 тг", 2_400_000),
        ("Цена иска: 1 500 000 тенге", 1_500_000),
        ("12 000 000,49 тенге", 12_000_000),
        ("12 000 000,50 тенге", 12_000_001),
        ("сумма не определена", None),
        ("", None),
    ],
)
def test_parse_amount_kzt(text: str, expected: int | None) -> None:
    assert parse_amount_kzt(text) == expected


def test_parse_all_amounts_kzt_returns_every_currency_amount() -> None:
    assert parse_all_amounts_kzt("Долг 12 000 000 тенге, неустойка 996 000 ₸, всего 12 996 000 теңге") == [
        12_000_000,
        996_000,
        12_996_000,
    ]


def test_parse_amount_kzt_handles_29_digit_value_without_decimal_context_failure() -> None:
    raw = "99999999999999999999999999999 тенге"
    assert parse_amount_kzt(raw) == 99_999_999_999_999_999_999_999_999_999


def test_format_kzt() -> None:
    assert format_kzt(24_000) == "24 000 тенге"


def test_claimant_is_individual_for_delo_2() -> None:
    assert claimant_is_individual(DELO_2_CONTEXT) is True


def test_respondent_legal_entity_marker_does_not_change_claimant_rate() -> None:
    context = DELO_2_CONTEXT + "Дополнительно упомянуто ТОО «Альфа», БИН 000000000303.\n"
    assert claimant_is_individual(context) is True


def test_legal_entity_claimant_uses_three_percent() -> None:
    context = (
        "Истец: ТОО «Альфа», БИН 000000000303, адрес: г. Алматы\n"
        "Ответчик: Иванов Иван, ИИН 000000000101\n"
    )
    assert claimant_is_individual(context) is False
    assert gosposhlina_line(context, "2 400 000 тенге").startswith("72 000 тенге")


def test_individual_entrepreneur_uses_physical_person_rate_for_ordinary_civil_claim() -> None:
    context = (
        "Истец: ИП Ахметов Руслан Маратович, ИИН 900101300123\n"
        "Ответчик: ТОО «Альфа», БИН 230740012345\n"
    )
    assert claimant_is_individual(context) is True
    line = gosposhlina_line(context, "2 400 000 тенге")
    assert line.startswith("24 000 тенге")
    assert "1%" in line


def test_individual_address_word_containing_bin_does_not_trigger_legal_entity_rate() -> None:
    context = (
        "Истец: Иванов Иван Иванович, ИИН 900101300123, адрес: г. Астана, кабинет 214\n"
        "Ответчик: Петров Петр Петрович, ИИН 910101300456\n"
    )
    assert claimant_is_individual(context) is True
    assert gosposhlina_line(context, "2 400 000 тенге").startswith("24 000 тенге")


def test_gosposhlina_line_for_delo_2() -> None:
    line = gosposhlina_line(DELO_2_CONTEXT, "2 400 000 (два миллиона четыреста тысяч) тенге")
    assert line.startswith("24 000 тенге")
    assert "1%" in line
    assert "10 000 МРП" in line
    assert "665" in line


def test_gosposhlina_line_without_price_needs_calculation() -> None:
    assert gosposhlina_line(DELO_2_CONTEXT, "[ТРЕБУЕТ УТОЧНЕНИЯ: цена иска]") == NEEDS_CALCULATION_MARKER


def test_gosposhlina_line_without_party_type_needs_calculation() -> None:
    assert gosposhlina_line("Стороны: не установлено", "2 400 000 тенге") == NEEDS_CALCULATION_MARKER


def test_claimant_is_legal_entity_from_labeled_bins_without_role_lines() -> None:
    context = "Стороны спора: ТОО «A» (БИН 230740012345) и ТОО «B» (БИН 210940067891)"
    assert claimant_is_individual(context) is False


def test_claimant_is_individual_from_single_labeled_iin_without_role_lines() -> None:
    context = "Материалы заявителя: ИИН 900101300123, адрес г. Астана."
    assert claimant_is_individual(context) is True


def test_mixed_labeled_iin_and_bin_without_resolvable_claimant_is_fail_closed() -> None:
    context = "Участники: ИИН 900101300123; БИН 230740012345."
    assert claimant_is_individual(context) is None


def test_bare_twelve_digits_without_label_are_not_treated_as_iin() -> None:
    assert claimant_is_individual("Идентификатор 900101300123") is None


def test_parenthetical_and_dash_claimant_roles_are_recognized() -> None:
    assert claimant_is_individual("ТОО «A» (Истец); ТОО «B» (Ответчик)") is False
    assert claimant_is_individual("Стороны: ТОО «A» — истец; ТОО «B» — ответчик") is False


def test_gosposhlina_line_for_legal_entity_from_12_996_000() -> None:
    context = "Стороны спора: ТОО «A» (БИН 230740012345) и ТОО «B» (БИН 210940067891)"
    line = gosposhlina_line(context, "12 996 000 тенге")
    assert line.startswith("389 880 тенге")
    assert "3%" in line
    assert "20 000 МРП" in line
