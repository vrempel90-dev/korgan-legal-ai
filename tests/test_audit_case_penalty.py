from datetime import date

from korgan.contractual_penalty import calc_contractual_penalty, parse_contractual_penalty_terms


def test_audit_case_contractual_penalty_is_92400_not_article_353() -> None:
    """Regression for the external audit example: 0.1%/day, 10% cap, 77 days."""
    context = (
        "Пунктом 6.3 договора предусмотрена договорная неустойка 0,1% от суммы задолженности "
        "за каждый день просрочки, но не более 10% от суммы задолженности."
    )
    terms = parse_contractual_penalty_terms(context)
    assert terms is not None

    result = calc_contractual_penalty(
        1_200_000,
        terms,
        date(2026, 6, 16),
        date(2026, 8, 31),
    )

    assert result.days == 77
    assert result.amount == 92_400
    assert result.cap_amount == 120_000
    assert result.capped is False
