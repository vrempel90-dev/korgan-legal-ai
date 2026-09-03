from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from korgan.professional_consultation import _render_consultation


def test_recovery_runtime_has_no_free_document_generation_import() -> None:
    source = Path("korgan/miniapp_api_recovery_cors.py").read_text(encoding="utf-8")
    assert "miniapp_free_generation_runtime" not in source
    assert "miniapp_document_payment_required" not in source


def test_generation_owner_fails_closed_when_payments_are_disabled(monkeypatch) -> None:
    from korgan import miniapp_generation_api as generation_api

    monkeypatch.setattr(generation_api.settings, "payments_enabled", False)
    with pytest.raises(HTTPException) as raised:
        generation_api._require_paid_document_runtime()
    assert raised.value.status_code == 503
    assert "только после подтвержденной оплаты" in str(raised.value.detail)


def test_generation_owner_keeps_existing_route_identity() -> None:
    from korgan import miniapp_generation_api as generation_api

    routes = [
        route
        for route in generation_api.app.router.routes
        if getattr(route, "path", None) == "/miniapp/documents/generate"
        and "POST" in (getattr(route, "methods", set()) or set())
    ]
    assert len(routes) == 1
    # Tole may intentionally own the route when configured in a real runtime;
    # otherwise durable generation remains the single owner. The hard payment
    # rule is implemented inside that owner instead of by installing a shadow
    # route in tests/staging.
    assert "miniapp_document_payment_required" not in routes[0].endpoint.__module__


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


def test_professional_consultation_preserves_service_object_identity() -> None:
    from korgan import miniapp_api_v3
    from korgan import miniapp_professional_consultation_runtime  # noqa: F401

    assert miniapp_api_v3.core.service is miniapp_api_v3.service
