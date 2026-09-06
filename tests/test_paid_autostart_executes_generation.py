"""Автозапуск после оплаты действительно доходит до конвейера.

Существующий набор подменял `_run_paid_job` целиком и проверял только, что
задача запланирована. Внутрь подменённой функции никто не заходил, поэтому
несовпадение имени параметра в вызове юридического конвейера жило незамеченным:
каждый автозапуск после подтверждённой оплаты падал первым же вызовом, задача
переводилась в `failed`, и клиент, уже заплативший, видел «Сервис временно не
смог завершить подготовку документа».

Здесь подменяется только сам конвейер, а весь путь задачи — настоящий.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def _order() -> SimpleNamespace:
    return SimpleNamespace(
        id=8801,
        user_key="c" * 64,
        case_id="case-autostart",
        case_fingerprint="scope-autostart",
        document_type="claim",
        language="ru",
        status="approved",
    )


def _job(runtime) -> object:
    return runtime.jobs.GenerationJob(
        id="22222222-2222-2222-2222-222222222222",
        payment_order_id=8801,
        user_key="c" * 64,
        case_id="case-autostart",
        status="queued",
        stage="queued",
        progress=0,
        error_detail="",
    )


def _install_common(monkeypatch: pytest.MonkeyPatch, runtime, *, updates: list, order, job) -> dict:
    state = {
        "consent": True,
        "cases": {"case-autostart": {"document_type": "claim", "language": "ru", "description": "факты"}},
    }
    saved: dict = {}

    async def get_order(order_id: int, **_kwargs):
        return order

    async def create_job(**_kwargs):
        return job

    async def claim_job(job_id: str):
        return job

    async def update_job(job_id: str, **kwargs):
        updates.append(kwargs)

    async def load_state(user_key: str):
        return state

    async def save_state(user_key: str, value):
        saved["state"] = value

    async def claim_payment(_job):
        return None

    async def heartbeat(_job_id):
        await asyncio.sleep(3600)

    monkeypatch.setattr(runtime.document_store, "get_document_order", get_order)
    monkeypatch.setattr(runtime.jobs, "create_or_get_job", create_job)
    monkeypatch.setattr(runtime.jobs, "claim_job", claim_job)
    monkeypatch.setattr(runtime.jobs, "update_job", update_job)
    monkeypatch.setattr(runtime.jobs, "_claim_payment", claim_payment)
    monkeypatch.setattr(runtime.jobs, "_heartbeat", heartbeat)
    monkeypatch.setattr(runtime.generation_runtime.core.store, "load_by_user_key", load_state)
    monkeypatch.setattr(runtime.generation_runtime.core.store, "save_by_user_key", save_state)
    monkeypatch.setattr(runtime.v5.v4, "_document_scope", lambda *_a, **_k: "scope-autostart")
    monkeypatch.setattr(runtime.generation_runtime.core, "_case_context", lambda case: "материалы дела")
    return saved


def test_paid_autostart_reaches_the_pipeline_and_completes(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.miniapp_paid_autostart_runtime as runtime

    async def scenario() -> None:
        runtime._AUTO_TASKS.clear()
        order, job = _order(), _job(runtime)
        updates: list = []
        saved = _install_common(monkeypatch, runtime, updates=updates, order=order, job=job)
        seen: dict = {}

        async def fake_payload(document_type, context, language, *, case_id, report_stage=None):
            seen["args"] = (document_type, context, language, case_id)
            seen["reporter"] = report_stage
            if report_stage is not None:
                report_stage("legal_research", 15)
            return {"status": "document_ready", "filename": "claim.docx", "title": "Исковое заявление"}

        monkeypatch.setattr(runtime.jobs, "_generate_payload", fake_payload)

        await runtime.start_paid_generation(8801)
        await asyncio.gather(*list(runtime._AUTO_TASKS.values()), return_exceptions=True)

        assert seen["args"] == ("claim", "материалы дела", "ru", "case-autostart")
        assert saved["state"]["cases"]["case-autostart"]["filename"] == "claim.docx"

    asyncio.run(scenario())


def test_paid_autostart_marks_the_job_succeeded(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.miniapp_paid_autostart_runtime as runtime

    async def scenario() -> None:
        runtime._AUTO_TASKS.clear()
        order, job = _order(), _job(runtime)
        updates: list = []
        _install_common(monkeypatch, runtime, updates=updates, order=order, job=job)

        async def fake_payload(document_type, context, language, *, case_id, report_stage=None):
            return {"status": "document_ready", "filename": "claim.docx"}

        monkeypatch.setattr(runtime.jobs, "_generate_payload", fake_payload)

        await runtime.start_paid_generation(8801)
        await asyncio.gather(*list(runtime._AUTO_TASKS.values()), return_exceptions=True)

        assert [item["status"] for item in updates][-1] == "succeeded"
        assert not any(item["status"] == "failed" for item in updates)

    asyncio.run(scenario())


def test_pipeline_stage_reports_move_the_job_forward(monkeypatch: pytest.MonkeyPatch) -> None:
    """Стадия, о которой сообщил конвейер, доходит до строки задачи.

    Синхронный приёмник обязателен: конвейер зовёт его обычным вызовом, и
    корутина, никем не ожидаемая, оставила бы полосу на месте.
    """
    import korgan.miniapp_paid_autostart_runtime as runtime

    async def scenario() -> None:
        runtime._AUTO_TASKS.clear()
        order, job = _order(), _job(runtime)
        updates: list = []
        _install_common(monkeypatch, runtime, updates=updates, order=order, job=job)
        advanced: list[tuple[str, int]] = []

        async def advance_stage(job_id: str, *, stage: str, progress_value: int):
            advanced.append((stage, progress_value))

        monkeypatch.setattr(runtime.jobs, "advance_stage", advance_stage)

        async def fake_payload(document_type, context, language, *, case_id, report_stage=None):
            assert report_stage is not None
            assert not asyncio.iscoroutinefunction(report_stage)
            report_stage("legal_research", 15)
            report_stage("drafting", 45)
            return {"status": "document_ready", "filename": "claim.docx"}

        monkeypatch.setattr(runtime.jobs, "_generate_payload", fake_payload)

        await runtime.start_paid_generation(8801)
        await asyncio.gather(*list(runtime._AUTO_TASKS.values()), return_exceptions=True)
        await asyncio.sleep(0)

        assert ("legal_research", 15) in advanced
        assert ("drafting", 45) in advanced

    asyncio.run(scenario())
