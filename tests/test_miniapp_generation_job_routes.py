from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from korgan import miniapp_generation_api as generation_api
from korgan.miniapp_document_payments import DocumentPaymentOrder
from korgan.miniapp_generation_jobs import GenerationJob
from tests.production_routes import owner


@asynccontextmanager
async def _noop_lock(*args, **kwargs):
    yield


def _order(status: str = "approved") -> DocumentPaymentOrder:
    return DocumentPaymentOrder(
        id=501,
        user_key="user-key",
        case_id="case-1",
        case_fingerprint="scope-1",
        document_type="claim",
        language="ru",
        amount_kzt=1000,
        status=status,
        transaction_id="tx-1",
        receipt_check={},
        decision_note="",
    )


def _job(status: str = "queued") -> GenerationJob:
    return GenerationJob(
        id="00000000-0000-0000-0000-000000000501",
        payment_order_id=501,
        user_key="user-key",
        case_id="case-1",
        status=status,
        stage="queued" if status == "queued" else status,
        progress=0 if status != "succeeded" else 100,
        error_detail="",
    )


def _install_identity(monkeypatch, *, case: dict[str, object] | None = None) -> dict[str, object]:
    monkeypatch.setattr(generation_api.settings, "payments_enabled", True)
    monkeypatch.setattr(generation_api.settings, "kaspi_payment_url", "https://pay.korgan.test")
    state: dict[str, object] = {
        "cases": {
            "case-1": case or {
                "id": "case-1",
                "description": "Проверяемые факты",
                "document_type": "claim",
                "language": "ru",
            }
        }
    }
    monkeypatch.setattr(generation_api.core.legacy, "_identity", lambda _raw: "identity")

    async def require_consent(_identity: str):
        return state

    monkeypatch.setattr(generation_api.core.legacy, "_require_consent", require_consent)
    monkeypatch.setattr(generation_api.core.store, "user_key", lambda _identity: "user-key")
    return state


def test_final_app_generation_routes_have_one_outer_owner() -> None:
    assert owner("/miniapp/documents/generate", "POST") == (
        "korgan.miniapp_generation_api.generate_document_job"
    )
    assert owner("/miniapp/documents/generation/{job_id}", "GET") == (
        "korgan.miniapp_generation_api.generation_status"
    )
    assert owner("/miniapp/documents/generation/{job_id}/retry", "POST") == (
        "korgan.miniapp_generation_api.retry_generation"
    )


def test_approved_payment_starts_persisted_job_and_returns_immediately(monkeypatch) -> None:
    _install_identity(monkeypatch)
    order = _order()
    job = _job()
    started: list[str] = []

    async def get_scope_order(**kwargs):
        assert kwargs["user_key"] == "user-key"
        assert kwargs["case_id"] == "case-1"
        return order

    async def create_or_get_job(**kwargs):
        assert kwargs["payment_order_id"] == order.id
        return job

    async def schedule(*args, **kwargs):
        started.append(kwargs["job"].id)

    monkeypatch.setattr(generation_api.document_store, "_require_pool", lambda: object())
    monkeypatch.setattr(generation_api, "payment_operation_lock", _noop_lock)
    monkeypatch.setattr(generation_api.document_store, "get_scope_order", get_scope_order)
    monkeypatch.setattr(generation_api.jobs, "create_or_get_job", create_or_get_job)
    monkeypatch.setattr(generation_api, "_schedule_job", schedule)

    result = asyncio.run(
        generation_api.generate_document_job(
            generation_api.core.GenerateRequest(
                case_id="case-1",
                document_type="claim",
                language="ru",
            ),
            x_telegram_init_data="signed",
        )
    )

    assert result["generation_started"] is True
    assert result["job"]["job_id"] == job.id
    assert result["job"]["status"] == "queued"
    assert "document_base64" not in result
    assert started == [job.id]


