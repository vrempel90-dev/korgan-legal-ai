"""Детерминированные поля иска: госпошлина считается кодом, суд не угадывается."""

import io

from docx import Document

from korgan.claim_docx import build_claim_docx
from korgan.legal_calc import NEEDS_CALCULATION_MARKER
from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.production_legal import (
    COURT_NOTE,
    COURT_PLACEHOLDER,
    STATE_DUTY_NOTE,
    _apply_state_duty,
    _enforce_court_verification,
)

DELO_2_CONTEXT = (
    "Файл: KORGAN_TEST_DELO_2.docx\n"
    "Стороны: Займодавец (истец): Ахметов Руслан Маратович; Заёмщик (ответчик): Садыков Тимур Ерланович\n"
    "Идентификаторы: Ахметов Руслан Маратович, ИИН 000000000101; Садыков Тимур Ерланович, ИИН 000000000202\n"
    "Адреса: не установлено\n"
    "Суммы: 2 400 000 тенге — сумма займа\n"
)


def _header_text(payload: bytes) -> str:
    """Шапка иска, а не первый параграф: перед ней печатается KORGAN QA STATUS."""
    for paragraph in Document(io.BytesIO(payload)).paragraphs:
        if "Госпошлина:" in paragraph.text:
            return paragraph.text
    raise AssertionError("В документе нет шапки со строкой госпошлины")


def _draft(**overrides) -> ClaimDraft:
    base = dict(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании суммы долга по договору займа",
        court=COURT_PLACEHOLDER,
        claimant=["Ахметов Руслан Маратович, ИИН 000000000101"],
        defendant=["Садыков Тимур Ерланович, ИИН 000000000202"],
        price_of_claim="2 400 000 (два миллиона четыреста тысяч) тенге",
        facts=["Договор займа от 15.02.2026 на 2 400 000 тенге"],
        legal_basis=["Статья 715 ГК РК"],
        requests=["Взыскать основной долг"],
        attachments=["Копия договора займа от 15.02.2026"],
        verification_notes=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
    )
    base.update(overrides)
    return ClaimDraft(**base)


def test_state_duty_is_calculated_for_delo_2() -> None:
    draft = _draft()

    _apply_state_duty(DELO_2_CONTEXT, draft)

    assert draft.state_duty.startswith("24 000 тенге")
    assert STATE_DUTY_NOTE not in draft.verification_notes


def test_unknown_price_falls_back_to_calculation_marker() -> None:
    draft = _draft(price_of_claim="[ТРЕБУЕТ УТОЧНЕНИЯ: цена иска]")

    _apply_state_duty(DELO_2_CONTEXT, draft)

    assert draft.state_duty == NEEDS_CALCULATION_MARKER
    assert STATE_DUTY_NOTE in draft.verification_notes


def test_guessed_court_is_replaced_with_verification_marker() -> None:
    """Адрес ответчика неизвестен — конкретный суд угадать нельзя."""
    draft = _draft(court="Медеуский районный суд города Алматы")

    _enforce_court_verification(DELO_2_CONTEXT, draft)

    assert draft.court == COURT_PLACEHOLDER
    assert COURT_NOTE in draft.verification_notes


def test_court_named_in_case_materials_is_kept() -> None:
    context = DELO_2_CONTEXT + "Важные факты: спор подсуден Медеускому районному суду города Алматы\n"
    draft = _draft(court="Медеуский районный суд города Алматы")

    _enforce_court_verification(context, draft)

    assert draft.court == "Медеуский районный суд города Алматы"
    assert COURT_NOTE not in draft.verification_notes


def test_existing_placeholder_is_untouched() -> None:
    draft = _draft()

    _enforce_court_verification(DELO_2_CONTEXT, draft)

    assert draft.court == COURT_PLACEHOLDER
    assert draft.verification_notes == []


def test_docx_header_always_shows_state_duty() -> None:
    draft = _draft()
    _apply_state_duty(DELO_2_CONTEXT, draft)

    header = _header_text(build_claim_docx(draft))

    assert "Госпошлина: 24 000 тенге" in header
    assert header.count("Госпошлина:") == 1


def test_docx_header_shows_marker_when_duty_is_unknown() -> None:
    header = _header_text(build_claim_docx(_draft()))

    assert "[ДАННЫЕ: размер государственной пошлины]" in header


def test_stale_duty_notes_are_dropped_after_calculation() -> None:
    draft = _draft(
        verification_notes=[
            "Размер государственной пошлины не подтверждён официальным источником — NEEDS_VERIFICATION.",
            "Не указан размер государственной пошлины и её расчёт.",
            "Не указаны адреса сторон.",
        ]
    )

    _apply_state_duty(DELO_2_CONTEXT, draft)

    assert draft.state_duty.startswith("24 000 тенге")
    assert draft.verification_notes == ["Не указаны адреса сторон."]


def test_duty_notes_are_kept_when_calculation_is_impossible() -> None:
    draft = _draft(
        price_of_claim="[ТРЕБУЕТ УТОЧНЕНИЯ: цена иска]",
        verification_notes=["Размер государственной пошлины не подтверждён — NEEDS_VERIFICATION."],
    )

    _apply_state_duty(DELO_2_CONTEXT, draft)

    assert draft.state_duty == NEEDS_CALCULATION_MARKER
    assert len(draft.verification_notes) == 2
    assert STATE_DUTY_NOTE in draft.verification_notes
