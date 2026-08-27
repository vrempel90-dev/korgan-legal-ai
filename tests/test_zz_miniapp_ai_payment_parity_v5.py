from __future__ import annotations

from types import SimpleNamespace

from korgan import miniapp_api_v5 as v5
from korgan import miniapp_api_v6 as v6
from korgan import miniapp_api_v7 as v7


def _route(path: str, method: str):
    matches = [
        route
        for route in v7.app.router.routes
        if getattr(route, "path", None) == path
        and method in (getattr(route, "methods", set()) or set())
    ]
    assert len(matches) == 1
    return matches[0]


def test_v7_owns_receipt_route_and_keeps_document_runtime() -> None:
    assert _route("/miniapp/documents/generate", "POST").endpoint is v5.generate_document
    assert _route("/miniapp/documents/payments/{order_id}/receipt", "POST").endpoint is v7.document_payment_receipt
    assert _route("/miniapp/documents/payments/{order_id}", "GET").endpoint is v5.document_payment_status
    assert _route("/miniapp/documents/payments/{order_id}/retry", "POST").endpoint is v5.retry_paid_document


def test_v6_merchant_alias_helper_accepts_branch_suffix() -> None:
    assert v6._recipient_matches(
        "YSA education на Кунаева",
        "YSA EDUCATION|ИП YSA EDUCATION",
    )


def test_v6_merchant_alias_helper_rejects_other_merchant() -> None:
    assert not v6._recipient_matches(
        "Other merchant",
        "YSA EDUCATION|ИП YSA EDUCATION",
    )


def test_payment_payload_requires_no_admin_confirmation() -> None:
    order = SimpleNamespace(
        id=1,
        case_id="case-1",
        document_type="claim",
        amount_kzt=1000,
        status="approved",
        decision_note="Kaspi OFD deterministic verification passed",
    )
    payload = v5._payment_payload(order)
    assert payload["approval_required"] is False
    assert payload["status"] == "approved"
