from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def _run_isolated(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "TELEGRAM_BOT_TOKEN": "000000:test-only-token",
            "OPENAI_API_KEY": "test-only-openai-key",
            "PAYMENTS_ENABLED": "false",
            "KASPI_PAYMENT_RECIPIENT": "OpenCourt (KORGAN)",
        }
    )
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def test_v5_runtime_isolated_from_agent_test_process() -> None:
    result = _run_isolated(
        r'''
        import asyncio
        from korgan import miniapp_api_v5 as appmod

        def routes(path, method):
            return [
                route for route in appmod.app.router.routes
                if getattr(route, "path", None) == path
                and method.upper() in (getattr(route, "methods", set()) or set())
            ]

        assert len(routes("/miniapp/documents/generate", "POST")) == 1
        assert routes("/miniapp/documents/generate", "POST")[0].endpoint is appmod.generate_document
        assert len(routes("/miniapp/documents/payments/{order_id}/receipt", "POST")) == 1
        assert routes("/miniapp/documents/payments/{order_id}/receipt", "POST")[0].endpoint is appmod.document_payment_receipt
        assert len(routes("/miniapp/documents/payments/{order_id}/retry", "POST")) == 1
        assert routes("/miniapp/admin/document-payments", "GET") == []
        assert routes("/miniapp/admin/document-payments/{order_id}/decision", "POST") == []

        payload = asyncio.run(appmod.parity())
        assert payload["api_version"] == "1.0.0"
        assert payload["document_manual_confirmation"] is False
        assert payload["document_ai_receipt_verification"] is True
        assert payload["service_outer"] == "ClaimPipelineV2Adapter"
        assert payload["service_claim_mux"] == "ClaimServiceMux"
        assert payload["service_stable"] == "PretrialResponseProductionService"
        assert set(payload["document_types"]) == {"claim", "contract", "response", "pretrial", "pretrial_response"}
        '''
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_v5_receipt_uses_same_agent_hard_gate_and_immediate_generation() -> None:
    source = (ROOT / "korgan" / "miniapp_api_v5.py").read_text(encoding="utf-8")
    store = (ROOT / "korgan" / "miniapp_payment_parity.py").read_text(encoding="utf-8")

    assert "ReceiptAnalyzer(settings).analyze" in source
    assert "receipt_hard_issues(" in source
    assert "expected_recipient=settings.kaspi_payment_recipient" in source
    assert "offered_at=offered_at" in source
    assert "accept_ai_verified_document_receipt" in source
    assert "_generate_verified_order" in source
    assert "document_manual_confirmation\": False" in source
    assert "document_ai_receipt_verification\": True" in source
    assert "UniqueViolationError" in store
    assert "status='approved'" in store
    assert "same_hash" in store and "same_tx" in store


def test_v5_payment_failure_is_fail_closed_and_retry_safe() -> None:
    source = (ROOT / "korgan" / "miniapp_api_v5.py").read_text(encoding="utf-8")

    assert "Документ остаётся заблокирован" in source
    assert "Не платите повторно" in source or "не платите повторно" in source
    assert "Повторно платить не нужно" in source
    assert "/miniapp/documents/payments/{order_id}/retry" in source
    assert "current_scope != order.case_fingerprint" in source


def test_miniapp_ui_exposes_agent_client_functions_and_auto_payment() -> None:
    index = (ROOT / "miniapp" / "index.html").read_text(encoding="utf-8")
    api = (ROOT / "miniapp" / "src" / "korganApiV2.js").read_text(encoding="utf-8")
    ui = (ROOT / "miniapp" / "src" / "main_v2.jsx").read_text(encoding="utf-8")

    assert "/src/main_v2.jsx" in index
    assert "document_manual_confirmation !== false" in api
    assert "document_ai_receipt_verification !== true" in api
    for method in (
        "consultation",
        "uploadMaterial",
        "generateDocument",
        "uploadDocumentReceipt",
        "retryPaidDocument",
        "getDocument",
        "deleteMyData",
    ):
        assert method in api
    for kind in ("claim", "contract", "response", "pretrial", "pretrial_response"):
        assert f"id: '{kind}'" in ui
    assert "uploadDocumentReceipt" in ui
    assert "finishDocument(r)" in ui
    assert "ручного подтверждения администратора" not in ui.lower()
