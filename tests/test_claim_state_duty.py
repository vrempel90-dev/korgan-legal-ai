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
        requests=["Расторгнуть договор.", "Взыскать задолженность 1 000 000 тенге."],
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


def test_debt_plus_moral_damage_is_mixed_not_one_percent_of_both():
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
    draft.verification_notes = ["FILING_ACTION: приложить документ об уплате государственной пошлины."]
    research = _research(
        "К отношениям применим Закон РК о защите прав потребителей [основание: статья 1; "
        "текст нормы: «потребитель»; источник: https://adilet.zan.kz/rus/docs/Z100000274_]"
    )
    # Основание отсрочки — не только подтверждённая норма, но и установленная
    # цель приобретения: без неё истец под определение потребителя не подпадает.
    decision = apply_professional_state_duty(
        "Истец: Иванов Иван, ИИН 900101300001. Услуга приобреталась для личных нужд, "
        "не связанных с предпринимательской деятельностью.",
        research,
        draft,
    )
    assert decision.deferred is True
    assert decision.amount == 10_000
    assert "отсрочена" in draft.state_duty
    assert all("пошлин" not in request.lower() for request in draft.requests)
    assert not any("пошлин" in note.lower() and "приложить" in note.lower() for note in draft.verification_notes)


def test_unverified_consumer_word_does_not_create_deferral():
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы, ул. Абая, д. 10"],
        requests=["Взыскать задолженность 1 000 000 тенге."],
    )
    context = "Истец: Иванов Иван, ИИН 900101300001. Ответчик спорит, что истец является потребителем."
    decision = decide_state_duty(context, _research(), draft)
    assert decision.mode == "property"
    assert decision.amount == 10_000
    assert decision.deferred is False


def test_disability_exemption_is_not_overwritten_by_property_rate():
    draft = _draft(
        claimant=["Иванов Иван, лицо с инвалидностью, ИИН 900101300001, адрес: г. Алматы"],
        requests=[
            "Взыскать задолженность 1 000 000 тенге.",
            "Взыскать расходы по уплате государственной пошлины 10 000 тенге.",
        ],
    )
    draft.verification_notes = ["FILING_ACTION: приложить документ об уплате государственной пошлины."]
    decision = apply_professional_state_duty(
        "Истец: Иванов Иван, лицо с инвалидностью, ИИН 900101300001.", _research(), draft
    )
    assert decision.exempt is True
    assert decision.amount == 0
    assert "пункт 13 статьи 668" in draft.state_duty
    assert all("пошлин" not in request.lower() for request in draft.requests)
    assert not any("уплате государственной пошлины" in note.lower() for note in draft.verification_notes)
    assert any("подтверждающий льготу" in note.lower() for note in draft.verification_notes)


def test_disability_proof_clears_exemption_proof_action():
    draft = _draft(
        claimant=["Иванов Иван, лицо с инвалидностью, ИИН 900101300001, адрес: г. Алматы"],
        requests=["Взыскать задолженность 1 000 000 тенге."],
    )
    draft.attachments = ["Справка об инвалидности истца"]
    apply_professional_state_duty(
        "Истец: Иванов Иван, лицо с инвалидностью, ИИН 900101300001.", _research(), draft
    )
    assert not any("подтверждающий льготу" in note.lower() for note in draft.verification_notes)


def test_alimony_claim_is_exempt_under_article_668():
    draft = _draft(
        claimant=["Иванова Анна, ИИН 900101300001, адрес: г. Алматы"],
        requests=["Взыскать алименты на содержание ребенка."],
    )
    decision = decide_state_duty("Истец: Иванова Анна, ИИН 900101300001", _research(), draft)
    assert decision.exempt is True
    assert decision.amount == 0
    assert "пункт 4 статьи 668" in decision.line


def test_wage_claim_is_exempt_under_article_668():
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы"],
        requests=["Взыскать заработную плату 500 000 тенге."],
    )
    decision = decide_state_duty("Истец: Иванов Иван, ИИН 900101300001", _research(), draft)
    assert decision.exempt is True
    assert decision.amount == 0
    assert "пункт 1 статьи 668" in decision.line


