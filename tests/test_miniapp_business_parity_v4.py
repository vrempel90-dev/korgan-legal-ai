from __future__ import annotations

import asyncio

from korgan import miniapp_api_v4


def _routes(path: str, method: str):
    return [
        route
        for route in miniapp_api_v4.app.router.routes
        if getattr(route, "path", None) == path
        and method.upper() in (getattr(route, "methods", set()) or set())
    ]


def test_direct_unlimited_consultation_route_is_replaced() -> None:
    routes = _routes("/miniapp/consultation", "POST")
    assert len(routes) == 1
    assert routes[0].endpoint is miniapp_api_v4.consultation


def test_direct_document_generation_route_is_replaced_by_payment_gate() -> None:
    routes = _routes("/miniapp/documents/generate", "POST")
    assert len(routes) == 1
    assert routes[0].endpoint is miniapp_api_v4.generate_document


def test_paid_consultation_receipt_and_retry_routes_exist() -> None:
    assert len(_routes("/miniapp/consultation/payments/{order_id}/receipt", "POST")) == 1
    assert len(_routes("/miniapp/consultation/payments/{order_id}/retry", "POST")) == 1


def test_document_payment_and_manual_admin_routes_exist() -> None:
    assert len(_routes("/miniapp/documents/payments/{order_id}/receipt", "POST")) == 1
    assert len(_routes("/miniapp/documents/payments/{order_id}", "GET")) == 1
    assert len(_routes("/miniapp/admin/document-payments", "GET")) == 1
    assert len(_routes("/miniapp/admin/document-payments/{order_id}/decision", "POST")) == 1


def test_business_parity_probe_matches_runtime_settings() -> None:
    payload = asyncio.run(miniapp_api_v4.parity())
    assert payload["status"] == "ok"
    assert payload["api_version"] == "0.9.0"
    assert payload["service_outer"] == "ClaimPipelineV2Adapter"
    assert payload["service_claim_mux"] == "ClaimServiceMux"
    assert payload["service_stable"] == "PretrialResponseProductionService"
    assert payload["consultation_limit_enabled"] is bool(miniapp_api_v4.settings.consultation_limit_enabled)
    assert payload["free_consultations_per_day"] == int(miniapp_api_v4.settings.free_consultations_per_day)
    assert payload["consultation_price_kzt"] == int(miniapp_api_v4.settings.consultation_price_kzt)
    assert payload["document_payments_enabled"] is bool(miniapp_api_v4.settings.payments_enabled)
    assert payload["document_price_kzt"] == int(miniapp_api_v4.settings.document_price_kzt)
    assert payload["document_manual_confirmation"] is True
