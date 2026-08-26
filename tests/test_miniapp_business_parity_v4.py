from __future__ import annotations

import asyncio
from pathlib import Path

from korgan import miniapp_api_v4
from korgan.payment import ReceiptCheck, receipt_hard_issues


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
    # v4 remains the compatibility base. The auto-payment overlay replaces the
    # receipt route at launch time while keeping these legacy admin endpoints for
    # orders already left in awaiting_admin before the deploy.
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


def test_auto_payment_overlay_disables_manual_confirmation_and_auto_generates() -> None:
    source = Path("korgan/miniapp_auto_payment.py").read_text(encoding="utf-8")
    assert '"document_manual_confirmation": False' in source
    assert '"document_ai_receipt_verification": True' in source
    assert '"document_auto_generation_after_receipt": True' in source
    assert "accept_document_receipt_ai_verified" in source
    assert "receipt_hard_issues(check, order.amount_kzt)" in source
    assert "core.generate_document(payload, x_telegram_init_data)" in source
    assert "consume_document_order" in source


def test_auto_payment_store_approves_receipt_atomically_without_admin() -> None:
    source = Path("korgan/miniapp_document_payments.py").read_text(encoding="utf-8")
    assert "accept_document_receipt_ai_verified" in source
    assert "target_status=\"approved\"" in source
    assert "CREATE UNIQUE INDEX IF NOT EXISTS korgan_miniapp_document_receipts_tx_unique" in source
    assert "FOR UPDATE" in source


def test_auto_payment_frontend_goes_directly_to_ready_document() -> None:
    patch = Path("miniapp/auto-payment-patch.mjs").read_text(encoding="utf-8")
    package = Path("miniapp/package.json").read_text(encoding="utf-8")
    assert "if (result?.document_base64)" in patch
    assert "setScreen('ready')" in patch
    assert "document_ai_receipt_verification" in patch
    assert "document_auto_generation_after_receipt" in patch
    assert "node auto-payment-patch.mjs && vite build" in package


def test_strict_receipt_rules_accept_complete_clean_receipt() -> None:
    check = ReceiptCheck(
        readable=True,
        looks_like_kaspi=True,
        payment_successful=True,
        amount_kzt=1000,
        date_time="2026-08-26 21:30",
        merchant_or_recipient="KORGAN",
        payer="Client",
        receipt_or_transaction_id="TX-OK-1",
        rnm="",
        fp="",
        suspicious_signals=(),
        notes=(),
    )
    assert receipt_hard_issues(check, 1000) == []


def test_strict_receipt_rules_fail_closed_on_suspicious_or_incomplete_receipt() -> None:
    check = ReceiptCheck(
        readable=True,
        looks_like_kaspi=True,
        payment_successful=True,
        amount_kzt=1000,
        date_time="",
        merchant_or_recipient="KORGAN",
        payer="Client",
        receipt_or_transaction_id="",
        rnm="",
        fp="",
        suspicious_signals=("possible edit",),
        notes=(),
    )
    issues = receipt_hard_issues(check, 1000)
    assert any("дата/время" in item for item in issues)
    assert any("номер операции" in item for item in issues)
    assert any("аномалии" in item for item in issues)
