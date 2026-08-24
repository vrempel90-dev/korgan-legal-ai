from dataclasses import replace
from datetime import date

import pytest

from korgan.legal.calc import load_rates
from korgan.legal_calc import (
    CAP_MRP,
    CAP_MRP_LEGAL_ENTITY,
    MRP_2026,
    NEEDS_CALCULATION_MARKER,
    calc_gosposhlina_claim,
    claimant_is_individual,
    format_kzt,
    gosposhlina_line,
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


def test_physical_and_legal_entity_have_different_caps() -> None:
    huge = 10_000_000_000
    assert calc_gosposhlina_claim(huge, True) == CAP_MRP * MRP_2026
    assert calc_gosposhlina_claim(huge, False) == CAP_MRP_LEGAL_ENTITY * MRP_2026
    assert CAP_MRP == 10_000
    assert CAP_MRP_LEGAL_ENTITY == 20_000


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
        ("сумма не определена", None),
        ("", None),
    ],
)
def test_parse_amount_kzt(text: str, expected: int | None) -> None:
    assert parse_amount_kzt(text) == expected


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


def test_individual_entrepreneur_is_physical_person_for_ordinary_property_claim() -> None:
    context = (
        "Истец: ИП Иванов Иван Иванович, ИИН 000000000101\n"
        "Ответчик: ТОО «Альфа», БИН 000000000303\n"
    )
    assert claimant_is_individual(context) is True
    assert gosposhlina_line(context, "2 400 000 тенге").startswith("24 000 тенге")


def test_gosposhlina_line_for_delo_2() -> None:
    line = gosposhlina_line(DELO_2_CONTEXT, "2 400 000 (два миллиона четыреста тысяч) тенге")
    assert line.startswith("24 000 тенге")
    assert "1%" in line
    assert "10 000 МРП" in line
    assert "665" in line


def test_mixed_property_and_non_property_claim_adds_half_mrp() -> None:
    line = gosposhlina_line(
        DELO_2_CONTEXT,
        "2 400 000 тенге",
        title="Иск о расторжении договора и взыскании денежных средств",
        requests=[
            "Расторгнуть договор оказания услуг.",
            "Взыскать с ответчика 2 400 000 тенге.",
        ],
    )
    assert line.startswith("26 163 тенге")
    assert "0.5 МРП" in line


def test_monetary_obligation_worded_as_oblige_does_not_add_half_mrp() -> None:
    line = gosposhlina_line(
        DELO_2_CONTEXT,
        "1 000 000 тенге",
        title="Иск о взыскании долга",
        requests=["Обязать ответчика вернуть долг 1 000 000 тенге."],
    )
    assert line.startswith("10 000 тенге")
    assert "0.5 МРП" not in line


def test_pure_non_property_claim_is_half_mrp() -> None:
    line = gosposhlina_line(
        DELO_2_CONTEXT,
        "[ТРЕБУЕТ УТОЧНЕНИЯ: цена иска]",
        title="Иск неимущественного характера",
        requests=["Обязать ответчика устранить нарушение."],
    )
    assert line.startswith("2 163 тенге")
    assert "0.5 МРП" in line


def test_consumer_claim_is_deferred_not_exempt() -> None:
    line = gosposhlina_line(
        DELO_2_CONTEXT,
        "920 000 тенге",
        title="Иск о защите прав потребителей",
        requests=["Взыскать 920 000 тенге."],
    )
    assert "Уплата отсрочена" in line
    assert "9 200 тенге" in line
    assert "106 ГПК" in line
    assert not line.startswith("0 тенге")


def test_wage_claim_is_exempt_under_article_668() -> None:
    context = (
        "Истец: Иванов Иван Иванович, ИИН 000000000101\n"
        "Ответчик: ТОО «Работодатель», БИН 000000000303\n"
    )
    line = gosposhlina_line(
        context,
        "500 000 тенге",
        title="Иск о взыскании заработной платы",
        requests=["Взыскать задолженность по заработной плате 500 000 тенге."],
    )
    assert line.startswith("0 тенге")
    assert "665" in line


def test_salary_certificate_in_evidence_does_not_create_wage_exemption() -> None:
    context = DELO_2_CONTEXT + "Доказательство: справка о заработной плате истца для подтверждения дохода.\n"
    line = gosposhlina_line(
        context,
        "1 000 000 тенге",
        title="Иск о взыскании долга",
        requests=["Взыскать долг 1 000 000 тенге."],
    )
    assert line.startswith("10 000 тенге")


def test_divorce_in_background_does_not_change_debt_tariff() -> None:
    context = DELO_2_CONTEXT + "Истец ранее сообщил, что его брак расторгнут в 2024 году.\n"
    line = gosposhlina_line(
        context,
        "1 000 000 тенге",
        title="Иск о взыскании долга",
        requests=["Взыскать долг 1 000 000 тенге."],
    )
    assert line.startswith("10 000 тенге")
    assert "0.3 МРП" not in line


def test_ambiguous_transaction_invalidity_fails_closed() -> None:
    line = gosposhlina_line(
        DELO_2_CONTEXT,
        "2 400 000 тенге",
        title="Иск о признании сделки недействительной",
        requests=["Признать сделку недействительной и применить последствия недействительности."],
    )
    assert line == NEEDS_CALCULATION_MARKER


def test_gosposhlina_line_without_price_needs_calculation() -> None:
    assert gosposhlina_line(DELO_2_CONTEXT, "[ТРЕБУЕТ УТОЧНЕНИЯ: цена иска]") == NEEDS_CALCULATION_MARKER


def test_gosposhlina_line_without_party_type_needs_calculation() -> None:
    assert gosposhlina_line("Стороны: не установлено", "2 400 000 тенге") == NEEDS_CALCULATION_MARKER


def test_state_duty_rates_expire_after_2026_instead_of_guessing() -> None:
    assert gosposhlina_line(DELO_2_CONTEXT, "2 400 000 тенге", day=date(2027, 1, 1)) == NEEDS_CALCULATION_MARKER


def test_production_helper_uses_injected_rate_config() -> None:
    configured = replace(load_rates(), duty_individual_rate=0.02)
    line = gosposhlina_line(
        DELO_2_CONTEXT,
        "1 000 000 тенге",
        title="Иск о взыскании долга",
        requests=["Взыскать долг 1 000 000 тенге."],
        rates=configured,
    )
    assert line.startswith("20 000 тенге")
    assert "2%" in line
