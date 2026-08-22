"""Блок 5: формальная проверка иска по требованиям ГПК РК к форме."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from korgan.legal.formal_check import (  # noqa: E402
    FILING_BLOCKED_MARKER,
    ClaimForm,
    Severity,
    check_claim_form,
)


def _form(**overrides) -> ClaimForm:
    base = dict(
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании долга по расписке",
        court="Медеуский районный суд города Алматы",
        claimant=["Ахметов Руслан Маратович, ИИН 000000000101"],
        defendant=["Садыков Тимур Ерланович, ИИН 000000000202"],
        price_of_claim="800 000 тенге",
        price_breakdown="Основной долг 800 000 тенге. Итого цена иска: 800 000 тенге",
        facts=["10.01.2026 ответчик получил в долг 800 000 тенге, что подтверждается распиской"],
        requests=["Взыскать основной долг в размере 800 000 тенге"],
        attachments=["Копия расписки от 10.01.2026"],
        pretrial_required=False,
        pretrial_confirmed=False,
    )
    base.update(overrides)
    return ClaimForm(**base)


def _codes(form: ClaimForm) -> set[str]:
    return {defect.code for defect in check_claim_form(form).defects}


def test_complete_claim_has_no_defects() -> None:
    result = check_claim_form(_form())

    assert result.defects == ()
    assert result.is_filing_ready
    assert result.marker() == ""


# --- суд ---------------------------------------------------------------------


def test_placeholder_court_is_critical() -> None:
    result = check_claim_form(_form(court="[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда]"))

    assert "court_missing" in {d.code for d in result.critical}
    assert not result.is_filing_ready


def test_empty_court_is_critical() -> None:
    assert "court_missing" in _codes(_form(court=""))


def test_vague_court_is_a_warning() -> None:
    result = check_claim_form(_form(court="Суд по месту жительства ответчика"))

    assert [d.code for d in result.warnings] == ["court_unclear"]
    assert result.is_filing_ready


# --- стороны -----------------------------------------------------------------


def test_claimant_without_identifier_is_critical() -> None:
    result = check_claim_form(_form(claimant=["Ахметов Руслан Маратович"]))

    assert "identifier_missing_истца" in {d.code for d in result.critical}


def test_defendant_without_identifier_is_only_a_warning() -> None:
    """ИИН ответчика истцу может быть неизвестен — это не блокирует подачу."""
    result = check_claim_form(_form(defendant=["Садыков Тимур Ерланович"]))

    assert "identifier_missing_ответчика" in {d.code for d in result.warnings}
    assert result.is_filing_ready


def test_missing_party_is_critical() -> None:
    assert "party_missing_истца" in _codes(_form(claimant=[]))
    assert "party_missing_ответчика" in _codes(_form(defendant=["[ТРЕБУЕТ УТОЧНЕНИЯ: данные ответчика]"]))


# --- цена иска и расчёт ------------------------------------------------------


def test_missing_price_is_critical() -> None:
    assert "price_missing" in _codes(_form(price_of_claim="[ТРЕБУЕТ УТОЧНЕНИЯ: цена иска]"))


def test_price_without_amount_is_critical() -> None:
    assert "price_missing" in _codes(_form(price_of_claim="согласно расчёту"))


def test_missing_breakdown_is_critical() -> None:
    assert "price_breakdown_missing" in _codes(_form(price_breakdown=""))


# --- досудебный порядок ------------------------------------------------------


def test_required_pretrial_without_confirmation_is_critical() -> None:
    assert "pretrial_not_confirmed" in _codes(_form(pretrial_required=True, pretrial_confirmed=False))


def test_confirmed_pretrial_passes() -> None:
    assert "pretrial_not_confirmed" not in _codes(_form(pretrial_required=True, pretrial_confirmed=True))


def test_pretrial_not_required_is_not_a_defect() -> None:
    assert "pretrial_not_confirmed" not in _codes(_form(pretrial_required=False))


# --- приложения --------------------------------------------------------------


def test_evidence_absent_from_annexes_is_critical() -> None:
    """Факт опирается на расписку, а в приложениях её нет."""
    result = check_claim_form(_form(attachments=["Копия удостоверения личности"]))

    codes = {d.code for d in result.critical}
    assert "attachment_missing" in codes
    assert "расписк" in result.critical[0].message


def test_evidence_present_in_annexes_passes() -> None:
    assert "attachment_missing" not in _codes(_form())


def test_evidence_matched_in_another_case_form() -> None:
    """Приложение в другом падеже всё равно засчитывается."""
    form = _form(
        facts=["Оплата произведена, что подтверждается платёжным поручением"],
        attachments=["Копия платёжного поручения от 12.03.2026"],
    )

    assert "attachment_missing" not in _codes(form)


# --- заголовок и просительная часть ------------------------------------------


def test_truncated_title_is_critical() -> None:
    assert "title_truncated" in _codes(_form(title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании долга и"))


def test_title_ending_with_dash_is_critical() -> None:
    assert "title_truncated" in _codes(_form(title="ИСКОВОЕ ЗАЯВЛЕНИЕ —"))


def test_missing_title_is_critical() -> None:
    assert "title_missing" in _codes(_form(title="  "))


def test_missing_requests_is_critical() -> None:
    assert "requests_missing" in _codes(_form(requests=[]))


# --- итог --------------------------------------------------------------------


def test_marker_names_every_critical_defect() -> None:
    result = check_claim_form(_form(court="", price_breakdown=""))

    marker = result.marker()

    assert marker.startswith(FILING_BLOCKED_MARKER)
    assert "суд не назван" in marker
    assert "расчёт цены иска" in marker


def test_critical_defects_are_listed_first() -> None:
    result = check_claim_form(_form(court="Суд по месту жительства ответчика", price_breakdown=""))

    assert result.defects[0].severity is Severity.CRITICAL
    assert result.defects[-1].severity is Severity.WARNING


def test_lines_are_prefixed_by_severity() -> None:
    lines = check_claim_form(_form(court="")).lines()

    assert lines[0].startswith("КРИТИЧНО:")
