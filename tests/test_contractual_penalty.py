from datetime import date

from korgan.contractual_penalty import (
    ContractualPenaltyTerms,
    calc_contractual_penalty,
    parse_contractual_penalty_terms,
)


def test_parse_contractual_penalty_terms_with_cap_and_clause() -> None:
    text = (
        "Пунктом 6.3 договора предусмотрена неустойка 0,1% от суммы задолженности "
        "за каждый день просрочки, но не более 10% от суммы задолженности."
    )
    terms = parse_contractual_penalty_terms(text)
    assert terms is not None
    assert terms.rate_percent_per_day == 0.1
    assert terms.cap_percent == 10.0
    assert terms.clause == "6.3"


def test_parse_contractual_penalty_spelling_variants() -> None:
    variants = [
        "Согласно пункту 6.3 договора неустойка 0.1 % за каждый день просрочки, но не свыше 10 процентов.",
        "п. 6.3 договора: неустойка 0,1 процента в день, не свыше 10 процентов от суммы задолженности.",
    ]
    for text in variants:
        terms = parse_contractual_penalty_terms(text)
        assert terms is not None
        assert terms.rate_percent_per_day == 0.1
        assert terms.cap_percent == 10.0
        assert terms.clause == "6.3"


def test_parse_contractual_penalty_keeps_cap_beyond_fixed_character_window() -> None:
    text = (
        "Пунктом 6.3 договора предусмотрена неустойка 0,1% за каждый день просрочки. "
        + "Дополнительное описание порядка начисления и применения санкции без изменения ставки. " * 6
        + "При этом размер неустойки не более 10% от суммы задолженности."
    )
    assert text.index("не более 10%") - text.index("0,1%") > 260

    terms = parse_contractual_penalty_terms(text)

    assert terms is not None
    assert terms.rate_percent_per_day == 0.1
    assert terms.cap_percent == 10.0
    assert terms.clause == "6.3"


def test_cap_from_next_contract_clause_is_not_applied_to_current_rate() -> None:
    text = (
        "Пункт 6.3 договора: неустойка 0,1% за каждый день просрочки.\n"
        "Пункт 6.4 договора: штраф за иное нарушение, но не более 10% от суммы задолженности."
    )

    terms = parse_contractual_penalty_terms(text)

    assert terms is not None
    assert terms.rate_percent_per_day == 0.1
    assert terms.clause == "6.3"
    assert terms.cap_percent is None


def test_long_numbered_clause_remains_scope_beyond_320_characters() -> None:
    filler = "Подробное условие договора о порядке исполнения обязательства без изменения ставки. " * 6
    text = (
        "Пункт 6.3 договора: "
        + filler
        + "неустойка 0,1% за каждый день просрочки.\n"
        + "Пункт 6.4 договора: штраф за другое нарушение, но не более 10% от суммы задолженности."
    )
    assert text.index("0,1%") - text.index("Пункт 6.3") > 320

    terms = parse_contractual_penalty_terms(text)

    assert terms is not None
    assert terms.rate_percent_per_day == 0.1
    assert terms.clause == "6.3"
    assert terms.cap_percent is None


def test_parse_kazakh_contractual_penalty_terms() -> None:
    text = (
        "Шарттың 6.3-тармағында тұрақсыздық айыбы берешек үшін 0,1% "
        "әрбір кешіктірілген күн үшін есептеледі, бірақ жалпы мөлшері 10%-дан аспайды."
    )

    terms = parse_contractual_penalty_terms(text)

    assert terms is not None
    assert terms.rate_percent_per_day == 0.1
    assert terms.cap_percent == 10.0
    assert terms.clause == "6.3"


def test_parse_contractual_penalty_fails_closed_on_multiple_caps_in_same_paragraph() -> None:
    text = (
        "Пункт 6.3 договора: неустойка 0,1% за каждый день просрочки, не более 10%. "
        "Далее в том же пункте указано не более 15%."
    )
    assert parse_contractual_penalty_terms(text) is None


def test_parse_contractual_penalty_fails_closed_without_or_with_ambiguous_rate() -> None:
    assert parse_contractual_penalty_terms("Пункт 6.3 договора: неустойка за просрочку.") is None
    assert parse_contractual_penalty_terms(
        "Пункт 6.3 договора: 0,1% за каждый день просрочки, а после 30 дней 0,2% за каждый день просрочки."
    ) is None


def test_calc_contractual_penalty_83_days_without_reaching_cap() -> None:
    terms = ContractualPenaltyTerms(rate_percent_per_day=0.1, cap_percent=10.0, clause="6.3")
    result = calc_contractual_penalty(
        12_000_000,
        terms,
        date(2026, 5, 31),
        date(2026, 8, 21),
    )
    assert result.days == 83
    assert result.amount == 996_000
    assert result.capped is False
    assert result.cap_amount == 1_200_000
    assert result.cap_reached_on == date(2026, 9, 7)


def test_calc_contractual_penalty_applies_cap_and_exact_boundary() -> None:
    terms = ContractualPenaltyTerms(rate_percent_per_day=0.1, cap_percent=10.0, clause="6.3")
    long_result = calc_contractual_penalty(
        12_000_000,
        terms,
        date(2026, 5, 31),
        date(2026, 12, 31),
    )
    assert long_result.amount == 1_200_000
    assert long_result.capped is True
    assert long_result.cap_reached_on == date(2026, 9, 7)

    boundary = calc_contractual_penalty(
        12_000_000,
        terms,
        date(2026, 5, 31),
        date(2026, 9, 7),
    )
    assert boundary.days == 100
    assert boundary.amount == 1_200_000
    assert boundary.capped is True
