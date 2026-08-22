from __future__ import annotations

import korgan.claim_filing_accuracy as accuracy
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def test_private_b2b_draft_court_is_not_treated_as_verified_special_jurisdiction(monkeypatch) -> None:
    monkeypatch.setattr(accuracy, "_gpk27_supports_business_court", lambda: True)
    monkeypatch.setattr(
        accuracy,
        "_economic_registry_court",
        lambda city: "Специализированный межрайонный экономический суд города Алматы",
    )

    draft = ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="Специализированный межрайонный административный суд города Алматы",
        claimant=["ТОО «Альфа», БИН 190440012345, г. Алматы"],
        defendant=["ТОО «Бета», БИН 200540067890, г. Алматы"],
        price_of_claim="1 000 000 тенге",
        facts=["Задолженность возникла по договору оказания услуг."],
        legal_basis=[],
        requests=["Взыскать 1 000 000 тенге задолженности."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )
    research = LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )
    context = (
        "Истец: ТОО «Альфа», БИН 190440012345, г. Алматы.\n"
        "Ответчик: ТОО «Бета», БИН 200540067890, г. Алматы.\n"
        "Частноправовой спор по договору оказания услуг о взыскании задолженности."
    )

    accuracy._apply_court_gate(context, research, draft)

    assert draft.court == "Специализированный межрайонный экономический суд города Алматы"
    assert "административный" not in draft.court.lower()
    assert any(note == f"VERIFIED_COURT: {draft.court}" for note in research.notes)
