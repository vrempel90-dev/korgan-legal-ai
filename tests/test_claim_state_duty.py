from korgan.claim_state_duty import apply_professional_state_duty, decide_state_duty
from korgan.legal_calc import NEEDS_CALCULATION_MARKER
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def _research(*verified: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(verified),
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def _draft(*, claimant: list[str], requests: list[str], title: str = "Иск") -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title=title,
        court="Суд",
        claimant=claimant,
        defendant=["Ответчик, адрес: г. Алматы, ул. Абая, д. 1"],
        price_of_claim="",
        state_duty="",
        facts=[],
        legal_basis=[],
        requests=requests,
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_physical_person_ordinary_property_claim_uses_one_percent():
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы, ул. Абая, д. 10"],
        requests=["Взыскать задолженность 1 000 000 тенге."],
    )

    decision = decide_state_duty("Истец: Иванов Иван, ИИН 900101300001", _research(), draft)

    assert decision.mode == "property"
    assert decision.amount == 10_000
    assert decision.needs_review is False


def test_legal_entity_ordinary_property_claim_uses_three_percent():
    draft = _draft(
        claimant=["ТОО «Истец», БИН 123456789012, адрес: г. Алматы, IBAN KZ000000000000000000"],
        requests=["Взыскать задолженность 1 000 000 тенге."],
    )

    decision = decide_state_duty("Истец: ТОО «Истец», БИН 123456789012", _research(), draft)

    assert decision.mode == "property"
    assert decision.amount == 30_000


def test_nonproperty_claim_uses_half_mrp():
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы, ул. Абая, д. 10"],
        requests=["Признать договор недействительным."],
    )

    decision = decide_state_duty("Истец: Иванов Иван, ИИН 900101300001", _research(), draft)

    assert decision.mode == "nonproperty"
    assert decision.amount == 2_163
    assert "0.5 МРП" in decision.line


def test_mixed_claim_adds_property_and_nonproperty_duty():
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы, ул. Абая, д. 10"],
        requests=[
            "Расторгнуть договор.",
            "Взыскать задолженность 1 000 000 тенге.",
        ],
    )

    decision = decide_state_duty("Истец: Иванов Иван, ИИН 900101300001", _research(), draft)

    assert decision.mode == "mixed"
    assert decision.amount == 12_163


def test_moral_damage_is_nonproperty_for_ordinary_case():
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы, ул. Абая, д. 10"],
        requests=["Взыскать компенсацию морального вреда 200 000 тенге."],
    )

    decision = decide_state_duty("Истец: Иванов Иван, ИИН 900101300001", _research(), draft)

    assert decision.mode == "nonproperty"
    assert decision.amount == 2_163


def test_debt_plus_moral_damage_is_mixed_not_1_percent_of_both():
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы, ул. Абая, д. 10"],
        requests=[
            "Взыскать задолженность 1 000 000 тенге.",
            "Взыскать компенсацию морального вреда 200 000 тенге.",
        ],
    )

    decision = decide_state_duty("Истец: Иванов Иван, ИИН 900101300001", _research(), draft)

    assert decision.mode == "mixed"
    assert decision.amount == 12_163


def test_grounded_consumer_claim_is_calculated_but_payment_is_deferred():
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы, ул. Абая, д. 10"],
        requests=[
            "Взыскать уплаченную по договору сумму 1 000 000 тенге.",
            "Взыскать расходы по уплате государственной пошлины 10 000 тенге.",
        ],
    )
    draft.verification_notes = [
        "FILING_ACTION: приложить документ об уплате государственной пошлины."
    ]
    research = _research(
        "К отношениям применим Закон РК о защите прав потребителей [основание: статья 1; текст нормы: «потребитель»; источник: https://adilet.zan.kz/rus/docs/Z100000274_]"
    )

    decision = apply_professional_state_duty(
        "Истец: Иванов Иван, ИИН 900101300001. Иск о защите прав потребителей.",
        research,
        draft,
    )

    assert decision.deferred is True
    assert decision.amount == 10_000
    assert "отсрочена" in draft.state_duty
    assert all("пошлин" not in request.lower() for request in draft.requests)
    assert not any("пошлин" in note.lower() and "приложить" in note.lower() for note in draft.verification_notes)


def test_special_statutory_category_fails_closed_instead_of_using_ordinary_rate():
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы, ул. Абая, д. 10"],
        requests=["Расторгнуть брак."],
        title="Иск о расторжении брака",
    )

    decision = decide_state_duty("Истец: Иванов Иван, ИИН 900101300001", _research(), draft)

    assert decision.mode == "special"
    assert decision.line == NEEDS_CALCULATION_MARKER
    assert decision.needs_review is True
