from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan import miniapp_paid_receipt_handoff_runtime as runtime
from korgan.miniapp_document_payments import DocumentPaymentOrder
from korgan.miniapp_generation_jobs import GenerationJob


def _order() -> DocumentPaymentOrder:
    return DocumentPaymentOrder(
        id=7001,
        user_key="a" * 64,
        case_id="case-7001",
        case_fingerprint="scope-7001",
        document_type="claim",
        language="ru",
        amount_kzt=1000,
        status="approved",
        transaction_id="tx-7001",
        receipt_check={},
        decision_note="",
    )


def _job(status: str = "queued") -> GenerationJob:
    return GenerationJob(
        id="job-7001",
        payment_order_id=7001,
        user_key="a" * 64,
        case_id="case-7001",
        status=status,
        stage=status,
        progress=0 if status != "succeeded" else 100,
        error_detail="",
    )


def test_receipt_confirmation_returns_quick_durable_job_payload(monkeypatch) -> None:
    starts: list[int] = []

    async def start(order_id: int):
        starts.append(order_id)
        return _job("queued")

    monkeypatch.setattr(runtime.paid_runtime, "start_paid_generation", start)
    monkeypatch.setattr(runtime.v5, "_payment_payload", lambda order: {
        "order_id": order.id,
        "case_id": order.case_id,
        "status": order.status,
    })

    result = asyncio.run(
        runtime._durable_run_approved_document(
            _order(),
            x_telegram_init_data="this-must-not-be-needed-for-background-generation",
        )
    )

    assert starts == [7001]
    assert result["payment_required"] is False
    assert result["payment_confirmed"] is True
    assert result["generation_started"] is True
    assert result["job"]["job_id"] == "job-7001"
    assert result["payment"]["status"] == "approved"


def test_recovery_scans_all_approved_orders_not_only_tole(monkeypatch) -> None:
    queries: list[str] = []
    scheduled: list[int] = []

    class DocumentPool:
        async def fetch(self, query: str, limit: int):
            queries.append(query)
            assert limit == runtime._RECOVERY_BATCH_SIZE
            return [{"id": 11}, {"id": 12}]

    async def recover(_pool):
        return None

    async def start(order_id: int):
        scheduled.append(order_id)
        return _job("queued")

    monkeypatch.setattr(runtime.generation_runtime.settings, "payments_enabled", True)
    monkeypatch.setattr(runtime.jobs, "_require_pool", lambda: SimpleNamespace())
    monkeypatch.setattr(runtime.jobs, "recover_interrupted_jobs", recover)
    monkeypatch.setattr(runtime.document_store, "_require_pool", lambda: DocumentPool())
    monkeypatch.setattr(runtime.paid_runtime, "start_paid_generation", start)
    monkeypatch.setattr(runtime.tole_runtime, "tole_configured", lambda: False)

    asyncio.run(runtime._reconcile_all_paid_work())

    assert scheduled == [11, 12]
    assert len(queries) == 1
    assert "korgan_miniapp_document_orders" in queries[0]
    assert "korgan_miniapp_tole_payments" not in queries[0], "receipt orders must survive without a Tole row"
    assert "status IN ('approved', 'consumed')" in queries[0]
