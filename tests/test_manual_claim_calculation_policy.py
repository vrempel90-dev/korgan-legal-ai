from __future__ import annotations

from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.manual_claim_calculation_policy import (
    calculator_penalty,
    calculator_state_duty,
    finalize_manual_claim_calculations,
)


def _draft(*, requests: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании задолженности",
        court="Районный суд",
        claimant=["Иванов Иван Иванович"],
        defendant=["Петров Пётр Сергеевич"],
        price_of_claim="599 000 тенге",
        facts=["Долг не возвращён в установленный срок."],
        legal_basis=["Правовое основание подтверждено."],
        requests=requests,
        attachments=[],
        verification_notes=[],
        source_urls=[],
        state_duty="5 990 тенге",
        late_interest="Автоматически рассчитанная неустойка: 99 000 тенге.",
        calculation=[
            "Основной долг: 500 000 тенге.",
            "Неустойка по статье 353 ГК РК: 99 000 тенге.",
        ],
    )


def test_without_calculator_lines_legacy_duty_and_penalty_are_removed() -> None:
    draft = _draft(
        requests=[
            "Взыскать с ответчика основной долг в размере 500 000 тенге.",
            "Взыскать неустойку по статье 353 ГК РК в размере 99 000 тенге.",
            "Взыскать расходы по уплате государственной пошлины в размере 5 990 тенге.",
        ]
    )

    finalize_manual_claim_calculations(
        "Прошу взыскать долг 500 000 тенге и рассчитать неустойку.",
        draft,
        language="ru",
    )

    assert draft.state_duty == ""
    assert draft.late_interest == ""
    assert all("99 000" not in item for item in draft.requests)
    assert all("5 990" not in item for item in draft.requests)
    assert all("неустой" not in item.lower() for item in draft.calculation)
    assert "500 000" in draft.price_of_claim


def test_calculator_lines_are_the_only_amounts_inserted_into_claim() -> None:
    context = """
Факты, сообщённые пользователем:
Основной долг: 500 000 тенге.
Рассчитанная госпошлина для иска: 5 000 тенге.
Рассчитанная неустойка по статье 353 ГК РК: 20 000 тенге за период с 11.03.2026 по 04.09.2026 (178 дн.).
"""
    draft = _draft(
        requests=[
            "Взыскать с ответчика основной долг в размере 500 000 тенге.",
            "Взыскать неустойку по статье 353 ГК РК в размере 99 000 тенге.",
            "Взыскать расходы по уплате государственной пошлины в размере 5 990 тенге.",
        ]
    )

    finalize_manual_claim_calculations(context, draft, language="ru")

    assert draft.state_duty == "5 000 тенге"
    assert "20 000 тенге" in draft.late_interest
    assert "99 000" not in "\n".join(draft.requests)
    assert "5 990" not in "\n".join(draft.requests)
    assert any("неустойку по статье 353" in item.lower() and "20 000 тенге" in item for item in draft.requests)
    assert any("государственной пошлины" in item.lower() and "5 000 тенге" in item for item in draft.requests)
    assert "520 000" in draft.price_of_claim


def test_exact_grounded_combined_request_is_not_duplicated() -> None:
    context = (
        "Рассчитанная неустойка по статье 353 ГК РК: 20 000 тенге "
        "за период с 11.03.2026 по 04.09.2026 (178 дн.)."
    )
    draft = _draft(
        requests=[
            "Взыскать основной долг 500 000 тенге и неустойку по статье 353 ГК РК 20 000 тенге."
        ]
    )

    finalize_manual_claim_calculations(context, draft, language="ru")

    penalty_requests = [item for item in draft.requests if "неустой" in item.lower()]
    assert len(penalty_requests) == 1
    assert "20 000" in penalty_requests[0]
    assert "520 000" in draft.price_of_claim


def test_ru_and_kk_calculator_markers_are_recognized() -> None:
    ru = (
        "Рассчитанная госпошлина для иска: 7 500 тенге.\n"
        "Рассчитанная неустойка по статье 353 ГК РК: 12 345 тенге за период с 01.01.2026 по 02.02.2026."
    )
    kk = (
        "Талап үшін есептелген мемлекеттік баж: 7 500 теңге.\n"
        "ҚР АК 353-бабы бойынша есептелген тұрақсыздық айыбы: 12 345 теңге, 01.01.2026–02.02.2026 кезеңі үшін."
    )

    assert calculator_state_duty(ru) == "7 500 тенге"
    assert calculator_penalty(ru) is not None
    assert calculator_penalty(ru).amount == "12 345 тенге"
    assert calculator_state_duty(kk) == "7 500 теңге"
    assert calculator_penalty(kk) is not None
    assert calculator_penalty(kk).amount == "12 345 теңге"
