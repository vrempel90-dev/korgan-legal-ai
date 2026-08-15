from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.state_duty_final_hotfix import _enforce_single_state_duty_request


def _draft(requests: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: суд]",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="800 000 тенге",
        facts=[],
        legal_basis=[],
        requests=requests,
        attachments=[],
        verification_notes=[],
        source_urls=[],
        state_duty="8 000 тенге (1% от цены иска)",
    )


def test_state_duty_variants_collapse_to_one_request() -> None:
    draft = _draft([
        "Взыскать долг 800 000 тенге.",
        "Взыскать госпошлину 8 000 тенге.",
        "Взыскать расходы по уплате государственной пошлины в размере 8 000 тенге.",
    ])

    _enforce_single_state_duty_request(draft)

    duty_requests = [x for x in draft.requests if "пошлин" in x.lower()]
    assert len(duty_requests) == 1
    assert duty_requests[0].endswith("8 000 тенге.")
    assert draft.requests[0] == "Взыскать долг 800 000 тенге."
