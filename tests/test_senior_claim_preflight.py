from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.senior_claim_preflight import deterministic_claim_preflight
from korgan.senior_litigation_service import _senior_research_prompt


ARTICLE_27_RULE = (
    "Специализированные межрайонные экономические суды рассматривают споры, сторонами в которых являются "
    "физические лица, осуществляющие индивидуальную предпринимательскую деятельность без образования юридического лица, "
    "юридические лица. [основание: статья 27 ГПК РК; текст нормы: «Специализированные межрайонные экономические суды "
    "рассматривают и разрешают гражданские дела по имущественным и неимущественным спорам, сторонами в которых являются "
    "физические лица, осуществляющие индивидуальную предпринимательскую деятельность без образования юридического лица, "
    "юридические лица, а также по корпоративным спорам»; источник: https://adilet.zan.kz/rus/docs/K1500000377]"
)


def _research(*, court: str = "", economic_rule: bool = False) -> LegalResearch:
    notes = [f"VERIFIED_COURT: {court}"] if court else []
    claims = ["Проверенная норма права [основание: статья X; текст нормы: «достаточно длинный проверенный текст нормы для теста»; источник: https://adilet.zan.kz/rus/docs/TEST]"]
    if economic_rule:
        claims.append(ARTICLE_27_RULE)
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=claims,
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/TEST", "https://adilet.zan.kz/rus/docs/K1500000377"],
        notes=notes,
    )


def _draft(*, court: str, claimant: list[str], defendant: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление",
        court=court,
        claimant=claimant,
        defendant=defendant,
        price_of_claim="2 000 000 тенге",
        state_duty="20 000 тенге",
        facts=["Между сторонами возник спор.", "Истец исполнил обязательство.", "Ответчик нарушил обязательство."],
        legal_basis=["Правовое основание подтверждено VERIFIED."],
        requests=["Взыскать 2 000 000 тенге."],
        attachments=["Договор"],
        verification_notes=[],
        source_urls=[],
    )


def test_economic_court_is_blocked_when_ordinary_individual_is_party_under_verified_rule():
    court = "Специализированный межрайонный экономический суд города Алматы"
    draft = _draft(
        court=court,
        claimant=["Ахметова Гульнара Сериковна, дата рождения 12.05.1988, ИИН 880512400156"],
        defendant=["ТОО «Компания», БИН 150640012233"],
    )
    errors = deterministic_claim_preflight(
        "Потребительский спор о ремонте квартиры.",
        _research(court=court, economic_rule=True),
        draft,
    )
    assert any("экономический суд" in item.lower() for item in errors)


def test_economic_court_choice_is_not_release_ready_without_verified_subject_rule():
    court = "Специализированный межрайонный экономический суд города Алматы"
    draft = _draft(
        court=court,
        claimant=["ТОО «Истец», БИН 150640012233"],
        defendant=["ТОО «Ответчик», БИН 150640012244"],
    )
    errors = deterministic_claim_preflight("Спор двух юридических лиц.", _research(court=court), draft)
    assert any("субъектный состав" in item.lower() for item in errors)


def test_economic_court_not_blocked_by_subject_composition_when_both_legal_and_rule_verified():
    court = "Специализированный межрайонный экономический суд города Алматы"
    draft = _draft(
        court=court,
        claimant=["ТОО «Истец», БИН 150640012233"],
        defendant=["ТОО «Ответчик», БИН 150640012244"],
    )
    errors = deterministic_claim_preflight(
        "Спор двух юридических лиц.",
        _research(court=court, economic_rule=True),
        draft,
    )
    assert not any("экономический суд" in item.lower() or "субъектный состав" in item.lower() for item in errors)


def test_model_may_not_invent_subjective_moral_harm_facts():
    court = "Алмалинский районный суд города Алматы"
    draft = _draft(
        court=court,
        claimant=["Иванов Иван, дата рождения 01.01.1990, ИИН 900101300001"],
        defendant=["ТОО «Компания», БИН 150640012233"],
    )
    draft.facts.append("Нарушение вызвало у Истца нервное напряжение, переживания и стресс.")
    draft.requests.append("Взыскать компенсацию морального вреда 100 000 тенге.")
    errors = deterministic_claim_preflight(
        "Истец просит проверить возможность компенсации морального вреда. Факты о страданиях не сообщались.",
        _research(court=court),
        draft,
    )
    assert any("субъективные последствия" in item.lower() for item in errors)


def test_monetary_moral_harm_request_cannot_have_blank_amount():
    court = "Алмалинский районный суд города Алматы"
    draft = _draft(
        court=court,
        claimant=["Иванов Иван, дата рождения 01.01.1990, ИИН 900101300001"],
        defendant=["ТОО «Компания», БИН 150640012233"],
    )
    draft.requests.append("Взыскать компенсацию морального вреда в размере ________ тенге.")
    errors = deterministic_claim_preflight("Истец сообщил о переживаниях и просит моральный вред.", _research(court=court), draft)
    assert any("незаполненная" in item.lower() or "без определенного размера" in item.lower() for item in errors)


def test_exact_court_must_be_source_bound_or_user_supplied():
    draft = _draft(
        court="Медеуский районный суд города Алматы",
        claimant=["Иванов Иван, дата рождения 01.01.1990, ИИН 900101300001"],
        defendant=["Петров Петр, дата рождения 01.01.1990, ИИН 900101300002"],
    )
    errors = deterministic_claim_preflight("Истец и ответчик проживают в Алматы.", _research(), draft)
    assert any("наименование суда" in item.lower() for item in errors)


def test_senior_research_is_generic_not_hardcoded_to_prior_cases():
    prompt = _senior_research_prompt("Обычный гражданский спор", _research(), max_chars=5000)
    lowered = prompt.lower()
    assert "статус каждой стороны" in lowered
    assert "наличие одного тоо" in lowered
    assert "курылысстройинвест" not in lowered
    assert "ахметова" not in lowered
