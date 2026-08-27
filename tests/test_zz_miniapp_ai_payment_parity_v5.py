from __future__ import annotations

import asyncio
import inspect
from pathlib import Path


def test_v5_replaces_manual_document_payment_routes() -> None:
    from korgan import miniapp_api_v5

    def routes(path: str, method: str):
        return [
            route
            for route in miniapp_api_v5.app.router.routes
            if getattr(route, "path", None) == path
            and method.upper() in (getattr(route, "methods", set()) or set())
        ]

    assert len(routes("/miniapp/documents/generate", "POST")) == 1
    assert routes("/miniapp/documents/generate", "POST")[0].endpoint is miniapp_api_v5.generate_document
    assert len(routes("/miniapp/documents/payments/{order_id}/receipt", "POST")) == 1
    assert routes("/miniapp/documents/payments/{order_id}/receipt", "POST")[0].endpoint is miniapp_api_v5.document_payment_receipt
    assert len(routes("/miniapp/documents/payments/{order_id}/retry", "POST")) == 1
    assert routes("/miniapp/admin/document-payments", "GET") == []
    assert routes("/miniapp/admin/document-payments/{order_id}/decision", "POST") == []


def test_v5_parity_declares_ai_verification_without_admin() -> None:
    from korgan import miniapp_api_v5

    payload = asyncio.run(miniapp_api_v5.parity())
    assert payload["api_version"] == "1.0.0"
    assert payload["document_manual_confirmation"] is False
    assert payload["document_ai_receipt_verification"] is True
    assert payload["service_outer"] == "ClaimPipelineV2Adapter"
    assert payload["service_claim_mux"] == "ClaimServiceMux"
    assert payload["service_stable"] == "PretrialResponseProductionService"


def test_v5_receipt_uses_agent_hard_gate_and_immediate_generation() -> None:
    from korgan import miniapp_api_v5

    source = inspect.getsource(miniapp_api_v5.document_payment_receipt)
    assert "receipt_hard_issues(" in source
    assert "expected_recipient=settings.kaspi_payment_recipient" in source
    assert "offered_at=offered_at" in source
    assert "accept_ai_verified_document_receipt" in source
    assert "_generate_verified_order" in source


def test_miniapp_ui_boots_auto_payment_client() -> None:
    root = Path(__file__).resolve().parents[1]
    index = (root / "miniapp" / "index.html").read_text(encoding="utf-8")
    api = (root / "miniapp" / "src" / "korganApiV2.js").read_text(encoding="utf-8")
    ui = (root / "miniapp" / "src" / "main_v2.jsx").read_text(encoding="utf-8")

    assert "/src/main_v2.jsx" in index
    assert "document_manual_confirmation !== false" in api
    assert "document_ai_receipt_verification !== true" in api
    assert "uploadDocumentReceipt" in ui
    assert "finishDocument(r)" in ui
    assert "ожида" not in ui.lower() or "администратор" not in ui.lower()
