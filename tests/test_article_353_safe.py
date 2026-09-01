from datetime import date

from korgan.late_interest_hotfix import (
    ProductionOpenAILegalService as Article353Service,
    _apply_verified_article_353,
    _extract_due_date,
)
from korgan.legal_calc import base_rate_on, calc_late_payment_penalty
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.state_duty_final_hotfix import ProductionOpenAILegalService as PreviousFinalService


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании долга и процентов",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: суд]",
        claimant=["Истец Тестов, ИИН 900000000001"],
        defendant=["Ответчик Примеров"],
        price_of_claim="800 000 тенге плюс проценты",
        facts=[],
        legal_basis=["Модель написала проценты по денежному обязательству."],
        requests=[
            "Взыскать основной долг 800 000 тенге.",
            "Взыскать проценты по денежному обязательству за период просрочки.",
        ],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def _verified_353() -> LegalResearch:
    url = "https://adilet.zan.kz/rus/docs/K940001000_/compare"
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[f"Статья 353 применима к просрочке [основание: 353; источник: {url}]"],
        unverified_claims=[],
        source_urls=[url],
        notes=[],
    )


def test_final_runtime_keeps_all_previous_hotfixes() -> None:
    assert issubclass(Article353Service, PreviousFinalService)


def test_verified_nb_rates_include_july_2026_change() -> None:
    assert base_rate_on(date(2026, 6, 8)) == 17.0
    assert base_rate_on(date(2026, 7, 27)) == 16.75
    assert base_rate_on(date(2026, 9, 4)) is None


def test_penalty_uses_filing_date_rate_choice() -> None:
    result = calc_late_payment_penalty(
        800_000,
        date(2026, 4, 11),
        date(2026, 8, 16),
        rate_date=date(2026, 8, 16),
    )
    assert result is not None
    assert result.days == 128
    assert result.rate_percent == 16.75
    assert result.amount == 46_992


def test_due_date_is_read_from_receipt_wording() -> None:
    text = "Ответчик обязался вернуть сумму в полном объёме не позднее 10 апреля 2026 года."
    assert _extract_due_date(text) == date(2026, 4, 10)


def test_model_cannot_add_unrequested_penalty() -> None:
    draft = _draft()
    context = "ИИН 900000000001. Проценты договором не предусмотрены. Неустойка договором не предусмотрена."
    _apply_verified_article_353(context, _verified_353(), draft, filing_date=date(2026, 8, 16))
    # The model-written penalty must disappear.  The deterministic state-duty
    # reimbursement request is a separate, legitimate request and is expected.
    assert len(draft.requests) == 2
    assert any("основной долг 800 000" in item for item in draft.requests)
    assert sum("государственной пошлины" in item.lower() for item in draft.requests) == 1
    assert not any("353" in item or "процент" in item.lower() for item in draft.requests)
    assert draft.price_of_claim == "800 000 тенге"
    assert draft.late_interest == ""


def test_explicit_article_353_claim_is_calculated_and_added_to_claim_price() -> None:
    draft = _draft()
    context = (
        "Истец ИИН 900000000001. Ответчик обязался вернуть сумму не позднее 10 апреля 2026 года. "
        "Прошу взыскать неустойку по статье 353 ГК РК за просрочку."
    )
    _apply_verified_article_353(context, _verified_353(), draft, filing_date=date(2026, 8, 16))
    assert "46 992 тенге" in draft.late_interest
    assert "846 992 тенге" in draft.price_of_claim
    assert "8 470 тенге" in draft.state_duty
    assert sum("353" in item for item in draft.requests) == 1


def test_partial_payment_blocks_the_single_formula_penalty() -> None:
    """Долг, погашенный частично, нельзя считать одной формулой за весь период.

    Неустойка после платежа начисляется на остаток. Прежний расчёт брал одну
    сумму и все дни периода, поэтому платёж середины периода в него не попадал
    и требование выходило завышенным — с виду обычное правдоподобное число,
    которое ответчик пересчитывает первым. До подтверждения дат и сумм платежей
    сумма не заявляется вовсе.
    """
    draft = _draft()
    context = (
        "Истец ИИН 900000000001. Ответчик обязался вернуть сумму не позднее 10 апреля 2026 года. "
        "01.06.2026 ответчик частично оплатил задолженность в размере 300 000 тенге. "
        "Прошу взыскать неустойку по статье 353 ГК РК за просрочку."
    )
    _apply_verified_article_353(context, _verified_353(), draft, filing_date=date(2026, 8, 16))

    assert "46 992" not in draft.late_interest
    assert not any("46 992" in item for item in draft.requests)
    assert any("частичн" in note.lower() for note in draft.verification_notes)


def test_a_case_without_payments_still_gets_its_calculated_penalty() -> None:
    """Проверка на частичную оплату не должна глушить обычный расчёт."""
    draft = _draft()
    context = (
        "Истец ИИН 900000000001. Ответчик обязался вернуть сумму не позднее 10 апреля 2026 года. "
        "Оплата не поступила. Прошу взыскать неустойку по статье 353 ГК РК за просрочку."
    )
    _apply_verified_article_353(context, _verified_353(), draft, filing_date=date(2026, 8, 16))

    assert "46 992 тенге" in draft.late_interest
