from __future__ import annotations

from korgan.claim_state_duty import decide_state_duty
from korgan.legal_calc import CAP_MRP_INDIVIDUAL, CAP_MRP_LEGAL_ENTITY, MRP_2026
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.party_identity import hydrate_claimant_identity, match_claimant_identity
from korgan.universal_word_final_hardening import calc_state_duty_exact


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


def _draft(claimant: list[str], amount: int = 4_800_000) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Иск о взыскании задолженности",
        court="Специализированный межрайонный экономический суд",
        claimant=list(claimant),
        defendant=["ТОО «Ответчик»"],
        price_of_claim=f"{amount:,} тенге".replace(",", " "),
        state_duty="",
        facts=[],
        legal_basis=[],
        requests=[f"Взыскать задолженность {amount:,} тенге.".replace(",", " ")],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_supplier_bin_is_restored_to_same_claimant_and_duty_is_calculated() -> None:
    context = (
        "Поставщик: ТОО «KAZTECH SOLUTIONS», БИН 230740012345, г. Алматы.\n"
        "Заказчик: ТОО «CLIENT GROUP», БИН 210540009999, г. Астана.\n"
        "Задолженность заказчика составляет 4 800 000 тенге."
    )
    draft = _draft(["KAZTECH SOLUTIONS"])

    match = hydrate_claimant_identity(context, draft.claimant)

    assert match is not None
    assert match.kind == "legal_entity"
    assert draft.claimant[-1] == "БИН 230740012345"

    decision = decide_state_duty(context, _research(), draft)
    assert decision.mode == "property"
    assert decision.amount == 144_000
    assert decision.needs_review is False


def test_matching_does_not_take_defendant_bin_for_claimant() -> None:
    context = (
        "Поставщик: KAZTECH SOLUTIONS.\n"
        "Заказчик: ТОО «CLIENT GROUP», БИН 210540009999."
    )
    claimant = ["KAZTECH SOLUTIONS"]

    assert match_claimant_identity(context, claimant) is None
    assert claimant == ["KAZTECH SOLUTIONS"]


def test_generic_shared_word_cannot_bind_defendant_bin() -> None:
    context = (
        "Поставщик: ABC GROUP.\n"
        "Заказчик: ТОО «CLIENT GROUP», БИН 210540009999."
    )

    assert match_claimant_identity(context, ["ABC GROUP"]) is None


def test_individual_iin_can_be_restored_from_contract_role() -> None:
    context = (
        "Исполнитель: Иванов Иван Иванович, ИИН 900101300001.\n"
        "Заказчик: ТОО «CLIENT GROUP», БИН 210540009999."
    )
    draft = _draft(["Иванов Иван Иванович"], amount=1_000_000)

    match = hydrate_claimant_identity(context, draft.claimant)

    assert match is not None
    assert match.kind == "individual"
    decision = decide_state_duty(context, _research(), draft)
    assert decision.amount == 10_000


def test_exact_state_duty_uses_distinct_statutory_caps() -> None:
    huge_amount = 10_000_000_000_000

    individual = calc_state_duty_exact(huge_amount, is_individual=True)
    legal_entity = calc_state_duty_exact(huge_amount, is_individual=False)

    assert individual == CAP_MRP_INDIVIDUAL * MRP_2026
    assert legal_entity == CAP_MRP_LEGAL_ENTITY * MRP_2026
    assert legal_entity == individual * 2
