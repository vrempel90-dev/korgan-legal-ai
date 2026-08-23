from __future__ import annotations

from korgan.claim_release_invariants import enforce_claim_release_invariants
from korgan.legal_types import ClaimDraft, VerificationStatus


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Иск о взыскании задолженности и договорной неустойки",
        court="Специализированный межрайонный экономический суд города Астаны",
        claimant=["ТОО «Поставщик», БИН 123456789012"],
        defendant=["ТОО «Покупатель», БИН 210987654321"],
        price_of_claim="12 996 000 тенге",
        facts=[
            "Ответчик не оплатил поставленный товар на сумму 12 000 000 тенге; данный факт подтвержден текстом претензии Истца.",
            "Задолженность не погашена и не опровергнута Ответчиком.",
        ],
        legal_basis=[
            "Иск должен соответствовать требованиям формы. Правовое основание: статья 148 ГПК РК.",
            "Покупатель обязан оплатить переданный товар. Правовое основание: статья 439 ГК РК (Особенная часть).",
        ],
        requests=[
            "Взыскать с ответчика основной долг в размере 12 000 000 тенге.",
            "Взыскать договорную неустойку в размере 996 000 тенге.",
        ],
        attachments=[],
        verification_notes=[],
        source_urls=[],
        state_duty="389 880 тенге",
    )


def test_removes_article_148_and_circular_self_evidence() -> None:
    draft = _draft()

    enforce_claim_release_invariants("Договор поставки", draft)

    assert all("148" not in item for item in draft.legal_basis)
    assert any("439" in item for item in draft.legal_basis)
    facts = "\n".join(draft.facts).lower()
    assert "подтвержден текстом претензии" not in facts
    assert "не опровергнута ответчиком" not in facts
    notes = "\n".join(draft.verification_notes).lower()
    assert "банковской выпиской" in notes
    assert "актом сверки" in notes
    assert draft.status is VerificationStatus.NEEDS_VERIFICATION


def test_restores_explicit_judicial_cost_request_without_inventing_amount() -> None:
    draft = _draft()
    context = "ПРОШУ: взыскать основной долг, неустойку и судебные расходы с Ответчика."

    enforce_claim_release_invariants(context, draft)

    requests = "\n".join(draft.requests).lower()
    assert "судебные расходы" in requests
    assert requests.count("судебные расходы") == 1
