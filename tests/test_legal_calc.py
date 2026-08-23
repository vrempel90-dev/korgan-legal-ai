import pytest

from korgan.legal_calc import (
    CAP_MRP,
    MRP_2026,
    NEEDS_CALCULATION_MARKER,
    calc_gosposhlina_claim,
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


def test_cap_is_10000_mrp() -> None:
    huge = 10_000_000_000
    assert calc_gosposhlina_claim(huge, True) == CAP_MRP * MRP_2026
    assert calc_gosposhlina_claim(huge, False) == CAP_MRP * MRP_2026


def test_zero_claim_gives_zero_duty() -> None:
    assert calc_gosposhlina_claim(0, True) == 0


def test_negative_claim_is_rejected() -> None:
    with pytest.raises(ValueError):
        calc_gosposhlina_claim(-1, True)


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


def test_format_kzt() -> None:
    assert format_kzt(24_000) == "24 000 тенге"


def test_claimant_is_individual_for_delo_2() -> None:
    assert claimant_is_individual(DELO_2_CONTEXT) is True


def test_respondent_legal_entity_marker_does_not_change_claimant_rate() -> None:
    """Party type is role-bound: an unrelated/respondent ТОО cannot contaminate the claimant."""
    context = DELO_2_CONTEXT + "Дополнительно упомянуто ТОО «Альфа», БИН 000000000303.\n"
    assert claimant_is_individual(context) is True


def test_legal_entity_claimant_uses_three_percent() -> None:
    context = (
        "Истец: ТОО «Альфа», БИН 000000000303, адрес: г. Алматы\n"
        "Ответчик: Иванов Иван, ИИН 000000000101\n"
    )
    assert claimant_is_individual(context) is False
    assert gosposhlina_line(context, "2 400 000 тенге").startswith("72 000 тенге")


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