def test_duplicate_generate_returns_same_running_job_without_second_schedule(monkeypatch) -> None:
    _install_identity(monkeypatch)
    order = _order()
    running = _job("running")
    schedules: list[str] = []

    async def get_scope_order(**kwargs):
        return order

    async def create_or_get_job(**kwargs):
        return running

    async def schedule(*args, **kwargs):
        schedules.append("unexpected")

    monkeypatch.setattr(generation_api.document_store, "_require_pool", lambda: object())
    monkeypatch.setattr(generation_api, "payment_operation_lock", _noop_lock)
    monkeypatch.setattr(generation_api.document_store, "get_scope_order", get_scope_order)
    monkeypatch.setattr(generation_api.jobs, "create_or_get_job", create_or_get_job)
    monkeypatch.setattr(generation_api, "_schedule_job", schedule)

    result = asyncio.run(
        generation_api.generate_document_job(
            generation_api.core.GenerateRequest(case_id="case-1", document_type="claim", language="ru"),
            x_telegram_init_data="signed",
        )
    )

    assert result["job"]["status"] == "running"
    assert schedules == []


def test_status_is_owner_scoped_and_recovers_ready_case(monkeypatch) -> None:
    state = _install_identity(
        monkeypatch,
        case={
            "id": "case-1",
            "status": "document_ready",
            "title": "Иск",
            "filename": "claim.docx",
            "filing_ready": False,
            "release_status": "preliminary",
            "verification_status": "needs_verification",
            "verification_notes": ["Проверить"],
            "quality_score": 8.0,
            "quality_issues": ["Проверить"],
            "document_base64": "ZmlsZQ==",
        },
    )
    succeeded = _job("succeeded")

    async def require_job(job_id: str, *, user_key: str):
        assert job_id == succeeded.id
        assert user_key == "user-key"
        return succeeded

    monkeypatch.setattr(generation_api.jobs, "require_job", require_job)

    result = asyncio.run(
        generation_api.generation_status(succeeded.id, x_telegram_init_data="signed")
    )

    assert result["job"]["document_ready"] is True
    assert result["document"]["case_id"] == "case-1"
    assert result["document"]["filename"] == "claim.docx"
    assert "document_base64" not in result["document"]
    assert state["cases"]["case-1"]["document_base64"] == "ZmlsZQ=="


def test_failed_job_retry_reuses_payment_and_reschedules_same_job(monkeypatch) -> None:
    _install_identity(monkeypatch)
    failed = _job("failed")
    order = _order()
    reset: list[str] = []
    scheduled: list[str] = []

    async def require_job(job_id: str, *, user_key: str):
        return failed

    async def get_order(order_id: int, *, user_key: str):
        assert order_id == failed.payment_order_id
        return order

    async def reset_failed_job(job_id: str):
        reset.append(job_id)
        return _job("queued")

    async def schedule(*args, **kwargs):
        scheduled.append(kwargs["job"].id)

    monkeypatch.setattr(generation_api.document_store, "_require_pool", lambda: object())
    monkeypatch.setattr(generation_api, "payment_operation_lock", _noop_lock)
    monkeypatch.setattr(generation_api.v5.v4, "_document_scope", lambda *args: order.case_fingerprint)
    monkeypatch.setattr(generation_api.jobs, "require_job", require_job)
    monkeypatch.setattr(generation_api.document_store, "get_document_order", get_order)
    monkeypatch.setattr(generation_api.jobs, "reset_failed_job", reset_failed_job)
    monkeypatch.setattr(generation_api, "_schedule_job", schedule)

    result = asyncio.run(
        generation_api.retry_generation(failed.id, x_telegram_init_data="signed")
    )

    assert result["generation_started"] is True
    assert reset == [failed.id]
    assert scheduled == [failed.id]


def test_process_local_task_registry_prevents_duplicate_worker(monkeypatch) -> None:
    job = _job()
    calls: list[str] = []

    async def scenario() -> None:
        blocker = asyncio.Event()

        async def run_job(started_job, **kwargs):
            calls.append(started_job.id)
            await blocker.wait()

        monkeypatch.setattr(generation_api.jobs, "run_job", run_job)
        generation_api._TASKS.clear()
        await generation_api._schedule_job(
            job=job,
            identity="identity",
            state={"cases": {"case-1": {}}},
            document_type="claim",
            context="Факты",
            language="ru",
        )
        await asyncio.sleep(0)
        await generation_api._schedule_job(
            job=job,
            identity="identity",
            state={"cases": {"case-1": {}}},
            document_type="claim",
            context="Факты",
            language="ru",
        )
        await asyncio.sleep(0.001)
        assert calls == [job.id]
        blocker.set()
        await asyncio.gather(*generation_api._TASKS.values(), return_exceptions=True)
        generation_api._TASKS.clear()

    asyncio.run(scenario())
