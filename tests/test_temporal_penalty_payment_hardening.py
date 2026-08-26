from __future__ import annotations

import inspect
from datetime import date

from korgan.legal_types import VerificationStatus
from korgan.pretrial import PretrialDraft
from korgan.temporal_penalty_payment_hardening import (
    _BANK_MARKER,
    apply_penalty_result_to_draft,
    calculate_temporal_penalty_from_context,
    due_date_from_context,
    ensure_payment_requisites,
    narrow_release_issues,
    payment_requisites_issues,
    penalty_demand_issues,
)
import korgan.temporal_penalty_payment_hardening as hardening


F2 = """
20.02.2026 Поставщик осуществил поставку товара стоимостью 3 250 000 тенге.
Срок оплаты по договору составляет 15 календарных дней с момента поставки.
Пункт 6.1 договора: за просрочку оплаты начисляется договорная неустойка 0,2% от суммы задолженности
за каждый календарный день просрочки, но не более 20% от суммы задолженности.
По состоянию на 25.08.2026 задолженность не погашена.
Требуем уплатить основной долг и договорную неустойку.
"""

F3 = """
Стоимость оказанных услуг по договору составляет 1 800 000 тенге.
Срок оплаты по договору: до 20.01.2026.
28.02.2026 произведена частичная оплата 600 000 тенге.
Пункт 8.2 договора: при просрочке Заказчик уплачивает договорную неустойку 0,1% от суммы задолженности
за каждый календарный день просрочки.
По состоянию на 25.08.2026 остаток основного долга составляет 1 200 000 тенге.
Требуем уплатить задолженность и договорную неустойку.
"""


def _draft(*, demand: str) -> PretrialDraft:
    return PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="Досудебная претензия",
        sender=["ТОО «Исполнитель»", "БИН 123456789012"],
        recipient=["ТОО «Заказчик»"],
        facts=["Обязательство по оплате нарушено."],
        legal_basis=[],
        demands=[demand],
        deadline="20 календарных дней",
        consequences=[],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_f2_context_derives_due_date_next_day_and_cap_result() -> None:
    assert due_date_from_context(F2) == date(2026, 3, 7)
    result = calculate_temporal_penalty_from_context(F2)
    assert result is not None
    assert result.segments[0]["from"] == date(2026, 3, 8)
    assert result.cap_amount == 650_000
    assert result.cap_reached_date == date(2026, 6, 15)
    assert result.total == 650_000
    assert result.daily_after == 0


def test_f3_context_uses_fixed_due_date_and_partial_payment_segments() -> None:
    assert due_date_from_context(F3) == date(2026, 1, 20)
    result = calculate_temporal_penalty_from_context(F3)
    assert result is not None
    assert result.segments == [
        {
            "from": date(2026, 1, 21),
            "to": date(2026, 2, 28),
            "base": 1_800_000,
            "rate_per_day": 1_800,
            "days": 39,
            "amount": 70_200,
        },
        {
            "from": date(2026, 3, 1),
            "to": date(2026, 8, 25),
            "base": 1_200_000,
            "rate_per_day": 1_200,
            "days": 178,
            "amount": 213_600,
        },
    ]
    assert result.total == 283_800
    assert result.daily_after == 1_200
    assert result.outstanding_principal == 1_200_000


def test_vague_penalty_demand_is_rewritten_and_segment_calculation_disclosed() -> None:
    result = calculate_temporal_penalty_from_context(F3)
    assert result is not None
    draft = _draft(demand="Требуем уплатить неустойку в сумме, подлежащей уточнению, путём перечисления на расчётный счёт ТОО «Исполнитель».")

    assert penalty_demand_issues(draft)
    assert payment_requisites_issues(draft)

    apply_penalty_result_to_draft(draft, result)
    ensure_payment_requisites(draft, F3)

    assert "283 800 тенге" in draft.demands[0]
    assert "подлежащ" not in draft.demands[0].lower()
    text = "\n".join([*draft.facts, *draft.demands])
    assert "21.01.2026–28.02.2026" in text
    assert "39 календарных дней" in text
    assert "70 200 тенге" in text
    assert "01.03.2026–25.08.2026" in text
    assert "178 календарных дней" in text
    assert "213 600 тенге" in text
    assert "платёж уменьшает основной долг со следующего календарного дня" in text
    assert _BANK_MARKER in text
    assert narrow_release_issues(draft) == []


def test_f2_render_discloses_cap_reached_date() -> None:
    result = calculate_temporal_penalty_from_context(F2)
    assert result is not None
    draft = _draft(demand="Требуем уплатить договорную неустойку, размер которой подлежит уточнению.")
    apply_penalty_result_to_draft(draft, result)
    text = "\n".join([*draft.facts, *draft.demands])
    assert "650 000 тенге" in text
    assert "15.06.2026" in text
    assert "0 тенге; договорный ограничитель достигнут" in text
    assert penalty_demand_issues(draft) == []


def test_complete_payment_requisites_are_copied_from_source_without_invention() -> None:
    source = """
ТОО «Исполнитель»
БИН: 123456789012
ИИК: KZ123456789012345678
Банк: АО «Банк ЦентрКредит»
БИК: KCJBKZKX
КБе: 17
Назначение платежа: погашение задолженности по договору № 7.
"""
    draft = _draft(demand="Перечислить задолженность на расчётный счёт ТОО «Исполнитель».")
    assert ensure_payment_requisites(draft, source) is True
    block = draft.demands[-1]
    assert _BANK_MARKER not in block
    assert "ИИК: KZ123456789012345678" in block
    assert "БИК: KCJBKZKX" in block
    assert "КБе: 17" in block
    assert "Назначение платежа: погашение задолженности" in block
    assert payment_requisites_issues(draft) == []


def test_payment_instruction_without_requisites_or_marker_is_rejected() -> None:
    draft = _draft(demand="Перечислить 1 200 000 тенге на расчётный счёт ТОО «Исполнитель».")
    assert payment_requisites_issues(draft) == [
        "требование перечислить деньги на счёт не содержит банковских реквизитов или [ДАННЫЕ]-маркера"
    ]


def test_new_hardening_has_no_direct_model_call() -> None:
    source = inspect.getsource(hardening)
    assert "_structured_response(" not in source
    assert "responses.create(" not in source
