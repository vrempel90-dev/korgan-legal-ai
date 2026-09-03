from __future__ import annotations

from korgan.client_calculation_advisory import (
    build_calculation_advisory,
    unresolved_calculation_items,
)
from korgan.legal_calc import NEEDS_CALCULATION_MARKER
from korgan.legal_types import ClaimDraft, VerificationStatus


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Иск",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="1 000 000 тенге",
        facts=["Долг не возвращён."],
        legal_basis=[],
        requests=["Взыскать 1 000 000 тенге."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_no_advisory_when_all_calculations_are_confirmed() -> None:
    draft = _draft()
    draft.state_duty = "Государственная пошлина: 10 000 тенге."
    draft.late_interest = "Неустойка: 25 000 тенге."

    assert unresolved_calculation_items(draft) == []
    assert build_calculation_advisory(draft) == ""


def test_penalty_due_date_uncertainty_becomes_client_facing_item() -> None:
    draft = _draft()
    draft.late_interest = (
        "Неустойка в цену иска и просительную часть не включена. "
        "Требует уточнения: не удалось однозначно установить дату начала просрочки."
    )

    items = unresolved_calculation_items(draft)
    advisory = build_calculation_advisory(draft)

    assert len(items) == 1
    assert items[0].startswith("Неустойка:")
    assert "дат" in items[0].lower()
    assert "советую обратиться к юристу KORGAN" in advisory
    assert "не подставляет неподтверждённые суммы" in advisory


def test_state_duty_marker_becomes_separate_client_facing_item() -> None:
    draft = _draft()
    draft.state_duty = f"{NEEDS_CALCULATION_MARKER}: не определена госпошлина"

    items = unresolved_calculation_items(draft)

    assert items == [
        "Госпошлина: уточнить размер государственной пошлины или подтвердить основание льготы."
    ]


def test_non_calculation_verification_note_does_not_trigger_advisory() -> None:
    draft = _draft()
    draft.verification_notes = ["Подсудность требует проверки до подачи."]

    assert unresolved_calculation_items(draft) == []
    assert build_calculation_advisory(draft) == ""


def test_kazakh_advisory_recommends_korgan_lawyer() -> None:
    draft = _draft()
    draft.late_interest = "Тұрақсыздық айыбы — нақтылау қажет: мерзімнің басталу күні анықталмады."

    advisory = build_calculation_advisory(draft, language="kk")

    assert "Тұрақсыздық айыбы" in advisory
    assert "KORGAN заңгеріне жүгінуге кеңес беремін" in advisory
