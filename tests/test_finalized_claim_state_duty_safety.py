from korgan import finalized_litigation
from korgan.legal_calc import NEEDS_CALCULATION_MARKER
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.production_legal import STATE_DUTY_NOTE


def _draft(notes: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Иск",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="9 999 999 тенге",
        state_duty="299 999 тенге",
        facts=[],
        legal_basis=[],
        requests=[
            "Взыскать 1 000 000 тенге и 250 000 тенге.",
            "Взыскать расходы по уплате государственной пошлины 299 999 тенге.",
        ],
        attachments=[],
        verification_notes=notes,
        source_urls=[],
    )


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def test_unresolved_claim_price_overrides_any_preqa_duty(monkeypatch):
    draft = _draft([
        "Цена иска требует проверки: неоднозначная денежная просительная часть."
    ])

    def fake_preqa(case_context, research, target):
        target.state_duty = "299 999 тенге (ошибочно рассчитано из старой цены)"
        target.requests.append(
            "Взыскать с ответчика расходы по уплате государственной пошлины 299 999 тенге."
        )

    monkeypatch.setattr(finalized_litigation, "_deterministic_pre_qa", fake_preqa)

    finalized_litigation._safe_deterministic_pre_qa("материалы", _research(), draft)

    assert draft.state_duty == NEEDS_CALCULATION_MARKER
    assert all("пошлин" not in request.lower() for request in draft.requests)
    assert STATE_DUTY_NOTE in draft.verification_notes
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION


def test_resolved_claim_keeps_existing_preqa_behavior(monkeypatch):
    draft = _draft([])

    def fake_preqa(case_context, research, target):
        target.state_duty = "30 000 тенге"

    monkeypatch.setattr(finalized_litigation, "_deterministic_pre_qa", fake_preqa)

    finalized_litigation._safe_deterministic_pre_qa("материалы", _research(), draft)

    assert draft.state_duty == "30 000 тенге"
    assert STATE_DUTY_NOTE not in draft.verification_notes
