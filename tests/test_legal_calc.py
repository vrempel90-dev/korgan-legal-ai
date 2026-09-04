import pytest

from korgan.legal_calc import (
    CAP_MRP_INDIVIDUAL,
    CAP_MRP_LEGAL_ENTITY,
    MRP_2026,
    NEEDS_CALCULATION_MARKER,
    calc_gosposhlina_claim,
    calc_mixed_state_duty,
    calc_nonproperty_state_duty,
    claim_price_amount,
    claimant_is_individual,
    format_kzt,
    gosposhlina_line,
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


# --- цена иска в строке с несколькими суммами --------------------------------
#
# Поле цены иска пишет модель свободным текстом. Пока код брал первую сумму в
# строке, разбивка «слагаемые, затем итог» давала госпошлину от слагаемого:
# по делу на 1 292 400 тенге (1 200 000 долга + 92 400 неустойки) выходило
# 12 000 тенге вместо 12 924. Заниженная пошлина в поданном иске — основание
# оставить его без движения, а число подавалось как точный расчёт по статье 665
# НК РК, без оговорок.

CLAIMANT_CONTEXT = (
    "Истец: Сериков Арман Нурланович, ИИН 900101300123\n"
    "Ответчик: ТОО «Мебель Стандарт», БИН 180540012345\n"
)


def test_claim_price_from_single_amount() -> None:
    assert claim_price_amount("1 292 400 тенге") == 1_292_400


def test_claim_price_takes_total_not_first_amount() -> None:
    assert claim_price_amount(
        "1 292 400 тенге (1 200 000 тенге основной долг + 92 400 тенге неустойка)"
    ) == 1_292_400
    assert claim_price_amount(
        "1 200 000 тенге основного долга и 92 400 тенге неустойки, итого 1 292 400 тенге"
    ) == 1_292_400


def test_claim_price_is_none_when_total_is_not_stated() -> None:
    assert claim_price_amount("1 200 000 тенге и 92 400 тенге") is None


def test_claim_price_is_none_when_total_is_ambiguous() -> None:
    # Две равные суммы: каждая равна сумме остальных, итог не определён.
    assert claim_price_amount("50 000 тенге и 50 000 тенге") is None


def test_state_duty_uses_claim_price_total_not_first_component() -> None:
    for price in (
        "1 292 400 тенге (1 200 000 тенге основной долг + 92 400 тенге неустойка)",
        "1 200 000 тенге основного долга и 92 400 тенге неустойки, итого 1 292 400 тенге",
        "основной долг 1 200 000 тенге, неустойка 92 400 тенге — цена иска 1 292 400 тенге",
    ):
        assert gosposhlina_line(CLAIMANT_CONTEXT, price).startswith("12 924 тенге"), price


def test_state_duty_fails_closed_when_claim_price_is_undeterminable() -> None:
    assert (
        gosposhlina_line(CLAIMANT_CONTEXT, "1 200 000 тенге и 92 400 тенге")
        == NEEDS_CALCULATION_MARKER
    )
