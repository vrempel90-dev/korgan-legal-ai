"""Регрессия фазы 3: жёсткий гейт перед выдачей документа.

Каждое правило проверяется дважды — на документе, который обязан пройти, и на
документе, который обязан быть заблокирован. Проверка только на нарушении
пропускает линтер, который блокирует всё подряд: он тоже «ловит» дефект, но
делает продукт неработоспособным.
"""

from __future__ import annotations

from datetime import date

import pytest

from korgan.article_lookup import source_hash
from korgan.claim_calculator import build_claim_calculation, try_calculator_authority
from korgan.claim_financials import extract_case_financials
from korgan.document_linter import (
    LintStatus,
    QA_WATERMARK_PREFIX,
    lint_claim_document,
)
from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.professional_claim_finalizer import apply_article_authority
from tests.test_phase1_calculator_authority import CASE_A_CONTEXT, CASE_A_EXPECTED

GK_URL = "https://adilet.zan.kz/rus/docs/K990000409_"
ARTICLE_439 = (
    "Покупатель обязан оплатить товар непосредственно до или после передачи ему продавцом товара."
)


def _trace(*articles: tuple[str, str]) -> dict:
    return {
        "traceability": [
            {
                "reference": f"статья {article} {code}",
                "code": code,
                "article": article,
                "part": "",
                "source_hash": source_hash(ARTICLE_439),
                "source_url": GK_URL,
                "edition_date": date.today().isoformat(),
                "field": "legal_basis",
            }
            for code, article in articles
        ]
    }


def _clean_draft(**overrides) -> ClaimDraft:
    """Документ, который обязан пройти линтер без единого замечания."""
    base = dict(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности по договору поставки",
        court="Специализированный межрайонный экономический суд города Алматы",
        # Номера проходят контрольную сумму ИИН/БИН РК: правило SG-04 отличает
        # реквизит стороны от правдоподобного числа именно по ней.
        claimant=["ТОО «Альфа», БИН 190440012341, г. Алматы, ул. Абая, 10"],
        defendant=["ТОО «Бета», БИН 200540067892, г. Алматы, ул. Толе би, 55"],
        price_of_claim="1 000 000 тенге",
        facts=["Товар поставлен 20.02.2026, оплата не произведена."],
        legal_basis=[
            "На основании статьи 439 ГК РК покупатель обязан оплатить товар непосредственно "
            "до или после передачи ему продавцом товара.",
        ],
        requests=[
            "Взыскать с ответчика в пользу истца основной долг в размере 1 000 000 тенге.",
            "Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины.",
        ],
        attachments=["Копия договора поставки № 14/2026 от 02.02.2026"],
        calculation=["Основной долг: 1 000 000 тенге."],
        verification_notes=[],
        source_urls=[GK_URL],
        citation_authority=_trace(("ГК РК", "439")),
    )
    base.update(overrides)
    return ClaimDraft(**base)


def _rules(result) -> set[str]:
    return {finding.rule for finding in result.findings}


# --------------------------------------------------------------------------
# Базовая линия
# --------------------------------------------------------------------------


def test_a_clean_document_passes() -> None:
    result = lint_claim_document(_clean_draft())

    assert result.status is LintStatus.PASS
    assert result.findings == []
    assert result.summary() == "PASS"


def test_result_is_structured() -> None:
    draft = _clean_draft(facts=["Внутренняя заметка: TODO уточнить дату у клиента."])

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    payload = result.as_dict()
    assert payload["status"] == "BLOCKED"
    for finding in payload["findings"]:
        assert set(finding) == {"rule", "location", "message", "suggested_fix"}
        assert all(finding[key] for key in finding)


# --------------------------------------------------------------------------
# Правило 1. Служебные маркеры
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "line"),
    [
        ("verification_notes", "Согласно verification_notes требуется проверка."),
        ("qa_json", 'Результат: {"critical_errors": []}'),
        ("internal_todo", "TODO: уточнить дату договора."),
        ("debug_payload", "DEBUG: сработал резервный путь."),
        ("structured_reasoning", "ШАГ 1: определить применимую норму."),
        ("internal_quality_note", "KORGAN QUALITY: оценка 9.5."),
        ("repair_marker", "Статус документа: NEEDS_VERIFICATION."),
        ("technical_placeholder_name", "Поле price_of_claim заполняется расчётом."),
    ],
)
def test_service_marker_in_the_body_blocks_release(rule, line) -> None:
    result = lint_claim_document(_clean_draft(facts=[line]))

    assert result.status is LintStatus.BLOCKED
    assert rule in _rules(result)


def test_lawyer_notes_outside_the_body_do_not_block() -> None:
    """Внутренний канал QA — не судебный текст."""
    draft = _clean_draft(
        verification_notes=[
            "Детерминированный расчёт: penalty: не установлен срок оплаты.",
            "Ссылка на норму: статья 180 ГК РК не выпущена в документ.",
        ]
    )

    assert lint_claim_document(draft).status is LintStatus.PASS


