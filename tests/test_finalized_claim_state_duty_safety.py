from korgan import finalized_litigation
from korgan.legal_calc import NEEDS_CALCULATION_MARKER
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def _draft(*, requests: list[str], notes: list[str] | None = None) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Иск о взыскании задолженности",
        court="Суд",
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы, ул. Абая, д. 10"],
        defendant=["Ответчик, адрес: г. Алматы, ул. Толе би, д. 20"],
        price_of_claim="9 999 999 тенге",
        state_duty="299 999 тенге",
        facts=[],
        legal_basis=[],
        requests=requests,
        attachments=[],
        verification_notes=list(notes or []),
        source_urls=[],
    )


def _research(*verified: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(verified),
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def test_unresolved_claim_price_overrides_any_legacy_preqa_duty(monkeypatch):
    draft = _draft(
        requests=[
            "Взыскать с ответчика 1 000 000 тенге и 250 000 тенге.",
            "Взыскать расходы по уплате государственной пошлины 299 999 тенге.",
        ],
        notes=["Цена иска требует проверки: неоднозначная денежная просительная часть."],
    )

    def fake_preqa(case_context, research, target):
        target.state_duty = "299 999 тенге (ошибочно рассчитано из старой цены)"
        target.requests.append(
            "Взыскать с ответчика расходы по уплате государственной пошлины 299 999 тенге."
        )

    monkeypatch.setattr(finalized_litigation, "_deterministic_pre_qa", fake_preqa)
    finalized_litigation._safe_deterministic_pre_qa(
        "Истец: Иванов Иван, ИИН 900101300001", _research(), draft
    )
    assert draft.state_duty == NEEDS_CALCULATION_MARKER
    assert all("пошлин" not in request.lower() for request in draft.requests)
    assert any(note.startswith("Государственная пошлина требует проверки:") for note in draft.verification_notes)
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION


def test_resolved_claim_overwrites_wrong_legacy_duty_with_canonical_amount(monkeypatch):
    draft = _draft(requests=["Взыскать задолженность 1 000 000 тенге."])

    def fake_preqa(case_context, research, target):
        target.state_duty = "299 999 тенге (ошибочная старая цена)"

    monkeypatch.setattr(finalized_litigation, "_deterministic_pre_qa", fake_preqa)
    finalized_litigation._safe_deterministic_pre_qa(
        "Истец: Иванов Иван, ИИН 900101300001", _research(), draft
    )
    assert draft.state_duty.startswith("10 000 тенге")
    duty_requests = [request for request in draft.requests if "пошлин" in request.lower()]
    assert len(duty_requests) == 1
    assert "10 000 тенге" in duty_requests[0]


def test_verified_consumer_deferral_overwrites_legacy_payment_request(monkeypatch):
    draft = _draft(requests=["Взыскать задолженность 1 000 000 тенге."])

    def fake_preqa(case_context, research, target):
        target.state_duty = "10 000 тенге"
        target.requests.append("Взыскать расходы по уплате государственной пошлины 10 000 тенге.")
        target.verification_notes.append("FILING_ACTION: приложить документ об уплате государственной пошлины.")

    research = _research(
        "Применяется Закон о защите прав потребителей [основание: статья 1; текст нормы: «потребитель»; "
        "источник: https://adilet.zan.kz/rus/docs/Z100000274_]"
    )
    monkeypatch.setattr(finalized_litigation, "_deterministic_pre_qa", fake_preqa)
    finalized_litigation._safe_deterministic_pre_qa(
        "Истец: Иванов Иван, ИИН 900101300001. Товар приобретался для личных нужд, "
        "не связанных с предпринимательской деятельностью.",
        research,
        draft,
    )
    assert "отсрочена" in draft.state_duty
    assert all("пошлин" not in request.lower() for request in draft.requests)
    assert not any("уплате государственной пошлины" in note.lower() for note in draft.verification_notes)
