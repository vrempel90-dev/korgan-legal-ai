from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from korgan import miniapp_generation_jobs as jobs


class FakeConnection:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[object, ...]] = []
        self.fetchrow_calls: list[tuple[object, ...]] = []
        self.row: dict[str, object] | None = None

    async def execute(self, *args):
        self.execute_calls.append(args)
        return "UPDATE 1"

    async def fetchrow(self, *args):
        self.fetchrow_calls.append(args)
        return self.row


class FakePool(FakeConnection):
    @asynccontextmanager
    async def acquire(self):
        yield self


class FakeStore:
    def __init__(self, state: dict[str, object] | None = None) -> None:
        self.state = state if state is not None else {"cases": {}}
        self.saved: list[tuple[str, dict[str, object]]] = []

    def user_key(self, _identity: str) -> str:
        return "user-key"

    async def load(self, _identity: str) -> dict[str, object]:
        return self.state

    async def save(self, identity: str, state: dict[str, object]) -> None:
        self.saved.append((identity, state))


def test_generation_job_schema_persists_progress_and_unique_payment_order() -> None:
    assert "CREATE TABLE IF NOT EXISTS korgan_miniapp_generation_jobs" in jobs._SCHEMA
    assert "payment_order_id BIGINT" in jobs._SCHEMA
    assert "UNIQUE" in jobs._SCHEMA
    assert "progress INTEGER" in jobs._SCHEMA
    assert "stage TEXT" in jobs._SCHEMA
    assert "error_detail TEXT" in jobs._SCHEMA
    assert "CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))" in jobs._SCHEMA


def test_startup_recovers_interrupted_running_jobs_as_retryable_failures() -> None:
    pool = FakePool()

    asyncio.run(jobs.recover_interrupted_jobs(pool))

    sql = str(pool.execute_calls[0][0])
    assert "status='failed'" in sql
    assert "status IN ('queued', 'running')" in sql
    assert "Сервис перезапустился" in sql


def test_same_payment_order_returns_existing_job_instead_of_duplicate(monkeypatch) -> None:
    pool = FakePool()
    pool.row = {
        "id": "job-1",
        "payment_order_id": 91,
        "user_key": "user-key",
        "case_id": "case-1",
        "status": "running",
        "stage": "legal_research",
        "progress": 25,
        "error_detail": "",
    }
    monkeypatch.setattr(jobs, "_POOL", pool)

    result = asyncio.run(
        jobs.create_or_get_job(
            payment_order_id=91,
            user_key="user-key",
            case_id="case-1",
            case_fingerprint="scope-1",
            document_type="claim",
            language="ru",
        )
    )

    assert result.id == "job-1"
    assert result.status == "running"
    assert len(pool.fetchrow_calls) == 1
    sql = str(pool.fetchrow_calls[0][0])
    assert "ON CONFLICT (payment_order_id) DO UPDATE" in sql


def test_public_job_status_never_reports_ready_before_success() -> None:
    running = jobs.GenerationJob(
        id="job-1",
        payment_order_id=91,
        user_key="user-key",
        case_id="case-1",
        status="running",
        stage="document_render",
        progress=90,
        error_detail="",
    )
    succeeded = jobs.GenerationJob(
        id="job-2",
        payment_order_id=92,
        user_key="user-key",
        case_id="case-2",
        status="succeeded",
        stage="completed",
        progress=100,
        error_detail="",
    )

    assert jobs.public_job(running)["document_ready"] is False
    assert jobs.public_job(running)["progress"] == 90
    assert jobs.public_job(succeeded)["document_ready"] is True


