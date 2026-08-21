from korgan.claim_quality_gate import MIN_READY_SCORE, assess_claim_quality
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


CASE = """
Истец: Ахметова Гульнара Сериковна, ИИН 880512400156, дата рождения 12.05.1988,
адрес: г. Алматы, Медеуский район, ул. Абая, 150, кв. 34.
Ответчик: ТОО «КурылысСтройИнвест», БИН 150640012233, адрес: г. Алматы,
Алатауский район, ул. Момышулы, 5.
12.05.2025 заключен договор подряда №45 на ремонт квартиры стоимостью 3 500 000 тенге.
Истец перечислил предоплату 2 300 000 тенге. Работы должны быть закончены до 20.06.2025,
но подрядчик к работам не приступил. 20.07.2025 направлена претензия о возврате предоплаты.
Имеются договор, банковская квитанция и копия претензии.
"""


def research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            "Статья 627 ГК РК: подтвержденное право заказчика при несвоевременном начале работ [основание: статья 627 ГК РК; источник: https://adilet.zan.kz/]",
            "Статья 640 ГК РК: подтвержденная квалификация бытового подряда [основание: статья 640 ГК РК; источник: https://adilet.zan.kz/]",
        ],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/"],
        notes=[],
    )


def old_bad_draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление о взыскании уплаченной предоплаты по договору подряда",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда]",
        claimant=[
            "Ахметова Гульнара Сериковна, ИИН 880512400156, адрес: г. Алматы, ул. Абая, 150",
            "Банковские реквизиты: [ТРЕБУЕТ УТОЧНЕНИЯ: банковские реквизиты истца]",
        ],
        defendant=[
            "ТОО «КурылысСтройИнвест», БИН 150640012233, адрес: г. Алматы, ул. Момышулы, 5",
            "[ТРЕБУЕТ УТОЧНЕНИЯ: ФИО ответчика полностью]",
        ],
        price_of_claim="2 300 000 тенге",
        facts=[
            "12 мая 2025 года заключен договор подряда №45.",
            "Истец перечислил предоплату 2 300 000 тенге.",
            "Ответчик к работам не приступил и деньги не вернул.",
        ],
        legal_basis=[
            "Нормы Гражданского кодекса Республики Казахстан об обязательствах.",
            "Нормы о подряде и неосновательном обогащении.",
        ],
        requests=["Взыскать с ответчика 2 300 000 тенге предоплаты."],
        attachments=["Договор №45", "Банковская квитанция", "Копия претензии"],
        verification_notes=[],
        source_urls=["https://adilet.zan.kz/"],
        state_duty="[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]",
    )


def test_old_screenshot_style_claim_fails_quality_bar_and_normalizes_parties():
    draft = old_bad_draft()
    report = assess_claim_quality(CASE, research(), draft)

    assert report.score < MIN_READY_SCORE
    assert not any("ФИО ответчика" in line for line in draft.defendant)
    assert not any("Банковские реквизиты" in line for line in draft.claimant)
    assert any("конкретных статей" in issue for issue in report.issues)


def test_court_ready_repaired_claim_passes_85_bar():
    draft = old_bad_draft()
    draft.court = "Районный суд города Алматы"
    draft.state_duty = "23 000 тенге"
    draft.legal_basis = [
        "В соответствии со статьей 627 ГК РК несвоевременное начало работ дает заказчику предусмотренные законом способы защиты; подрядчик к работам не приступил.",
        "Правоотношения сторон относятся к бытовому подряду по статье 640 ГК РК, поскольку ремонт квартиры выполнялся для личных нужд гражданина.",
    ]
    draft.requests = [
        "Прекратить договорные отношения вследствие нарушения подрядчиком срока начала и выполнения работ.",
        "Взыскать с ответчика 2 300 000 тенге уплаченной предоплаты.",
    ]
    draft.verification_notes = []

    report = assess_claim_quality(CASE, research(), draft)
    assert report.score >= MIN_READY_SCORE, (report.score, report.issues, report.category_scores)
