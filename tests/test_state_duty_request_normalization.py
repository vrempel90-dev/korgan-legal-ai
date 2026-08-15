from korgan.fast_v2_production_legal import _normalize_state_duty_request
from korgan.legal_types import ClaimDraft, VerificationStatus


def test_state_duty_request_is_replaced_with_one_deterministic_item() -> None:
    draft = ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Иск",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="800 000 тенге",
        facts=[],
        legal_basis=[],
        requests=[
            "Взыскать долг 800 000 тенге.",
            "Взыскать госпошлину 6 500 тенге.",
            "Взыскать расходы по уплате государственной пошлины 8 000 тенге.",
        ],
        attachments=[],
        verification_notes=[],
        source_urls=[],
        state_duty="8 000 тенге (1% от цены иска)",
    )

    _normalize_state_duty_request(draft)

    duty_requests = [item for item in draft.requests if "госпошлин" in item.lower()]
    assert duty_requests == [
        "Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины в размере 8 000 тенге."
    ]
    assert "Взыскать долг 800 000 тенге." in draft.requests
