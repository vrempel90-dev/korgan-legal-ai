from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from korgan.professional_consultation import _render_consultation


def test_recovery_runtime_has_no_free_document_generation_import() -> None:
    source = Path("korgan/miniapp_api_recovery_cors.py").read_text(encoding="utf-8")
    assert "miniapp_free_generation_runtime" not in source
    assert "miniapp_document_payment_required" in source


def test_paid_document_guard_fails_closed_when_payments_are_disabled() -> None:
    # Import locally so the static recovery-runtime assertion above stays useful
    # even if another test imported the complete Mini App stack first.
    from korgan.miniapp_document_payment_required import require_document_payments_enabled

    require_document_payments_enabled(True)
    with pytest.raises(HTTPException) as raised:
        require_document_payments_enabled(False)
    assert raised.value.status_code == 503
    assert "только после подтвержденной оплаты" in str(raised.value.detail)


def test_professional_consultation_drops_action_with_unverified_legal_basis() -> None:
    payload = {
        "qualification": "Спор о возврате уплаченной суммы.",
        "client_goal": "Вернуть деньги.",
        "verified_points": [],
        "actions": [
            {"action": "Сохранить платёжные документы.", "basis_statement": ""},
            {
                "action": "Обязательно подать иск в течение трёх дней.",
                "basis_statement": "У клиента есть трёхдневный срок.",
            },
        ],
        "risks": [],
        "unknowns": [],
    }
    text = _render_consultation(payload=payload, verified=[], rejected=[], language="ru")
    assert "Сохранить платёжные документы" in text
    assert "трёх дней" not in text
    assert "Я не могу подтвердить конкретную правовую норму" in text


def test_professional_consultation_keeps_action_linked_to_verified_point() -> None:
    statement = "Подтверждённый правовой вывод"
    payload = {
        "qualification": "Договорный спор.",
        "client_goal": "Защитить нарушенное право.",
        "verified_points": [],
        "actions": [
            {"action": "Использовать подтверждённый способ защиты.", "basis_statement": statement}
        ],
        "risks": [],
        "unknowns": ["Из материалов не следует дата получения уведомления."],
    }
    verified = [{
        "statement": statement,
        "article": "статья N",
        "provision_text": "текст",
        "source_url": "https://adilet.zan.kz/",
    }]
    text = _render_consultation(payload=payload, verified=verified, rejected=[], language="ru")
    assert statement in text
    assert "Использовать подтверждённый способ защиты" in text
    assert "Из материалов не следует дата получения уведомления" in text


def test_recovery_runtime_installs_professional_consultation_layer() -> None:
    source = Path("korgan/miniapp_api_recovery_cors.py").read_text(encoding="utf-8")
    assert "miniapp_professional_consultation_runtime" in source
