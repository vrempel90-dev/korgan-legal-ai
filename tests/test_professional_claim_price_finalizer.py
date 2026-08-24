from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.professional_claim_finalizer import _recalculate_price


def _draft(requests: list[str], *, price: str = "99 999 999 тенге") -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Иск",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim=price,
        state_duty="",
        facts=[],
        legal_basis=[],
        requests=requests,
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_finalizer_uses_total_once_for_debt_and_penalty():
    draft = _draft([
        "Взыскать основной долг 12 000 000 тенге и неустойку 996 000 тенге, итого 12 996 000 тенге."
    ])
    _recalculate_price(draft)
    assert draft.price_of_claim == "12 996 000 тенге"
    assert not draft.verification_notes


def test_finalizer_excludes_state_duty_and_representation_costs():
    draft = _draft([
        "Взыскать задолженность 1 000 000 тенге.",
        "Взыскать государственную пошлину 10 000 тенге.",
        "Взыскать расходы на оплату услуг представителя 150 000 тенге.",
    ])
    _recalculate_price(draft)
    assert draft.price_of_claim == "1 000 000 тенге"


def test_finalizer_keeps_moral_damage_out_of_property_price():
    draft = _draft([
        "Взыскать задолженность 1 000 000 тенге.",
        "Взыскать компенсацию морального вреда 200 000 тенге.",
    ])
    _recalculate_price(draft)
    assert draft.price_of_claim == "1 000 000 тенге"


def test_finalizer_fails_closed_on_wrong_explicit_total():
    draft = _draft([
        "Взыскать основной долг 1 000 000 тенге и неустойку 200 000 тенге, итого 1 500 000 тенге."
    ])
    _recalculate_price(draft)
    assert draft.price_of_claim == "99 999 999 тенге"
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert any(note.startswith("Цена иска требует проверки:") for note in draft.verification_notes)
