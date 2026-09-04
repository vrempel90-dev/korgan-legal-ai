"""Договорная неустойка за просрочку выполнения работ, а не только за долг.

Тестовое дело: потребитель полностью оплатил изготовление и установку кухонного
гарнитура, исполнитель сорвал конечный срок работ. Договор называет ставку
неустойки от стоимости невыполненного обязательства.

До исправления оба детерминированных шага не срабатывали именно на этой
формулировке, хотя она типовая для подряда, поставки и оказания услуг:

1. ставка «0,1 % от стоимости невыполненного обязательства за каждый день
   просрочки» не извлекалась, потому что база неустойки допускалась только как
   «от суммы задолженности» или «от долга»;
2. начало просрочки не устанавливалось, потому что срок исполнения искался
   только у денежного обязательства («вернуть … до <дата>»).

Последствие было не косметическим: требование о неустойке заменялось на
«Взыскать заявленную клиентом неустойку [ТРЕБУЕТ ПРОВЕРКИ: …]», цена иска
теряла неустойку, и госпошлина переставала считаться.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from korgan.contractual_penalty import calc_contractual_penalty, parse_contractual_penalty_terms
from korgan.late_interest_hotfix import (
    _extract_due_date,
    _property_components,
    _write_deterministic_calculation,
)
from korgan.legal_calculation import MoneyComponent
from korgan.legal_types import ClaimDraft, VerificationStatus

WORK_CLAUSE = (
    "Пунктом 5.2 договора предусмотрено: при нарушении срока выполнения работ исполнитель "
    "выплачивает заказчику неустойку в размере 0,1 % от стоимости невыполненного обязательства "
    "за каждый день просрочки, но не более 10 % стоимости договора."
)


def test_penalty_rate_parsed_from_value_of_unperformed_obligation() -> None:
    terms = parse_contractual_penalty_terms(WORK_CLAUSE)

    assert terms is not None
    assert terms.rate_percent_per_day == Decimal("0.1")
    assert terms.cap_percent == Decimal("10")
    assert terms.clause == "5.2"


def test_penalty_rate_parsed_from_other_contractual_bases() -> None:
    for clause in (
        "по договору неустойка в размере 0,1 % от стоимости работ за каждый день просрочки",
        "по договору пеня 0,5 % от цены договора за каждый день просрочки",
        "по договору неустойка 0,2 % от стоимости непоставленного товара за каждый день просрочки",
    ):
        assert parse_contractual_penalty_terms(clause) is not None, clause


def test_daily_rate_still_requires_a_daily_anchor() -> None:
    """Процент без «за каждый день» ставкой не становится: штраф считается иначе."""
    assert parse_contractual_penalty_terms("по договору штраф 10 % от цены договора") is None


def test_work_deadline_starts_the_delay_period() -> None:
    assert _extract_due_date(
        "Договором установлен окончательный срок выполнения работ: до 15 июня 2026 года включительно."
    ) == date(2026, 6, 15)
    assert _extract_due_date("Работы должны быть выполнены до 15.06.2026.") == date(2026, 6, 15)
    assert _extract_due_date(
        "Срок поставки товара — не позднее 15 июня 2026 года."
    ) == date(2026, 6, 15)
    assert _extract_due_date(
        "Услуги должны быть оказаны не позднее 15 июня 2026 года."
    ) == date(2026, 6, 15)


def test_two_different_performance_deadlines_stay_fail_closed() -> None:
    """Две разные даты срока — не повод выбрать любую из них."""
    assert _extract_due_date(
        "Срок выполнения работ до 15 июня 2026 года. Срок поставки товара не позднее 20 июля 2026 года."
    ) is None


def test_case_one_penalty_amount_is_reproducible() -> None:
    """1 200 000 x 0,1 % x 77 дней = 92 400 тенге, договорный предел 120 000 не достигнут."""
    terms = parse_contractual_penalty_terms(WORK_CLAUSE)
    assert terms is not None

    penalty = calc_contractual_penalty(1_200_000, terms, date(2026, 6, 16), date(2026, 8, 31))

    assert penalty.days == 77
    assert penalty.amount == 92_400
    assert penalty.cap_amount == 120_000
    assert penalty.capped is False


def _refund_claim_draft() -> ClaimDraft:
    """Иск потребителя: возврат уплаченного и договорная неустойка."""
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление о взыскании уплаченной по договору суммы и договорной неустойки",
        court="районный суд № 2 Алмалинского района города Алматы",
        claimant=["Сериков Арман Нурланович"],
        defendant=["ТОО «Мебель Стандарт»"],
        price_of_claim="1 200 000 тенге",
        facts=["Работы по договору № MS-114/26 не выполнены."],
        legal_basis=[],
        requests=[
            "Взыскать с ТОО «Мебель Стандарт» в пользу Серикова Армана Нурлановича уплаченные "
            "по договору № MS-114/26 от 20 марта 2026 года денежные средства в размере 1 200 000 тенге.",
            "Взыскать с ТОО «Мебель Стандарт» в пользу Серикова Армана Нурлановича договорную "
            "неустойку в размере 92 400 тенге.",
        ],
        attachments=["Договор № MS-114/26 от 20 марта 2026 года."],
        verification_notes=[],
        source_urls=[],
    )


def test_refund_of_prepayment_is_a_principal_money_claim() -> None:
    """Возврат уплаченного — основное требование, а не безымянная позиция.

    Гейт сверки расчёта требует ровно одно основное денежное требование. Пока
    возврат предоплаты в него не попадал, сверка объявляла требование
    «изложенным неоднозначно» и снимала рассчитанную неустойку из иска.
    """
    components, unresolved = _property_components(_refund_claim_draft())

    assert unresolved is False
    labels = {label for label, _, _ in components}
    principal = [amount for label, amount, _ in components if label.startswith("основн")]
    assert principal == [1_200_000], labels
    assert any("неустойк" in label for label in labels)


def test_refund_component_is_named_in_the_calculation_section() -> None:
    """Возврат уплаченного не называется в расчёте «долгом»: это разные требования."""
    draft = _refund_claim_draft()
    _write_deterministic_calculation(
        draft,
        MoneyComponent(title="Договорная неустойка", basis="", amount=92_400),
    )

    titles = [str(line).split(":", 1)[0] for line in draft.calculation]
    assert any(title.lower().startswith("основная сумма") for title in titles), titles
    assert not any(title.lower() == "основной долг" for title in titles), titles
