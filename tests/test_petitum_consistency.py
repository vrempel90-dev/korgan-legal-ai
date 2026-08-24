from datetime import date

from korgan.claim_quality_gate import ClaimQualityReport, assess_claim_quality, check_amount_consistency
from korgan.late_interest_hotfix import _apply_verified_penalty
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


CASE_CONTEXT = """
Истец: ТОО «KAZTECH SOLUTIONS», БИН 230740012345
Ответчик: ТОО «ASTANA INDUSTRY GROUP», БИН 210940067891
15.05.2026 заключен договор поставки № KT-15/05-26. 20.05.2026 поставлен товар
на 12 000 000 тенге. Пункт 3.2: оплата в течение 10 календарных дней.
Срок оплаты истек 30.05.2026.
Пункт 6.3 договора: неустойка 0,1% от суммы задолженности за каждый день
просрочки, но не более 10% от суммы задолженности.
Прошу взыскать основной долг и договорную неустойку с 31.05.2026.
"""


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании задолженности и договорной неустойки по договору поставки",
        court="СМЭС города Астаны",
        claimant=["ТОО «KAZTECH SOLUTIONS»"],
        defendant=["ТОО «ASTANA INDUSTRY GROUP»"],
        price_of_claim="12 996 000 тенге",
        facts=["Задолженность 12 000 000 тенге основного долга и 996 000 тенге неустойки, всего 12 996 000 тенге."],
        legal_basis=["Обязанность покупателя оплатить принятый товар."],
        requests=[
            "Взыскать основной долг 12 000 000 тенге.",
            "Взыскать договорную неустойку по пункту 6.3 договора в размере 996 000 тенге.",
            "Взыскать расходы по уплате государственной пошлины.",
        ],
        attachments=["Расчет договорной неустойки на 996 000 тенге."],
        verification_notes=[],
        source_urls=[],
    )


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=["ГК РК (Особенная часть), договор поставки"],
        procedural_requirements=[],
        verified_claims=["Покупатель обязан оплатить принятый товар."],
        unverified_claims=[],
        notes=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
    )


def test_contractual_penalty_survives_petitum_and_duty_recalculation() -> None:
    draft = _draft()
    _apply_verified_penalty(CASE_CONTEXT, _research(), draft, filing_date=date(2026, 8, 21))

    assert any("договорную неустойку" in item.lower() and "996 000 тенге" in item for item in draft.requests)
    assert "12 996 000 тенге" in draft.price_of_claim
    assert "389 880 тенге" in draft.state_duty
    assert check_amount_consistency(draft) == []


def test_exact_reproduction_filing_date_recalculates_through_august_23() -> None:
    """The task's pasted reproduction uses 23.08; that is 85 inclusive days, not 83."""
    draft = _draft()
    _apply_verified_penalty(CASE_CONTEXT, _research(), draft, filing_date=date(2026, 8, 23))

    assert any("1 020 000 тенге" in item for item in draft.requests if "неустой" in item.lower())
    assert "13 020 000 тенге" in draft.price_of_claim
    assert "390 600 тенге" in draft.state_duty
    assert all("996 000" not in str(item) for item in draft.facts)
    assert all("996 000" not in str(item) for item in draft.attachments)
    assert check_amount_consistency(draft) == []


def test_amount_consistency_detects_penalty_removed_from_petitum() -> None:
    draft = _draft()
    _apply_verified_penalty(CASE_CONTEXT, _research(), draft, filing_date=date(2026, 8, 21))
    draft.requests = [item for item in draft.requests if "неустой" not in item.lower()]

    errors = check_amount_consistency(draft)
    assert errors
    assert any("996 000" in item or "неустой" in item.lower() for item in errors)


def test_historical_payment_and_contract_price_do_not_create_amount_mismatch() -> None:
    draft = _draft()
    draft.title = "Исковое заявление о взыскании задолженности"
    draft.price_of_claim = "12 000 000 тенге"
    draft.requests = ["Взыскать основной долг 12 000 000 тенге."]
    draft.facts = [
        "Цена договора составила 15 000 000 тенге; ответчик частично оплатил 3 000 000 тенге; остаток задолженности составляет 12 000 000 тенге."
    ]
    draft.attachments = []

    assert check_amount_consistency(draft) == []


def test_nonproperty_amount_on_same_line_does_not_hide_unclaimed_debt() -> None:
    draft = _draft()
    draft.title = "Исковое заявление о взыскании задолженности"
    draft.price_of_claim = "10 000 000 тенге"
    draft.requests = ["Взыскать основной долг 10 000 000 тенге."]
    draft.facts = [
        "Задолженность составляет 12 000 000 тенге; судебные расходы составили 100 000 тенге."
    ]
    draft.attachments = []

    errors = check_amount_consistency(draft)

    assert any("12 000 000" in item for item in errors)
    assert all("100 000" not in item for item in errors)


def test_explicit_penalty_with_unknown_due_date_is_kept_for_verification() -> None:
    context = (
        "Истец: ТОО «A», БИН 230740012345. Ответчик: ТОО «B», БИН 210940067891. "
        "Пункт 6.3 договора: неустойка 0,1% за каждый день просрочки, но не более 10%. "
        "Прошу взыскать долг 12 000 000 тенге и договорную неустойку."
    )
    draft = _draft()
    _apply_verified_penalty(context, _research(), draft, filing_date=date(2026, 8, 21))

    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert any("ТРЕБУЕТ ПРОВЕРКИ" in item and "неустой" in item.lower() for item in draft.requests)
    assert all("12 000 000" not in item for item in draft.requests if "неустой" in item.lower())
    assert "ТРЕБУЕТ РАСЧЁТА" in draft.price_of_claim
    assert any("дату начала просрочки" in note for note in draft.verification_notes)


