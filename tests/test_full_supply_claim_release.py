from korgan.claim_state_duty import apply_professional_state_duty
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import _recalculate_price
from korgan.universal_word_final_hardening import (
    complete_claim_relief_from_materials_exact,
    contractual_penalty_period_from_source,
)


CASE = """
Истец:
ТОО «Арман Снабжение»
БИН: 000000000001
Ответчик:
ТОО «Вектор Строй»
БИН: 000000000002

15.06.2026 между сторонами заключён договор поставки № 15/06-26.
20.06.2026 Истец поставил товар на 4 800 000 тенге.
Основной долг по состоянию на 24.08.2026 составляет 4 800 000 тенге.
Пункт 7.3 договора: за нарушение срока оплаты Покупатель уплачивает Поставщику
неустойку в размере 0,1% от суммы просроченного платежа за каждый календарный
день просрочки, но не более 10% от суммы просроченной задолженности.
Период просрочки для настоящего иска: с 11.07.2026 по 24.08.2026 включительно.
Требуется взыскать основной долг и договорную неустойку, рассчитать цену иска и государственную пошлину.
"""


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании задолженности и договорной неустойки",
        court="Специализированный межрайонный экономический суд города Алматы",
        claimant=["ТОО «Арман Снабжение»", "БИН: 000000000001"],
        defendant=["ТОО «Вектор Строй»", "БИН: 000000000002"],
        price_of_claim="4 800 000 тенге",
        facts=["Ответчик не оплатил поставленный товар."],
        legal_basis=[],
        requests=[
            "Взыскать с ответчика в пользу истца задолженность по договору поставки в размере 4 800 000 тенге."
        ],
        attachments=[],
        verification_notes=[],
        source_urls=[],
        state_duty="[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]",
    )


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


def test_full_supply_claim_restores_penalty_price_and_legal_entity_duty():
    draft = _draft()

    assert contractual_penalty_period_from_source(CASE) is not None
    assert complete_claim_relief_from_materials_exact(CASE, draft) is True

    _recalculate_price(draft)
    decision = apply_professional_state_duty(CASE, _research(), draft)

    assert any("216 000 тенге" in request and "неустой" in request.lower() for request in draft.requests)
    assert any("45 календарных дней" in fact and "216 000 тенге" in fact for fact in draft.facts)
    assert draft.price_of_claim == "5 016 000 тенге"
    assert decision.mode == "property"
    assert decision.amount == 150_480
    assert draft.state_duty.startswith("150 480 тенге")
    assert any("150 480 тенге" in request and "пошлин" in request.lower() for request in draft.requests)


def test_contractual_penalty_restoration_fails_closed_without_explicit_period():
    draft = _draft()
    context = CASE.replace(
        "Период просрочки для настоящего иска: с 11.07.2026 по 24.08.2026 включительно.",
        "Просрочка имеется, точные даты необходимо уточнить.",
    )

    assert complete_claim_relief_from_materials_exact(context, draft) is False
    assert draft.price_of_claim == "4 800 000 тенге"
    assert not any("договорную неустойку в размере" in request.lower() for request in draft.requests)