def test_qa_watermark_in_the_header_is_allowed() -> None:
    draft = _clean_draft(title=f"{QA_WATERMARK_PREFIX}: документ проверен")

    assert lint_claim_document(draft).status is LintStatus.PASS


# --------------------------------------------------------------------------
# Правило 2. Незаполненные числовые поля
# --------------------------------------------------------------------------


def test_unresolved_placeholder_blocks_release() -> None:
    draft = _clean_draft(
        requests=["Взыскать с ответчика основной долг в размере {{principal_amount}}."]
    )

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "unresolved_placeholder" in _rules(result)


def test_calculation_marker_blocks_release() -> None:
    draft = _clean_draft(price_of_claim="[ТРЕБУЕТ РАСЧЁТА]")

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "unresolved_calculation_marker" in _rules(result)


def test_english_placeholder_token_blocks_release() -> None:
    draft = _clean_draft(facts=["Сумма долга: <amount>."])

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "technical_placeholder_token" in _rules(result)


def test_insufficient_data_is_its_own_release_condition() -> None:
    """Дефицит данных блокирует выпуск, а не маскируется текстом."""
    context = CASE_A_CONTEXT.replace("Срок оплаты по договору — до 10.03.2026 включительно.\n", "")
    outcome = build_claim_calculation(
        context, extract_case_financials(context), filing_date=date(2026, 9, 1), penalty_claimed=True
    )
    draft = _clean_draft(calculation_result=outcome.calculation.as_dict())

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "insufficient_calculation_data" in _rules(result)
    blocked = [item for item in result.findings if item.rule == "insufficient_calculation_data"]
    assert any("срок оплаты" in item.message for item in blocked)


# --------------------------------------------------------------------------
# Правило 3. Непроверенные статьи
# --------------------------------------------------------------------------


def test_article_without_verified_lookup_blocks_release() -> None:
    draft = _clean_draft(
        legal_basis=["В соответствии со статьёй 180 ГК РК срок исковой давности прерывается."]
    )

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "unverified_article" in _rules(result)


def test_article_with_verified_lookup_passes() -> None:
    assert lint_claim_document(_clean_draft()).status is LintStatus.PASS


def test_article_outside_legal_basis_is_checked_too() -> None:
    draft = _clean_draft(
        facts=["Ответчик признал долг, что по статье 180 ГК РК прерывает срок исковой давности."]
    )

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "unverified_article" in _rules(result)


def test_empty_traceability_blocks_any_printed_article() -> None:
    """Проверка ссылок не выполнялась — печатать номера нельзя."""
    draft = _clean_draft(citation_authority={})

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "unverified_article" in _rules(result)


# --------------------------------------------------------------------------
# Правило 4. Структурные аномалии
# --------------------------------------------------------------------------


def test_motion_to_demand_the_claimants_own_attachment_blocks_release() -> None:
    draft = _clean_draft(
        attachments=["Копия договора поставки № 14/2026 от 02.02.2026"],
        motions=["Истребовать у истца договор поставки № 14/2026 от 02.02.2026."],
    )

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "motion_requests_claimant_own_attachment" in _rules(result)


def test_motion_to_demand_evidence_from_the_defendant_is_fine() -> None:
    draft = _clean_draft(
        attachments=["Копия договора поставки № 14/2026 от 02.02.2026"],
        motions=["Истребовать у ответчика акты сверки взаиморасчётов за 2026 год."],
    )

    assert lint_claim_document(draft).status is LintStatus.PASS


def test_motion_about_a_different_document_is_fine() -> None:
    draft = _clean_draft(
        attachments=["Копия договора поставки № 14/2026 от 02.02.2026"],
        motions=["Истребовать у истца выписку банка о зачислении платежей за март 2026 года."],
    )

    assert lint_claim_document(draft).status is LintStatus.PASS


# --------------------------------------------------------------------------
# Правило 4. Суммы против структурированного расчёта
# --------------------------------------------------------------------------


@pytest.fixture()
def calculated_draft() -> ClaimDraft:
    """Иск, полностью собранный детерминированным расчётом по CASE A."""
    draft = _clean_draft(
        price_of_claim="",
        requests=[
            "Взыскать с ответчика основной долг в размере 8 750 000 тенге.",
            "Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины.",
        ],
        citation_authority=_trace(("ГК РК", "439")),
    )
    outcome = try_calculator_authority(
        CASE_A_CONTEXT, draft, filing_date=date(2026, 9, 1), penalty_claimed=True
    )
    assert outcome is not None
    draft.calculation_result = outcome.calculation.as_dict()
    # Строку госпошлины пишет детерминированный расчёт, и она называет статью
    # 665 НК РК. Проверка ссылок подтверждает её по справочнику ставок — тому
    # самому, из которого взята ставка, — и вносит в трассировку.
    apply_article_authority(draft)
    return draft