def test_penalty_before_principal_does_not_bind_principal_amount_to_penalty() -> None:
    context = (
        "Истец: ТОО «A», БИН 230740012345. Ответчик: ТОО «B», БИН 210940067891. "
        "Пункт 6.3 договора: неустойка 0,1% за каждый день просрочки. "
        "Прошу взыскать договорную неустойку и основной долг в размере 12 000 000 тенге."
    )
    draft = _draft()
    _apply_verified_penalty(context, _research(), draft, filing_date=date(2026, 8, 21))

    penalty_requests = [item for item in draft.requests if "неустой" in item.lower()]
    assert penalty_requests
    assert all("12 000 000" not in item for item in penalty_requests)
    assert all("ТРЕБУЕТ ПРОВЕРКИ" in item for item in penalty_requests)
    assert "ТРЕБУЕТ РАСЧЁТА" in draft.price_of_claim


def test_source_bound_penalty_amount_stays_unresolved_until_due_date_is_verified() -> None:
    context = (
        "Истец: ТОО «A», БИН 230740012345. Ответчик: ТОО «B», БИН 210940067891. "
        "Пункт 6.3 договора: неустойка 0,1% за каждый день просрочки, но не более 10%. "
        "Прошу взыскать основной долг 12 000 000 тенге и договорную неустойку 996 000 тенге."
    )
    draft = _draft()
    _apply_verified_penalty(context, _research(), draft, filing_date=date(2026, 8, 21))

    penalty_requests = [item for item in draft.requests if "неустой" in item.lower()]
    assert any("996 000 тенге" in item and "ТРЕБУЕТ ПРОВЕРКИ" in item for item in penalty_requests)
    assert "ТРЕБУЕТ РАСЧЁТА" in draft.price_of_claim
    assert "ТРЕБУЕТ РАСЧ" in draft.state_duty


def test_unrequested_model_penalty_is_removed_from_all_fields() -> None:
    context = (
        "Истец: ТОО «A», БИН 230740012345. Ответчик: ТОО «B», БИН 210940067891. "
        "Прошу взыскать только основной долг 12 000 000 тенге."
    )
    draft = _draft()
    _apply_verified_penalty(context, _research(), draft, filing_date=date(2026, 8, 21))

    assert not any("неустой" in item.lower() for item in draft.requests)
    assert not any("неустой" in item.lower() for item in draft.legal_basis)
    assert not any("неустой" in item.lower() for item in draft.facts)
    assert not any("неустой" in item.lower() for item in draft.attachments)
    assert "неустой" not in draft.title.lower()
    assert draft.late_interest == ""


def test_title_amount_cannot_disappear_from_petitum_and_price() -> None:
    draft = _draft()
    draft.title = "Исковое заявление о взыскании договорной неустойки 996 000 тенге"
    draft.price_of_claim = "13 000 000 тенге"
    draft.requests = [
        "Взыскать основной долг 12 000 000 тенге.",
        "Взыскать договорную неустойку 1 000 000 тенге.",
    ]
    draft.facts = []
    draft.attachments = []

    errors = check_amount_consistency(draft)

    assert any("996 000" in item and "title" in item for item in errors)


def test_amount_mismatch_is_unconditionally_blocking_for_ready() -> None:
    report = ClaimQualityReport(
        score=10.0,
        issues=["AMOUNT_MISMATCH: сумма санкции отсутствует в петитуме"],
        category_scores={},
    )
    assert report.ready is False


def test_assess_claim_quality_marks_amount_mismatch_not_ready() -> None:
    draft = _draft()
    draft.requests = [item for item in draft.requests if "неустой" not in item.lower()]

    report = assess_claim_quality(CASE_CONTEXT, _research(), draft)

    assert any(item.startswith("AMOUNT_MISMATCH:") for item in report.issues)
    assert report.ready is False


def test_reversed_kazakh_contractual_rate_stays_on_contractual_path() -> None:
    context = (
        "Истец: ТОО «A», БИН 230740012345. Ответчик: ТОО «B», БИН 210940067891. "
        "Шарттың 6.3-тармағында тұрақсыздық айыбы әрбір кешіктірілген күн үшін 0,1%, "
        "бірақ жалпы мөлшері 10%-дан аспайды деп белгіленген. "
        "Срок оплаты истек 30.05.2026. "
        "Талап етемін негізгі берешекті және тұрақсыздық айыбын өндіріп алуды."
    )
    draft = _draft()

    _apply_verified_penalty(context, _research(), draft, filing_date=date(2026, 8, 21))

    assert any("договорную неустойку" in item.lower() and "996 000 тенге" in item for item in draft.requests)
    assert any("Пунктом 6.3 договора" in item and "0.1%" in item and "10%" in item for item in draft.legal_basis)
    assert not any("статьи 353" in item.lower() for item in draft.legal_basis)
    assert "12 996 000 тенге" in draft.price_of_claim
