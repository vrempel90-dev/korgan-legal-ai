from korgan.document_quality import MIN_READY_SCORE, assess_document_quality
from korgan.legal_calc import claimant_is_individual, gosposhlina_line
from korgan.legal_types import ClaimDraft, ContractDraft, ContractSection, LegalResearch, VerificationStatus
from korgan.response_types import ResponseObjection, ResponseToClaimDraft


def research(*claims: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(claims),
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/example"],
        notes=[],
    )


def test_hard_blocker_can_never_be_offset_by_good_claim_sections():
    draft = ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда]",
        claimant=["Иванов Иван Иванович, ИИН 900101300001, адрес: г. Алматы"],
        defendant=["Петров Петр Петрович, ИИН 900101300002, адрес: г. Алматы"],
        price_of_claim="1 000 000 тенге",
        state_duty="10 000 тенге",
        facts=["Заключен договор.", "Обязательство исполнено истцом.", "Ответчик обязательство нарушил."],
        legal_basis=["В соответствии со статьей 722 ГК РК заемщик обязан возвратить сумму займа."],
        requests=["Взыскать 1 000 000 тенге."],
        attachments=["Договор", "Платежный документ"],
        verification_notes=[],
        source_urls=[],
    )
    report = assess_document_quality(
        "claim",
        "Истец: Иванов Иван Иванович, ИИН 900101300001\nОтветчик: Петров Петр Петрович, ИИН 900101300002",
        research("Статья 722 ГК РК подтверждает обязанность возврата займа."),
        draft,
    )
    assert not report.ready
    assert report.score < MIN_READY_SCORE
    assert any("суд" in item.lower() for item in report.hard_blockers)


def test_state_duty_party_type_is_role_bound_not_case_wide():
    context = (
        "Истец: Ахметова Гульнара Сериковна, ИИН 880512400156, адрес: г. Алматы\n"
        "Ответчик: ТОО «Компания», БИН 150640012233, адрес: г. Алматы"
    )
    assert claimant_is_individual(context) is True
    assert gosposhlina_line(context, "2 300 000 тенге").startswith("23 000 тенге")


def test_legal_entity_claimant_uses_legal_entity_rate_even_with_person_defendant():
    context = (
        "Истец: ТОО «Компания», БИН 150640012233, адрес: г. Алматы\n"
        "Ответчик: Иванов Иван Иванович, ИИН 900101300001, адрес: г. Алматы"
    )
    assert claimant_is_individual(context) is False
    assert gosposhlina_line(context, "2 300 000 тенге").startswith("69 000 тенге")


def test_contract_with_missing_essential_structure_cannot_be_ready():
    draft = ContractDraft(
        status=VerificationStatus.VERIFIED,
        contract_type="договор оказания услуг",
        title="ДОГОВОР ОКАЗАНИЯ УСЛУГ",
        place_and_date="г. Алматы, 16.08.2026",
        party_a=["ТОО «Заказчик», БИН 150640012233"],
        party_b=["ТОО «Исполнитель», БИН 150640012244"],
        preamble=[],
        sections=[],
        requisites_a=["ТОО «Заказчик», БИН 150640012233"],
        requisites_b=["ТОО «Исполнитель», БИН 150640012244"],
        verification_notes=[],
        source_urls=[],
    )
    report = assess_document_quality(
        "contract",
        "Стороны: ТОО «Заказчик», БИН 150640012233; ТОО «Исполнитель», БИН 150640012244",
        research("Договорная конструкция подтверждена действующим правом."),
        draft,
    )
    assert not report.ready
    assert report.score < MIN_READY_SCORE
    assert any("услов" in item.lower() or "преамбул" in item.lower() for item in report.hard_blockers)


def test_response_without_position_and_objections_cannot_be_ready():
    draft = ResponseToClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ОТЗЫВ НА ИСК",
        court="Районный суд города Алматы",
        case_number="1234-26-00-2/0001",
        claimant=["Истец: Иванов Иван Иванович"],
        defendant=["Ответчик: Петров Петр Петрович"],
        claim_summary=["Истец просит взыскать задолженность."],
        position=[],
        objections=[],
        legal_basis=["В соответствии со статьей 166 ГПК РК ответчик представляет отзыв."],
        requests=["Отказать в удовлетворении иска при наличии установленных оснований."],
        attachments=["Копия отзыва"],
        verification_notes=[],
        source_urls=[],
    )
    report = assess_document_quality(
        "response_to_claim",
        "Истец: Иванов Иван Иванович. Ответчик: Петров Петр Петрович. Требование: взыскать задолженность.",
        research("Статья 166 ГПК РК регулирует отзыв на иск."),
        draft,
    )
    assert not report.ready
    assert report.score < MIN_READY_SCORE
    assert any("позици" in item.lower() or "возраж" in item.lower() for item in report.hard_blockers)
