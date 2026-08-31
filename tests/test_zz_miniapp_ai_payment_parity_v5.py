from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from korgan import miniapp_api_ofd_upload as upload_runtime
from korgan import miniapp_api_v5 as v5


def _route(path: str, method: str):
    matches = [
        route
        for route in v5.app.router.routes
        if getattr(route, "path", None) == path
        and method in (getattr(route, "methods", set()) or set())
    ]
    assert len(matches) == 1
    return matches[0]


def test_automatic_payment_routes_use_fiscal_upload_bridge_and_v5_delivery() -> None:
    """Маршруты, которыми v5 владеет и в собранном приложении.

    Приём чека за документ намеренно не проверяется здесь: поверх фискального
    моста стоит ручное подтверждение администратором
    (korgan.miniapp_manual_payment_admin), и утверждать из этого модуля, что
    верхний слой — upload_runtime, значило бы спорить с более поздним решением.
    Фактические владельцы всех маршрутов собраны в
    tests/test_production_route_ownership.
    """
    assert _route("/miniapp/documents/generate", "POST").endpoint is v5.generate_document
    assert (
        _route("/miniapp/consultation/payments/{order_id}/receipt", "POST").endpoint
        is upload_runtime.consultation_receipt_upload
    )
    assert (
        _route("/miniapp/consultation/payments/{order_id}", "GET").endpoint
        is upload_runtime.consultation_payment_status
    )
    assert _route("/miniapp/documents/payments/{order_id}", "GET").endpoint is v5.document_payment_status
    assert _route("/miniapp/documents/payments/{order_id}/retry", "POST").endpoint is v5.retry_paid_document


def test_strict_receipt_gate_matches_agent_requirements(monkeypatch) -> None:
    monkeypatch.setattr(v5.settings, "kaspi_payment_recipient", "OpenCourt (KORGAN)")
    now = datetime.now(timezone.utc)
    valid = SimpleNamespace(
        readable=True,
        looks_like_kaspi=True,
        payment_successful=True,
        amount_kzt=1000,
        date_time=now.isoformat(),
        merchant_or_recipient="OpenCourt (KORGAN)",
        receipt_or_transaction_id="TX-100",
        suspicious_signals=(),
    )
    assert v5._strict_receipt_issues(valid, 1000, offered_at=now) == []

    wrong_recipient = SimpleNamespace(**{**valid.__dict__, "merchant_or_recipient": "Other merchant"})
    assert any("получатель" in issue for issue in v5._strict_receipt_issues(wrong_recipient, 1000, offered_at=now))

    suspicious = SimpleNamespace(**{**valid.__dict__, "suspicious_signals": ("edited",)})
    assert any("аномалии" in issue for issue in v5._strict_receipt_issues(suspicious, 1000, offered_at=now))


def test_payment_payload_requires_no_admin_confirmation() -> None:
    order = SimpleNamespace(
        id=1,
        case_id="case-1",
        document_type="claim",
        amount_kzt=1000,
        status="approved",
        decision_note="AI receipt verification passed",
    )
    payload = v5._payment_payload(order)
    assert payload["approval_required"] is False
    assert payload["status"] == "approved"