def test_run_job_persists_real_stages_and_marks_success_after_document_save(monkeypatch) -> None:
    pool = FakePool()
    state: dict[str, object] = {"cases": {"case-1": {"id": "case-1"}}}
    store = FakeStore(state)
    job = jobs.GenerationJob(
        id="job-1",
        payment_order_id=91,
        user_key="user-key",
        case_id="case-1",
        status="queued",
        stage="queued",
        progress=0,
        error_detail="",
    )
    stages: list[tuple[str, int]] = []
    consumed: list[int] = []

    async def fake_update(job_id: str, *, status: str, stage: str, progress: int, error_detail: str = ""):
        assert job_id == job.id
        stages.append((stage, progress))

    async def fake_generate(document_type: str, context: str, language: str, *, case_id: str, on_stage):
        assert (document_type, context, language) == ("claim", "Проверяемые факты", "ru")
        assert case_id == "case-1"
        await on_stage("legal_research", 20)
        await on_stage("legal_drafting", 55)
        await on_stage("quality_control", 80)
        await on_stage("document_render", 90)
        return {
            "status": "document_ready",
            "title": "Иск",
            "filename": "claim.docx",
            "document_base64": "ZmlsZQ==",
            "filing_ready": False,
            "release_status": "preliminary",
            "verification_status": "needs_verification",
            "verification_notes": ["Проверить"],
            "quality_score": 8.0,
            "quality_issues": ["Проверить"],
        }

    async def fake_consume(order_id: int, *, user_key: str):
        assert user_key == "user-key"
        consumed.append(order_id)
        return True

    async def fake_claim(job_id: str):
        assert job_id == job.id
        return job

    monkeypatch.setattr(jobs, "_POOL", pool)
    monkeypatch.setattr(jobs, "claim_job", fake_claim)
    monkeypatch.setattr(jobs, "update_job", fake_update)
    monkeypatch.setattr(jobs, "_generate_payload", fake_generate)
    monkeypatch.setattr(jobs.document_store, "consume_document_order", fake_consume)

    asyncio.run(
        jobs.run_job(
            job,
            identity="identity",
            store=store,
            document_type="claim",
            context="Проверяемые факты",
            language="ru",
        )
    )

    assert stages == [
        ("starting", 5),
        ("legal_research", 20),
        ("legal_drafting", 55),
        ("quality_control", 80),
        ("document_render", 90),
        ("completed", 100),
    ]
    assert consumed == [91]
    assert len(store.saved) == 1
    case = state["cases"]["case-1"]
    assert case["document_base64"] == "ZmlsZQ=="
    assert case["status"] == "document_ready"


def test_failed_job_keeps_payment_retryable_and_persists_error(monkeypatch) -> None:
    pool = FakePool()
    store = FakeStore({"cases": {"case-1": {"id": "case-1"}}})
    job = jobs.GenerationJob(
        id="job-1",
        payment_order_id=91,
        user_key="user-key",
        case_id="case-1",
        status="queued",
        stage="queued",
        progress=0,
        error_detail="",
    )
    updates: list[dict[str, object]] = []

    async def fake_update(job_id: str, **values):
        updates.append(values)

    async def fail_generate(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    async def forbidden_consume(*args, **kwargs):
        raise AssertionError("failed generation must not consume payment")

    async def fake_claim(_job_id: str):
        return job

    monkeypatch.setattr(jobs, "claim_job", fake_claim)
    monkeypatch.setattr(jobs, "_POOL", pool)
    monkeypatch.setattr(jobs, "update_job", fake_update)
    monkeypatch.setattr(jobs, "_generate_payload", fail_generate)
    monkeypatch.setattr(jobs.document_store, "consume_document_order", forbidden_consume)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(
            jobs.run_job(
                job,
                identity="identity",
                store=store,
                document_type="claim",
                context="Факты",
                language="ru",
            )
        )

    assert updates[-1]["status"] == "failed"
    assert updates[-1]["stage"] == "failed"
    assert "provider unavailable" in str(updates[-1]["error_detail"])
    assert store.saved == []


def test_job_lookup_is_owner_scoped(monkeypatch) -> None:
    pool = FakePool()
    pool.row = None
    monkeypatch.setattr(jobs, "_POOL", pool)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(jobs.require_job("missing", user_key="other-user"))

    assert exc.value.status_code == 404
    sql = str(pool.fetchrow_calls[0][0])
    assert "id=$1 AND user_key=$2" in sql
