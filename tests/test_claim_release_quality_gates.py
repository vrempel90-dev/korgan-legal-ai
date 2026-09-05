"""Готовый иск не должен противоречить сам себе и терять правовую опору.

Что было видно юристу в боевом документе: суд назван уверенно и одновременно
помечен «уточнить наименование/подсудность»; госпошлина рассчитана и рядом
помечена как требующая уточнения; в разделе «Ходатайства» стояли внутренние
действия проверки; правовое обоснование опиралось только на процессуальные
статьи, хотя норма о существе долга была подтверждена исследованием.
"""

from __future__ import annotations

import io

from docx import Document

from korgan.claim_docx import build_claim_docx
from korgan.claim_release_consistency import (
    contradictory_release_issues,
    court_is_resolved,
    enforce_release_consistency,
    state_duty_is_resolved,
)
from korgan.claim_state_duty import decide_state_duty
from korgan.claim_substantive_basis import (
    enforce_substantive_basis,
    substantive_basis_issues,
    substantive_basis_lines,
)
from korgan.legal_calc import NEEDS_CALCULATION_MARKER
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

CASE = """Истец: ТОО «Альфа Трейд», БИН 123456789012, г. Алматы, ул. Абая, 10.
Ответчик: ТОО «Бета Снаб», БИН 210987654321, г. Алматы, ул. Толе би, 20.
10.01.2026 заключён договор поставки №12.
15.01.2026 поставлен товар на 4 500 000 тенге.
Поставка подтверждена договором, товарной накладной и актом приёма-передачи.
Товар принят без замечаний. Срок оплаты — 15 календарных дней после поставки.
Оплата не произведена. 15.02.2026 направлена претензия, 17.02.2026 получена
ответчиком. Ответа нет, долг не погашен."""

SUBSTANTIVE_LINE = (
    "Покупатель обязан оплатить принятый товар в срок, установленный договором. "
    "Правовое основание: статья 439 ГК РК (Особенная часть)."
)
PROCEDURAL_LINE = (
    "Иск предъявляется по месту нахождения ответчика. Правовое основание: статья 29 ГПК РК."
)


def _research(verified: list[str] | None = None) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(verified or []),
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
        notes=[],
    )


def _draft(**overrides: object) -> ClaimDraft:
    values: dict[str, object] = {
        "status": VerificationStatus.VERIFIED,
        "title": "ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности по договору поставки",
        "court": "Специализированный межрайонный экономический суд города Алматы",
        "claimant": ["ТОО «Альфа Трейд», БИН 123456789012, г. Алматы, ул. Абая, 10"],
        "defendant": ["ТОО «Бета Снаб», БИН 210987654321, г. Алматы, ул. Толе би, 20"],
        "price_of_claim": "4 500 000 тенге",
        "facts": ["10.01.2026 между сторонами заключён договор поставки №12."],
        "legal_basis": [SUBSTANTIVE_LINE],
        "requests": [
            "Взыскать с ответчика в пользу истца основной долг в размере 4 500 000 тенге.",
        ],
        "attachments": ["Договор поставки №12 от 10.01.2026"],
        "verification_notes": [],
        "source_urls": [],
        "state_duty": "135 000 тенге (3% от цены иска; максимум 20 000 МРП)",
    }
    values.update(overrides)
    return ClaimDraft(**values)  # type: ignore[arg-type]


# --- госпошлина ------------------------------------------------------------

def test_state_duty_is_calculated_deterministically_for_the_regression_case() -> None:
    draft = _draft(state_duty="")
    decision = decide_state_duty(CASE, _research([SUBSTANTIVE_LINE]), draft)
    assert decision.needs_review is False
    assert decision.amount == 135_000
    assert "135 000" in decision.line


def test_missing_input_fails_closed_with_a_named_reason() -> None:
    """Недостающие данные дают именованную причину, а не удобную цифру."""
    draft = _draft(
        requests=["Взыскать с ответчика убытки."],
        state_duty="",
        price_of_claim="",
    )
    decision = decide_state_duty("Спор между сторонами.", _research(), draft)
    assert decision.needs_review is True
    assert decision.line == NEEDS_CALCULATION_MARKER
    assert decision.note.strip()


def test_calculated_duty_removes_the_task_to_clarify_its_amount() -> None:
    draft = _draft(
        verification_notes=[
            "Государственная пошлина требует проверки: цена иска не определена однозначно.",
            "FILING_ACTION: приложить документ об уплате государственной пошлины.",
        ],
    )
    assert state_duty_is_resolved(draft) is True
    enforce_release_consistency(draft, CASE)
    assert not any("требует проверки" in note for note in draft.verification_notes)
    # Уплата пошлины остаётся: это действие истца, а не сомнение в размере.
    assert any("уплате государственной пошлины" in note for note in draft.verification_notes)
    assert contradictory_release_issues(draft) == []


def test_placeholder_duty_keeps_its_task() -> None:
    draft = _draft(
        state_duty=NEEDS_CALCULATION_MARKER,
        verification_notes=["Государственная пошлина требует проверки: цена иска не определена."],
    )
    assert state_duty_is_resolved(draft) is False
    enforce_release_consistency(draft, CASE)
    assert any("требует проверки" in note for note in draft.verification_notes)