def test_a_fully_calculated_claim_passes(calculated_draft) -> None:
    result = lint_claim_document(calculated_draft)

    assert result.status is LintStatus.PASS, result.summary()


def test_claim_price_that_disagrees_with_the_calculation_blocks(calculated_draft) -> None:
    calculated_draft.price_of_claim = "7 000 000 тенге"

    result = lint_claim_document(calculated_draft)

    assert result.status is LintStatus.BLOCKED
    assert "claim_price_mismatch" in _rules(result)


def test_prayer_amount_that_disagrees_with_the_calculation_blocks(calculated_draft) -> None:
    calculated_draft.requests[0] = "Взыскать с ответчика основной долг в размере 6 000 000 тенге."

    result = lint_claim_document(calculated_draft)

    assert result.status is LintStatus.BLOCKED
    assert _rules(result) & {"prayer_total_mismatch", "prayer_amount_missing"}


def test_prayer_without_the_total_amount_blocks(calculated_draft) -> None:
    calculated_draft.requests = [
        request
        for request in calculated_draft.requests
        if "Общая сумма ко взысканию" not in request
    ]

    result = lint_claim_document(calculated_draft)

    assert result.status is LintStatus.BLOCKED
    assert "prayer_without_total_amount" in _rules(result)


def test_the_calculated_total_is_stated_in_the_prayer(calculated_draft) -> None:
    prayer = "\n".join(calculated_draft.requests)

    assert "Общая сумма ко взысканию" in prayer
    assert "8 224 808 тенге" in prayer


def test_the_total_summary_does_not_double_the_claim_price(calculated_draft) -> None:
    """Итоговая строка — сводка, а не ещё одно требование."""
    from korgan.claim_money_ledger import build_claim_money_ledger

    ledger = build_claim_money_ledger(list(calculated_draft.requests))

    assert ledger.total == CASE_A_EXPECTED["claim_price"]


# --------------------------------------------------------------------------
# Гейт не маскирует нарушение
# --------------------------------------------------------------------------


def test_blocked_result_names_every_violation() -> None:
    draft = _clean_draft(
        facts=["TODO: уточнить дату."],
        legal_basis=["В соответствии со статьёй 180 ГК РК срок прерывается."],
        price_of_claim="[ТРЕБУЕТ РАСЧЁТА]",
    )

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert {"internal_todo", "unverified_article", "unresolved_calculation_marker"} <= _rules(result)


def test_every_finding_offers_a_concrete_fix() -> None:
    draft = _clean_draft(facts=["TODO: уточнить дату."])

    for finding in lint_claim_document(draft).findings:
        assert len(finding.suggested_fix) > 20
        assert finding.location


# --------------------------------------------------------------------------
# Гейт выпуска
# --------------------------------------------------------------------------


def test_release_policy_blocks_a_linted_violation() -> None:
    """Нарушение линтера не выдаётся даже под штампом предварительного документа."""
    from korgan.miniapp_professional_release import ReleaseBlocked, apply_release_policy

    result = {
        "filing_ready": False,
        "release_status": "preliminary",
        "quality_issues": [],
        "verification_notes": [],
        "lint": {
            "status": "BLOCKED",
            "findings": [
                {
                    "rule": "unverified_article",
                    "location": "legal_basis[0]",
                    "message": "статья 180 ГК РК напечатана без подтверждённой записи корпуса",
                    "suggested_fix": "снять номер статьи",
                }
            ],
        },
    }

    with pytest.raises(ReleaseBlocked):
        apply_release_policy(result, case_id="case-1")


def test_release_policy_passes_a_clean_lint() -> None:
    from korgan.miniapp_professional_release import apply_release_policy

    result = {
        "filing_ready": True,
        "release_status": "verified",
        "quality_issues": [],
        "verification_notes": [],
        "lint": {"status": "PASS", "findings": []},
    }

    assert apply_release_policy(result, case_id="case-1") is result


def test_release_policy_ignores_documents_without_a_lint_report() -> None:
    """Через ту же политику проходят договор, отзыв и претензия."""
    from korgan.miniapp_professional_release import apply_release_policy

    result = {
        "filing_ready": True,
        "release_status": "verified",
        "quality_issues": [],
        "verification_notes": [],
    }

    assert apply_release_policy(result, case_id="case-1") is result


def test_blocked_release_message_carries_no_internal_protocol() -> None:
    """Клиент читает причину, а не разметку внутренних проверок."""
    from korgan.miniapp_professional_release import ReleaseBlocked

    blocked = ReleaseBlocked(["служебный фрагмент «TODO» (facts[0])"])

    assert "TODO" not in blocked.detail or "Причина" in blocked.detail
    assert "FILING_ACTION" not in blocked.detail
