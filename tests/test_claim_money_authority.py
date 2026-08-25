from __future__ import annotations

from korgan import claim_state_duty
from korgan.claim_money_authority import (
    CLAIM_PRICE_NEEDS_CALCULATION,
    install_claim_money_authority,
    reconcile_claim_money,
)
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def _draft(*, price: str, requests: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        source_urls=[],
        title="И С К\nо взыскании задолженности",
        court="Суд",
        claimant=["Истец: Товарищество с ограниченной ответственностью «СтройИнжиниринг KZ»"],
        defendant=["Ответчик: ТОО «Астана Девелопмент»"],
        price_of_claim=price,
        state_duty="",
        late_interest="",
        facts=["Стоимость выполненных работ составляет 8 400 000 тенге."],
        legal_basis=[],
        requests=requests,
        attachments=[],
        verification_notes=[],
    )


def test_restores_dropped_principal_amount_only_when_same_price_is_in_source() -> None:
    draft = _draft(
        price="8 400 000 тенге",
        requests=["Взыскать с Ответчика задолженность."],
    )
    context = (
        "Истец: ТОО «СтройИнжиниринг KZ». Ответчик: ТОО «Астана Девелопмент». "
        "Стоимость выполненных работ и задолженность составляют 8 400 000 тенге. "
        "Прошу взыскать задолженность."
    )

    result = reconcile_claim_money(context, draft)

    assert result.repaired_request is True
    assert result.price == 8_400_000
    assert draft.price_of_claim == "8 400 000 тенге"
    assert draft.requests == [
        "Взыскать с Ответчика задолженность в размере 8 400 000 тенге."
    ]


def test_orphan_model_price_is_not_used_when_source_does_not_ground_it() -> None:
    draft = _draft(
        price="9 999 999 тенге",
        requests=["Взыскать с Ответчика задолженность."],
    )
    context = "Истец: ТОО «СтройИнжиниринг KZ». Задолженность составляет 8 400 000 тенге."

    result = reconcile_claim_money(context, draft)

    assert result.needs_review is True
    assert result.price is None
    assert draft.price_of_claim == CLAIM_PRICE_NEEDS_CALCULATION
    assert draft.requests == ["Взыскать с Ответчика задолженность."]


def test_final_prayer_ledger_overrides_stale_price_and_includes_penalty() -> None:
    draft = _draft(
        price="8 400 000 тенге",
        requests=[
            "Взыскать задолженность 8 400 000 тенге.",
            "Взыскать договорную пеню 100 000 тенге.",
        ],
    )
    context = (
        "Истец: ТОО «СтройИнжиниринг KZ». Основной долг 8 400 000 тенге. "
        "Договорная пеня рассчитана в размере 100 000 тенге."
    )

    result = reconcile_claim_money(context, draft)
    decision = claim_state_duty.decide_state_duty(context, _research(), draft)

    assert result.price == 8_500_000
    assert draft.price_of_claim == "8 500 000 тенге"
    assert decision.mode == "property"
    assert decision.amount == 255_000


def test_production_regression_known_price_known_too_no_longer_becomes_unclassified() -> None:
    install_claim_money_authority()
    draft = _draft(
        price="8 400 000 тенге",
        requests=["Взыскать с Ответчика задолженность."],
    )
    context = (
        "Истец: ТОО «СтройИнжиниринг KZ». Ответчик: ТОО «Астана Девелопмент». "
        "По договору подряда стоимость выполненных и принятых работ составляет 8 400 000 тенге. "
        "Оплата не произведена. Прошу взыскать задолженность."
    )

    decision = claim_state_duty.decide_state_duty(context, _research(), draft)

    assert decision.mode == "property"
    assert decision.needs_review is False
    assert decision.amount == 252_000
    assert draft.price_of_claim == "8 400 000 тенге"
    assert "8 400 000 тенге" in draft.requests[0]
