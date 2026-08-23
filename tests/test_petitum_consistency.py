from datetime import date

from korgan.claim_quality_gate import check_amount_consistency
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
    assert check_amount_consistency(draft) == []


def test_amount_consistency_detects_penalty_removed_from_petitum() -> None:
    draft = _draft()
    _apply_verified_penalty(CASE_CONTEXT, _research(), draft, filing_date=date(2026, 8, 21))
    draft.requests = [item for item in draft.requests if "неустой" not in item.lower()]

    errors = check_amount_consistency(draft)
    assert errors
    assert any("996 000" in item or "неустой" in item.lower() for item in errors)


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
    assert "ТРЕБУЕТ РАСЧЁТА" in draft.price_of_claim
    assert any("дату начала просрочки" in note for note in draft.verification_notes)


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
