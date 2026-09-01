"""Документ появляется в деле только после того, как задача действительно дошла.

Две ошибки видны только на длинной задаче и обе стоят денег. Первая: документ
сохранялся в дело до списания оплаты, поэтому в окне между сохранением и
списанием обычный запрос дела уже отдавал файл, а задача ещё могла упасть —
клиент видел готовность, которой не было. Вторая: задача сохраняла тот снимок
состояния, который был на момент HTTP-запроса, и затирала всё, что
пользователь успел сделать за минуту подготовки, включая удаление дела.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from korgan import miniapp_generation_jobs as jobs


class RecordingStore:
    """Хранилище, которое помнит порядок обращений и отдаёт свежее состояние."""

    def __init__(self, state: dict[str, object], log: list[str]) -> None:
        self.state = state
        self.log = log
        self.saved: list[dict[str, object]] = []

    async def load(self, _identity: str) -> dict[str, object]:
        self.log.append("load")
        return self.state

    async def save(self, _identity: str, state: dict[str, object]) -> None:
        self.log.append("save")
        self.saved.append(state)


def _job() -> jobs.GenerationJob:
    return jobs.GenerationJob(
        id="job-1",
        payment_order_id=91,
        user_key="user-key",
        case_id="case-1",
        status="queued",
        stage="queued",
        progress=0,
        error_detail="",
    )


_RESULT = {
    "status": "document_ready",
    "title": "Иск",
    "filename": "claim.docx",
    "document_base64": "ZmlsZQ==",
    "filing_ready": True,
    "release_status": "verified",
    "verification_status": "verified",
    "verification_notes": [],
    "quality_score": 9.1,
    "quality_issues": [],
}


def _install(monkeypatch, *, log: list[str], consume: bool, order_status: str = "approved"):
    async def fake_claim(_job_id: str):
        # Работу начинает только выигравший переход `queued -> running`.
        log.append("claim")
        return _job()

    async def fake_update(_job_id: str, **values):
        log.append(f"update:{values.get('status')}")

    async def fake_generate(*args, **kwargs):
        log.append("generate")
        return dict(_RESULT)

    async def fake_consume(order_id: int, *, user_key: str):
        assert (order_id, user_key) == (91, "user-key")
        log.append("consume")
        return consume

    async def fake_order(order_id: int, *, user_key: str | None = None):
        log.append("order")
        return SimpleNamespace(id=order_id, status=order_status, user_key="user-key")

    monkeypatch.setattr(jobs, "claim_job", fake_claim)
    monkeypatch.setattr(jobs, "update_job", fake_update)
    monkeypatch.setattr(jobs, "_generate_payload", fake_generate)
    monkeypatch.setattr(jobs.document_store, "consume_document_order", fake_consume)
    monkeypatch.setattr(jobs.document_store, "get_document_order", fake_order)


def _run(store: RecordingStore) -> None:
    asyncio.run(
        jobs.run_job(
            _job(),
            identity="identity",
            store=store,
            document_type="claim",
            context="Проверяемые факты",
            language="ru",
        )
    )


def test_payment_is_claimed_before_the_document_becomes_visible(monkeypatch) -> None:
    log: list[str] = []
    _install(monkeypatch, log=log, consume=True)
    store = RecordingStore({"cases": {"case-1": {"id": "case-1"}}}, log)

    _run(store)

    assert log[0] == "claim", "работа началась до захвата задачи"
    assert log.index("consume") < log.index("save")
    assert log.index("save") < log.index("update:succeeded")
    assert store.saved[-1]["cases"]["case-1"]["document_base64"] == "ZmlsZQ=="


def test_worker_publishes_into_freshly_loaded_state(monkeypatch) -> None:
    """За минуту подготовки пользователь успел добавить материал."""
    log: list[str] = []
    _install(monkeypatch, log=log, consume=True)
    fresh = {
        "cases": {
            "case-1": {"id": "case-1", "materials_count": 3},
            "case-2": {"id": "case-2"},
        }
    }
    store = RecordingStore(fresh, log)

    _run(store)

    saved_case = store.saved[-1]["cases"]["case-1"]
    assert saved_case["materials_count"] == 3
    assert saved_case["document_base64"] == "ZmlsZQ=="
    assert "case-2" in store.saved[-1]["cases"]


def test_case_deleted_during_preparation_is_not_resurrected(monkeypatch) -> None:
    log: list[str] = []
    _install(monkeypatch, log=log, consume=True)
    store = RecordingStore({"cases": {}}, log)

    with pytest.raises(RuntimeError):
        _run(store)

    assert store.saved == []
    assert log[-1] == "update:failed"


def test_lost_payment_fails_the_job_without_publishing_the_document(monkeypatch) -> None:
    log: list[str] = []
    _install(monkeypatch, log=log, consume=False, order_status="cancelled")
    store = RecordingStore({"cases": {"case-1": {"id": "case-1"}}}, log)

    with pytest.raises(RuntimeError):
        _run(store)

    assert store.saved == []
    assert "document_base64" not in store.state["cases"]["case-1"]


def test_repeat_of_a_job_whose_payment_was_already_claimed_completes(monkeypatch) -> None:
    """Повтор после сбоя публикации не требует второй оплаты."""
    log: list[str] = []
    _install(monkeypatch, log=log, consume=False, order_status="consumed")
    store = RecordingStore({"cases": {"case-1": {"id": "case-1"}}}, log)

    _run(store)

    assert log[-1] == "update:succeeded"
    assert store.saved[-1]["cases"]["case-1"]["document_base64"] == "ZmlsZQ=="
