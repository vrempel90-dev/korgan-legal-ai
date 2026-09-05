from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from korgan import miniapp_paid_autostart_runtime as runtime


def test_background_recovers_approved_work_before_provider_polling(monkeypatch):
    events = []

    async def fetch(sql, limit):
        assert "o.status IN ('approved', 'consumed')" in sql
        assert "j.id IS NULL OR j.status='queued'" in sql
        assert limit == 5
        return [{"id": 71}, {"id": 72}]

    async def start(order_id):
        events.append(("start", order_id))

    async def poll(*, limit):
        events.append(("poll", limit))

    recover = AsyncMock()
    pool = SimpleNamespace(fetch=fetch)
    monkeypatch.setattr(runtime.generation_runtime.settings, "payments_enabled", True)
    monkeypatch.setattr(runtime.tole_runtime, "tole_configured", lambda: True)
    monkeypatch.setattr(runtime.tole_runtime, "_ensure_schema", AsyncMock())
    monkeypatch.setattr(runtime.document_store, "_require_pool", lambda: pool)
    monkeypatch.setattr(runtime.jobs, "_require_pool", lambda: pool)
    monkeypatch.setattr(runtime.jobs, "recover_interrupted_jobs", recover)
    monkeypatch.setattr(runtime, "start_paid_generation", start)
    monkeypatch.setattr(runtime.tole_runtime, "_reconcile_pending_payments", poll)
    asyncio.run(runtime.reconcile_paid_work())
    assert events == [("start", 71), ("start", 72), ("poll", 5)]
    recover.assert_awaited_once_with(pool)


def test_disabled_payments_do_not_start_recovery_or_contact_provider(monkeypatch):
    monkeypatch.setattr(runtime.generation_runtime.settings, "payments_enabled", False)
    poll = AsyncMock(side_effect=AssertionError("payments disabled"))
    monkeypatch.setattr(runtime.tole_runtime, "_reconcile_pending_payments", poll)
    asyncio.run(runtime.reconcile_paid_work())
    poll.assert_not_awaited()


def test_failed_provider_read_rotates_queue_before_next_order(monkeypatch):
    events = []
    rows = [{"order_id": 71}, {"order_id": 72}]

    async def touch(order_id):
        events.append(("touch", order_id))

    async def reconcile(payment, *, client):
        events.append(("read", payment.order_id))
        if payment.order_id == 71:
            raise runtime.tole_runtime.ToleAPIError("timeout")

    monkeypatch.setattr(runtime.tole_runtime, "_ensure_schema", AsyncMock())
    monkeypatch.setattr(runtime.document_store, "_require_pool", lambda: SimpleNamespace(fetch=AsyncMock(return_value=rows)))
    monkeypatch.setattr(runtime.tole_runtime, "_client", lambda: object())
    monkeypatch.setattr(runtime.tole_runtime, "_payment_from_row", lambda row: SimpleNamespace(**row))
    monkeypatch.setattr(runtime.tole_runtime, "_upsert_provider_result", touch)
    monkeypatch.setattr(runtime.tole_runtime, "_reconcile_payment", reconcile)
    assert asyncio.run(runtime.tole_runtime._reconcile_pending_payments()) == 1
    assert events == [("touch", 71), ("read", 71), ("touch", 72), ("read", 72)]


@pytest.mark.parametrize("status", ["pending_receipt", "awaiting_admin", "rejected", "cancelled"])
def test_unpaid_orders_cannot_create_jobs(monkeypatch, status):
    monkeypatch.setattr(runtime.document_store, "get_document_order", AsyncMock(return_value=SimpleNamespace(status=status)))
    create = AsyncMock(side_effect=AssertionError("unpaid generation"))
    monkeypatch.setattr(runtime.jobs, "create_or_get_job", create)
    assert asyncio.run(runtime.start_paid_generation(71)) is None
    create.assert_not_awaited()


@pytest.mark.parametrize("consent", [None, False, True, {"accepted": False}])
def test_background_generation_honors_revoked_consent(monkeypatch, consent):
    load = AsyncMock(return_value={"consent": consent, "cases": {"case-1": {"description": "Факты"}}})
    monkeypatch.setattr(runtime.generation_runtime.core.store, "load_by_user_key", load)
    with pytest.raises(runtime.jobs.GenerationFailure, match="согласие"):
        asyncio.run(runtime._load_paid_case(SimpleNamespace(user_key="a" * 64, case_id="case-1")))


def test_worker_lifecycle_starts_after_stores_and_stops_before_close(monkeypatch):
    async def scenario():
        events = []
        started = asyncio.Event()

        @asynccontextmanager
        async def previous(_app):
            events.append("stores_open")
            yield
            events.append("stores_closed")

        async def worker():
            events.append("worker_start")
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                events.append("worker_stop")

        app = SimpleNamespace(router=SimpleNamespace(lifespan_context=previous))
        monkeypatch.setattr(runtime.generation_runtime, "app", app)
        monkeypatch.setattr(runtime.generation_runtime.settings, "payments_enabled", True)
        monkeypatch.setattr(runtime.tole_runtime, "tole_configured", lambda: True)
        monkeypatch.setattr(runtime, "_reconciliation_loop", worker)
        monkeypatch.setattr(runtime, "_AUTO_TASKS", {})
        runtime._install_background_lifespan()
        async with app.router.lifespan_context(app):
            await started.wait()
        assert events == ["stores_open", "worker_start", "worker_stop", "stores_closed"]

    asyncio.run(scenario())