def test_alimony_exemption_does_not_pay_the_duty_of_a_joined_divorce_claim():
    """Освобождение по одному требованию не оплачивает второе.

    Расторжение брака и взыскание алиментов заявляются одним иском постоянно.
    Освобождение по пункту 4 статьи 668 НК РК относится к алиментному
    требованию; требование о расторжении брака оно не покрывает. Проставленный
    на весь иск ноль означал бы недоплату пошлины — то есть возврат иска судом.
    """
    draft = _draft(
        claimant=["Иванова Анна, ИИН 900101300001, адрес: г. Алматы"],
        requests=["Расторгнуть брак.", "Взыскать алименты на содержание ребенка."],
        title="Иск о расторжении брака и взыскании алиментов",
    )

    decision = decide_state_duty("Истец: Иванова Анна, ИИН 900101300001", _research(), draft)

    assert decision.exempt is False
    assert decision.needs_review is True
    assert decision.line == NEEDS_CALCULATION_MARKER
    assert "освобожд" in decision.note.lower()


def test_wage_exemption_does_not_pay_the_duty_of_an_unrelated_money_claim():
    """Заём не вытекает из трудовых отношений и своей пошлины не теряет."""
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы"],
        requests=[
            "Взыскать заработную плату 500 000 тенге.",
            "Взыскать задолженность по договору займа 2 000 000 тенге.",
        ],
    )

    decision = decide_state_duty("Истец: Иванов Иван, ИИН 900101300001", _research(), draft)

    assert decision.exempt is False
    assert decision.needs_review is True
    assert decision.line == NEEDS_CALCULATION_MARKER


def test_exemption_survives_state_duty_cost_and_procedural_requests():
    """Просьба о расходах и ходатайство пошлиной не облагаются."""
    draft = _draft(
        claimant=["Иванова Анна, ИИН 900101300001, адрес: г. Алматы"],
        requests=[
            "Взыскать алименты на содержание ребенка.",
            "Взыскать с ответчика в пользу истца документально подтвержденные судебные расходы.",
            "Истребовать у работодателя ответчика справку о доходах.",
        ],
    )

    decision = decide_state_duty("Истец: Иванова Анна, ИИН 900101300001", _research(), draft)

    assert decision.exempt is True
    assert decision.amount == 0


def test_personal_disability_exemption_covers_the_whole_claim():
    """Льгота по инвалидности принадлежит истцу, а не отдельному требованию."""
    draft = _draft(
        claimant=["Иванов Иван, лицо с инвалидностью, ИИН 900101300001, адрес: г. Алматы"],
        requests=[
            "Взыскать задолженность 1 000 000 тенге.",
            "Признать договор недействительным.",
        ],
    )

    decision = decide_state_duty(
        "Истец: Иванов Иван, лицо с инвалидностью, ИИН 900101300001", _research(), draft
    )

    assert decision.exempt is True
    assert decision.amount == 0


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


def test_incidental_special_category_words_in_case_history_do_not_change_final_relief_route():
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы, ул. Абая, д. 10"],
        requests=["Взыскать задолженность 1 000 000 тенге."],
        title="Иск о взыскании задолженности",
    )
    context = (
        "Истец: Иванов Иван, ИИН 900101300001. В переписке ответчик утверждал, что возможны "
        "банкротство и судебный приказ, однако настоящий иск заявлен только о взыскании долга."
    )
    decision = decide_state_duty(context, _research(), draft)
    assert decision.mode == "property"
    assert decision.amount == 10_000


def test_multiple_distinct_nonproperty_demands_fail_closed_until_legal_classification():
    draft = _draft(
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы, ул. Абая, д. 10"],
        requests=[
            "Признать договор недействительным.",
            "Обязать ответчика прекратить использование имущества.",
        ],
    )
    decision = decide_state_duty("Истец: Иванов Иван, ИИН 900101300001", _research(), draft)
    assert decision.mode == "multiple_nonproperty"
    assert decision.line == NEEDS_CALCULATION_MARKER
    assert decision.needs_review is True
