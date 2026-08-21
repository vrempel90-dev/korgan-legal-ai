from __future__ import annotations

from korgan.claim_consistency_guard import claim_consistency_errors
from korgan.legal_types import ClaimDraft, VerificationStatus


def _draft(*, legal_basis: list[str], requests: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление о взыскании уплаченной суммы, неустойки и судебных расходов",
        court="",
        claimant=["Истец"],
        defendant=["ИП Ответчик"],
        price_of_claim="1 200 000 тенге",
        facts=[
            "Истец полностью оплатил 1 200 000 тенге.",
            "Ответчик не изготовил и не установил кухонный гарнитур в установленный договором срок.",
        ],
        legal_basis=legal_basis,
        requests=requests,
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_explicit_penalty_and_costs_cannot_disappear_from_prayer() -> None:
    context = (
        "Я полностью оплатил работы. Ответчик нарушил срок изготовления и установки кухни. "
        "Прошу взыскать 1 200 000 тенге, неустойку и судебные расходы."
    )
    draft = _draft(
        legal_basis=["Исполнитель отвечает за нарушение срока выполнения работы."],
        requests=["Взыскать с Ответчика 1 200 000 тенге."],
    )

    errors = claim_consistency_errors(context, draft)

    assert any("неустойку/пеню" in error and "исчезло" in error for error in errors)
    assert any("судебные расходы" in error and "нет в разделе" in error for error in errors)


def test_buyer_nonpayment_rule_is_blocked_when_claimant_paid_in_full() -> None:
    context = (
        "Истец полностью оплатил 1 200 000 тенге. "
        "Ответчик не изготовил и не установил кухню в срок. Прошу вернуть уплаченную сумму."
    )
    draft = _draft(
        legal_basis=[
            "В случаях, когда договором предусмотрена предварительная оплата товара, "
            "неоплата покупателем в установленный срок признается отказом покупателя от исполнения договора."
        ],
        requests=["Взыскать с Ответчика 1 200 000 тенге."],
    )

    errors = claim_consistency_errors(context, draft)

    assert any("истец оплатил полностью" in error and "другой фактической ситуации" in error for error in errors)


def test_goods_return_penalty_rule_is_blocked_for_delayed_work() -> None:
    context = (
        "Ответчик должен был выполнить работы по изготовлению и установке кухни до 10 июля, но срок нарушил. "
        "Прошу взыскать неустойку."
    )
    draft = _draft(
        legal_basis=[
            "За просрочку требований потребителя об обмене или возврате товара надлежащего качества, "
            "а также требований при продаже товара ненадлежащего качества выплачивается неустойка 1% стоимости товара."
        ],
        requests=["Взыскать неустойку 120 000 тенге."],
    )

    errors = claim_consistency_errors(context, draft)

    assert any("просрочке выполнения работы/услуги" in error and "возврате/качестве товара" in error for error in errors)


def test_work_delay_penalty_basis_is_not_misclassified_as_goods_rule() -> None:
    context = (
        "Ответчик нарушил срок выполнения работы по изготовлению и установке кухни. "
        "Прошу взыскать неустойку."
    )
    draft = _draft(
        legal_basis=[
            "За нарушение сроков начала и окончания выполнения работы исполнитель обязан уплатить "
            "неустойку в размере одного процента стоимости работы за каждый день просрочки."
        ],
        requests=["Взыскать неустойку 120 000 тенге."],
    )

    errors = claim_consistency_errors(context, draft)

    assert not any("возврате/качестве товара" in error for error in errors)


def test_penalty_without_amount_cannot_be_filing_ready() -> None:
    context = "Прошу взыскать неустойку за нарушение срока выполнения работ."
    draft = _draft(
        legal_basis=["За нарушение срока выполнения работы исполнитель уплачивает неустойку."],
        requests=["Взыскать с Ответчика неустойку."],
    )

    errors = claim_consistency_errors(context, draft)

    assert any("без конкретного размера" in error for error in errors)