# --- суд -------------------------------------------------------------------

def test_named_court_and_a_task_to_clarify_it_cannot_coexist() -> None:
    draft = _draft(
        verification_notes=[
            "FILING_ACTION: подтвердить точное официальное наименование экономического "
            "суда по месту надлежащей подсудности.",
        ],
    )
    assert court_is_resolved(draft) is True
    assert contradictory_release_issues(draft)
    enforce_release_consistency(draft, CASE)
    assert contradictory_release_issues(draft) == []
    assert not any("наименование" in note and "суда" in note for note in draft.verification_notes)


def test_unresolved_court_keeps_its_task_and_its_marker() -> None:
    draft = _draft(
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: специализированный межрайонный экономический суд]",
        verification_notes=[
            "FILING_ACTION: подтвердить точное официальное наименование экономического суда "
            "по месту надлежащей подсудности.",
        ],
    )
    assert court_is_resolved(draft) is False
    enforce_release_consistency(draft, CASE)
    assert any("суда" in note for note in draft.verification_notes)
    assert contradictory_release_issues(draft) == []


# --- правовое обоснование --------------------------------------------------

def test_verified_substantive_law_reaches_the_final_docx() -> None:
    draft = _draft()
    research = _research([SUBSTANTIVE_LINE])
    assert enforce_substantive_basis(research, draft) == []
    assert substantive_basis_lines(draft)

    document = Document(io.BytesIO(build_claim_docx(draft)))
    body = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "статья 439 ГК РК" in body.lower() or "статья 439 гк рк" in body.lower()


def test_procedural_article_cannot_replace_the_substantive_basis() -> None:
    draft = _draft(legal_basis=[PROCEDURAL_LINE])
    research = _research([SUBSTANTIVE_LINE])
    issues = substantive_basis_issues(research, draft)
    assert issues, "потеря материальной нормы обязана быть названа"
    assert "статья 439" in issues[0]

    enforce_substantive_basis(research, draft)
    assert draft.status is VerificationStatus.NEEDS_VERIFICATION


def test_claim_without_any_verified_substantive_law_is_marked_too() -> None:
    draft = _draft(legal_basis=[PROCEDURAL_LINE])
    issues = substantive_basis_issues(_research(), draft)
    assert issues and "процессуальные" in issues[0]


def test_prayer_without_substantive_relief_needs_no_substantive_basis() -> None:
    """Иск, где остались только расходы, не требует материальной опоры."""
    draft = _draft(
        requests=["Взыскать с ответчика расходы по уплате государственной пошлины."],
        legal_basis=[PROCEDURAL_LINE],
    )
    assert substantive_basis_issues(_research([SUBSTANTIVE_LINE]), draft) == []


# --- просительная часть и служебный текст ----------------------------------

def test_unsupported_representative_costs_leave_the_prayer() -> None:
    draft = _draft(
        requests=[
            "Взыскать с ответчика в пользу истца основной долг в размере 4 500 000 тенге.",
            "Взыскать расходы на оплату услуг представителя в размере 300 000 тенге.",
        ],
    )
    enforce_release_consistency(draft, CASE)
    assert len(draft.requests) == 1
    assert "представител" not in draft.requests[0].lower()


def test_documented_representative_costs_stay_in_the_prayer() -> None:
    draft = _draft(
        requests=[
            "Взыскать с ответчика в пользу истца основной долг в размере 4 500 000 тенге.",
            "Взыскать расходы на оплату услуг представителя в размере 300 000 тенге.",
        ],
        attachments=[
            "Договор поставки №12 от 10.01.2026",
            "Договор на оказание юридических услуг от 20.02.2026",
        ],
    )
    enforce_release_consistency(draft, CASE)
    assert len(draft.requests) == 2


def test_internal_verification_actions_are_not_court_motions() -> None:
    draft = _draft(
        motions=[
            "Ходатайство об уточнении наименования суда",
            "Ходатайство об истребовании документа об оплате государственной пошлины",
            "Ходатайство об обеспечении иска",
        ],
    )
    enforce_release_consistency(draft, CASE)
    assert draft.motions == ["Ходатайство об обеспечении иска"]
    assert contradictory_release_issues(draft) == []


def test_duplicated_pretrial_narrative_is_collapsed() -> None:
    line = "15.02.2026 истцом направлена претензия, полученная ответчиком 17.02.2026."
    draft = _draft(facts=[line, line, "Оплата не произведена."])
    enforce_release_consistency(draft, CASE)
    assert draft.facts == [line, "Оплата не произведена."]
    assert contradictory_release_issues(draft) == []


def test_internal_pipeline_vocabulary_in_the_body_is_reported() -> None:
    draft = _draft(facts=["FILING_ACTION: приложить накладную", "Товар принят без замечаний."])
    issues = contradictory_release_issues(draft)
    assert any("служебный текст" in issue for issue in issues)


def test_clean_claim_reports_no_contradictions_at_all() -> None:
    draft = _draft()
    assert contradictory_release_issues(draft) == []
