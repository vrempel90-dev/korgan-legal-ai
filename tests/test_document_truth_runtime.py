from __future__ import annotations

from korgan.document_truth_runtime import (
    _is_russian_adilet,
    contract_truth_findings,
    general_truth_findings,
    live_citation_findings,
)
from korgan.provision_check import verified_claim_line


def _gpk_166(source: str = "https://adilet.zan.kz/rus/docs/K1500000377") -> str:
    return verified_claim_line(
        "Отзыв на иск подается в порядке, установленном статьей 166 ГПК РК.",
        "статья 166 ГПК РК",
        (
            "Ответчик представляет в суд отзыв на исковое заявление с приложением "
            "документов, подтверждающих возражения относительно иска."
        ),
        source,
    )


def test_live_citation_accepts_same_request_verified_core_act() -> None:
    findings = live_citation_findings(
        "В соответствии со статьей 166 ГПК РК ответчик представляет отзыв на иск.",
        [_gpk_166()],
    )
    assert findings == []


def test_live_citation_rejects_correct_article_number_bound_to_wrong_core_act() -> None:
    findings = live_citation_findings(
        "В соответствии со статьей 166 ГПК РК ответчик представляет отзыв на иск.",
        [_gpk_166("https://adilet.zan.kz/rus/docs/K940001000_")],
    )
    assert findings
    assert "live source-bound VERIFIED" in findings[0]


def test_live_citation_rejects_article_absent_from_current_request_verified() -> None:
    # Even if the local corpus happens to contain Article 166, filing-ready
    # release requires a live source-bound provision for this document.
    findings = live_citation_findings(
        "Согласно статье 166 ГПК РК ответчик представляет отзыв.",
        [],
    )
    assert findings


def test_adilet_legislation_source_must_be_russian_official_page() -> None:
    assert _is_russian_adilet("https://adilet.zan.kz/rus/docs/K1500000377") is True
    assert _is_russian_adilet("https://adilet.zan.kz/eng/docs/K1500000377") is False
    assert _is_russian_adilet("https://example.com/rus/docs/K1500000377") is False


def test_contract_blocks_invented_percentage_and_duration() -> None:
    findings = contract_truth_findings(
        [
            "За просрочку начисляется пеня 0,1% за каждый день.",
            "Оплата производится в течение 10 рабочих дней.",
        ],
        case_context="Стороны согласовали оказание услуг. Размер пени и срок оплаты не согласованы.",
        verified_claims=[],
    )
    assert any("0,1%" in item for item in findings)
    assert any("10 рабочих дней" in item for item in findings)


def test_contract_allows_numeric_terms_explicitly_given_by_user() -> None:
    context = (
        "Стороны согласовали: пеня 0,1% за каждый день просрочки. "
        "Оплата производится в течение 10 рабочих дней."
    )
    findings = contract_truth_findings(
        [
            "За просрочку начисляется пеня 0,1% за каждый день.",
            "Оплата производится в течение 10 рабочих дней.",
        ],
        case_context=context,
        verified_claims=[],
    )
    assert not any("0,1%" in item for item in findings)
    assert not any("10 рабочих дней" in item for item in findings)


def test_contract_blocks_invented_money_and_date() -> None:
    findings = contract_truth_findings(
        [
            "Цена договора составляет 750 000 тенге.",
            "Договор заключен 03.09.2026.",
        ],
        case_context="Пользователь просит подготовить договор оказания услуг; цена и дата не сообщены.",
        verified_claims=[],
    )
    assert any("750 000" in item for item in findings)
    assert any("03.09.2026" in item for item in findings)


def test_general_guard_blocks_invented_dispatch_date_outside_fact_array() -> None:
    findings = general_truth_findings(
        ["Поскольку претензия была направлена 15.08.2026, нарушение не устранено."],
        case_context="Претензия ранее не направлялась; дата направления отсутствует.",
        verified_claims=[],
    )
    assert any("15.08.2026" in item or "направления претензии" in item for item in findings)


def test_general_guard_allows_date_when_it_is_in_user_materials() -> None:
    context = "Досудебная претензия направлена ответчику 15.08.2026."
    findings = general_truth_findings(
        ["Досудебная претензия направлена ответчику 15.08.2026."],
        case_context=context,
        verified_claims=[],
    )
    assert findings == []


def test_general_guard_blocks_invented_completed_payment() -> None:
    findings = general_truth_findings(
        ["Истец перечислил ответчику 500 000 тенге 15.08.2026."],
        case_context="Сумма и дата платежа в материалах отсутствуют.",
        verified_claims=[],
    )
    assert any("500 000" in item or "факт оплаты" in item for item in findings)


def test_general_guard_does_not_treat_future_payment_instruction_as_fact() -> None:
    findings = general_truth_findings(
        ["Оплатить государственную пошлину до подачи иска."],
        case_context="Размер и факт оплаты государственной пошлины не сообщены.",
        verified_claims=[],
    )
    assert findings == []


def test_general_guard_does_not_treat_filing_attachment_name_as_existing_fact() -> None:
    findings = general_truth_findings(
        ["Квитанция об уплате государственной пошлины"],
        case_context="Квитанция пока не приложена.",
        verified_claims=[],
    )
    assert findings == []


def test_general_guard_does_not_treat_conditional_pretrial_deadline_as_past_dispatch() -> None:
    findings = general_truth_findings(
        ["Исполнить требования в течение 10 календарных дней с даты получения настоящей претензии."],
        case_context="Составляется первая досудебная претензия.",
        verified_claims=[],
    )
    assert findings == []
