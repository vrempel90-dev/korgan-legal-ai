from korgan.claim_docx import build_claim_docx
from korgan.document_quality import MIN_READY_SCORE, assess_document_quality, docx_text
from korgan.document_release import review_lines
from korgan.legal_calc import claimant_is_individual, gosposhlina_line
from korgan.legal_types import ClaimDraft, ContractDraft, LegalResearch, VerificationStatus
from korgan.provision_check import verified_claim_line
from korgan.response_types import ResponseToClaimDraft


def research(*claims: str, notes: list[str] | None = None) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(claims),
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/example"],
        notes=list(notes or []),
    )


def live_loan_rule() -> str:
    provision = (
        "Заемщик обязан возвратить заимодателю полученную сумму займа в срок и в порядке, "
        "которые предусмотрены договором."
    )
    statement = (
        "Заемщик обязан возвратить заимодателю полученную сумму займа в срок и порядке, "
        "предусмотренных договором."
    )
    return verified_claim_line(
        statement,
        "статья 722 ГК РК",
        provision,
        "https://adilet.zan.kz/rus/docs/K990000409_",
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
        facts=["Заключен договор займа.", "Деньги переданы истцом.", "Ответчик сумму займа не возвратил."],
        legal_basis=["В соответствии со статьей 722 ГК РК заемщик обязан возвратить сумму займа."],
        requests=["Взыскать 1 000 000 тенге суммы займа."],
        attachments=["Договор", "Платежный документ"],
        verification_notes=[],
        source_urls=[],
    )
    report = assess_document_quality(
        "claim",
        "Истец: Иванов Иван Иванович, ИИН 900101300001\nОтветчик: Петров Петр Петрович, ИИН 900101300002",
        research(live_loan_rule()),
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


def test_state_duty_role_lock_also_works_when_parties_are_on_one_line():
    context = (
        "Истец: Ахметова Гульнара Сериковна, ИИН 880512400156, адрес: г. Алматы; "
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


def test_live_source_bound_article_passes_without_static_corpus_record():
    rule = live_loan_rule()
    line = "В соответствии со статьей 722 ГК РК заемщик обязан возвратить заимодателю полученную сумму займа."

    with_live = review_lines([line], verified_claims=[rule])
    without_live = review_lines([line], verified_claims=[])

    assert not with_live.citations.blocking
    assert without_live.citations.blocking


def test_fully_supported_claim_reaches_quality_bar_and_exports_clean_docx():
    rule = live_loan_rule()
    context = (
        "В Алмалинский районный суд города Алматы.\n"
        "Истец: Иванов Иван Иванович, ИИН 900101300001, адрес: г. Алматы, ул. Абая, 10.\n"
        "Ответчик: Петров Петр Петрович, ИИН 900101300002, адрес: г. Алматы, ул. Толе би, 20.\n"
        "По договору займа истец передал ответчику 1 000 000 тенге. Срок возврата наступил, деньги не возвращены. "
        "Имеются договор займа, расписка и банковская квитанция."
    )
    draft = ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании суммы займа",
        court="Алмалинский районный суд города Алматы",
        claimant=["Иванов Иван Иванович, ИИН 900101300001, адрес: г. Алматы, ул. Абая, 10"],
        defendant=["Петров Петр Петрович, ИИН 900101300002, адрес: г. Алматы, ул. Толе би, 20"],
        price_of_claim="1 000 000 тенге",
        state_duty=gosposhlina_line(context, "1 000 000 тенге"),
        facts=[
            "Между сторонами заключен договор займа.",
            "Истец передал ответчику 1 000 000 тенге, что подтверждается распиской и банковской квитанцией.",
            "Срок возврата наступил, однако ответчик сумму займа не возвратил.",
        ],
        legal_basis=[
            "В соответствии со статьей 722 ГК РК заемщик обязан возвратить заимодателю полученную сумму займа в предусмотренный договором срок."
        ],
        requests=["Взыскать с ответчика в пользу истца 1 000 000 тенге суммы займа."],
        attachments=["Договор займа", "Расписка", "Банковская квитанция"],
        verification_notes=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
    )
    legal_research = research(rule)

    report = assess_document_quality("claim", context, legal_research, draft)
    assert report.ready, (report.score, report.hard_blockers, report.issues, report.category_scores)
    assert report.score >= MIN_READY_SCORE

    file_bytes = build_claim_docx(draft)
    text = docx_text(file_bytes).lower()
    assert "korgan qa status" not in text
    assert "preliminary draft" not in text
    assert "[требует уточнения" not in text


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
