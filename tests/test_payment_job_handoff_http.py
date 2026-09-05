"""Exercise the actual payment routes without a bank, AI call or real database."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from korgan import miniapp_payment_hardening_runtime as runtime


@pytest.fixture
def payment_routes(monkeypatch):
    original_routes = list(runtime.app.router.routes)
    monkeypatch.setattr(runtime, "_INSTALLED", False)
    monkeypatch.setattr(runtime.tole_runtime, "tole_configured", lambda: True)
    monkeypatch.setattr(runtime.tole_runtime, "_require_tole_runtime", lambda: None)
    monkeypatch.setattr(runtime.settings, "payments_enabled", True)
    runtime.install_payment_hardening_runtime()
    try:
        yield runtime.app
    finally:
        runtime.app.router.routes = original_routes


@pytest.mark.parametrize("document_type", ["claim", "contract", "response", "pretrial", "pretrial_response"])
@pytest.mark.parametrize("status", ["approved", "consumed"])
def test_reopened_paid_case_reuses_job_without_new_invoice(monkeypatch, payment_routes, status, document_type):
    order = SimpleNamespace(id=71, user_key="owner-key", case_id="case-1", case_fingerprint="scope-1", status=status)
    completed = status == "consumed"
    job = runtime.jobs.GenerationJob("job-71", 71, "owner-key", "case-1", "succeeded" if completed else "running", "completed" if completed else "legal_drafting", 100 if completed else 55, "")

    async def scope(payload, init_data):
        assert init_data == "unit-test-identity"
        assert payload.document_type == document_type
        return "identity", {}, {}, "owner-key", "scope-1", document_type, "ru"

    async def order_lookup(order_id, *, user_key):
        assert order_id == 71 and user_key == "owner-key"
        return order

    new_invoice = AsyncMock(side_effect=AssertionError("second invoice after payment"))
    monkeypatch.setattr(runtime.generation_runtime, "_generation_scope", scope)
    monkeypatch.setattr(runtime.jobs, "latest_job_for_case", AsyncMock(return_value=job))
    monkeypatch.setattr(runtime.document_store, "get_document_order", order_lookup)
    monkeypatch.setattr(runtime.tole_runtime, "_resolve_document_order", new_invoice)
    monkeypatch.setattr(runtime.core.legacy, "_require_consent", AsyncMock(return_value={}))
    monkeypatch.setattr(runtime.generation_runtime, "_ready_document", lambda *_: {"filename": f"{document_type}.docx"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=payment_routes), base_url="http://unit.test") as client:
            response = await client.post("/miniapp/documents/generate", json={"case_id": "case-1", "document_type": document_type, "language": "ru"}, headers={"X-Telegram-Init-Data": "unit-test-identity"})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["payment_confirmed"] is True
            assert result["payment_required"] is False
            assert result["job"]["job_id"] == "job-71"
            if completed:
                assert result["document"]["filename"] == f"{document_type}.docx"

    asyncio.run(scenario())
    new_invoice.assert_not_awaited()
