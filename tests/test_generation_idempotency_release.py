"""Повтор не должен стоить второй оплаты, второго документа и второго исполнителя.

Клиент нажимает повтор именно тогда, когда что-то пошло не так, — и это самый
опасный момент: две генерации, пишущие в одно дело, дают документ-победитель и
проигравшего, а второе списание оплаты за уже оплаченную работу клиент замечает
сразу.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from korgan import miniapp_generation_api as api
from korgan import miniapp_generation_jobs as jobs


class _Pool:
    @asynccontextmanager
    async def acquire(self):
        yield self

    async def execute(self, *args):
        return "UPDATE 1"

    async def fetchrow(self, *args):
        return None


class _Store:
    def __init__(self) -> None:
        self.state = {"cases": {"case-1": {"id": "case-1"}}}
        self.saves = 0

    def user_key(self, _identity: str) -> str:
        return "user-key"

    async def load(self, _identity: str):
        return self.state

    async def save(self, _identity: str, state) -> None:
        self.saves += 1
        self.state = state


def _job(status: str = "queued") -> jobs.GenerationJob:
    return jobs.GenerationJob(
        id="job-1",
        payment_order_id=91,
        user_key="user-key",
        case_id="case-1",
        status=status,
        stage="queued",
        progress=0,
        error_detail="",
    )


def test_second_worker_never_starts_the_same_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """Переход состояния в базе выигрывает ровно один исполнитель."""
    claimed: list[str] = []
    generated: list[str] = []

    async def fake_claim(job_id: str):
        if job_id in claimed:
            return None
        claimed.append(job_id)
        return _job("running")

    async def fake_update(*_args, **_kwargs):
        return None

    async def fake_generate(*_args, **kwargs):
        generated.append("run")
        return {
            "status": "document_ready",
            "filename": "claim.docx",
            "document_base64": "ZmlsZQ==",
        }

    async def fake_consume(order_id: int, *, user_key: str) -> bool:
        return True

    monkeypatch.setattr(jobs, "_POOL", _Pool())
    monkeypatch.setattr(jobs, "claim_job", fake_claim)
    monkeypatch.setattr(jobs, "update_job", fake_update)
    monkeypatch.setattr(jobs, "_generate_payload", fake_generate)
    monkeypatch.setattr(jobs.document_store, "consume_document_order", fake_consume)

    store = _Store()

    async def race() -> None:
        await asyncio.gather(
            jobs.run_job(_job(), identity="i", store=store, document_type="claim", context="ф", language="ru"),
            jobs.run_job(_job(), identity="i", store=store, document_type="claim", context="ф", language="ru"),
        )

    asyncio.run(race())
    assert generated == ["run"], "документ подготовлен дважды"
    assert store.saves == 1, "дело сохранено дважды"


def test_payment_is_consumed_once_even_if_publication_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """Уже списанный ордер этой же задачи — основание продолжить, а не платить снова."""
    consumed: list[int] = []

    async def fake_consume(order_id: int, *, user_key: str) -> bool:
        consumed.append(order_id)
        return False  # ордер уже списан ранее

    class _Order:
        status = "consumed"

    async def fake_get(order_id: int, *, user_key: str):
        return _Order()

    monkeypatch.setattr(jobs.document_store, "consume_document_order", fake_consume)
    monkeypatch.setattr(jobs.document_store, "get_document_order", fake_get)

    asyncio.run(jobs._claim_payment(_job("running")))
    assert consumed == [91], "повторное списание оплаты"


def test_missing_payment_fails_with_a_message_that_forbids_paying_again(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_consume(order_id: int, *, user_key: str) -> bool:
        return False

    async def fake_get(order_id: int, *, user_key: str):
        return None

    monkeypatch.setattr(jobs.document_store, "consume_document_order", fake_consume)
    monkeypatch.setattr(jobs.document_store, "get_document_order", fake_get)

    with pytest.raises(jobs.GenerationFailure) as failure:
        asyncio.run(jobs._claim_payment(_job("running")))
    assert "Повторно не платите" in str(failure.value)


def test_scheduling_the_same_job_twice_creates_one_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Двойное нажатие в одном процессе не порождает второго исполнителя."""
    started: list[str] = []

    async def fake_run(job, **_kwargs):
        started.append(job.id)
        await asyncio.sleep(0.05)

    monkeypatch.setattr(jobs, "run_job", fake_run)
    api._TASKS.clear()

    async def scenario() -> None:
        job = _job()
        await api._schedule_job(job=job, identity="i", document_type="claim", context="ф", language="ru")
        await api._schedule_job(job=job, identity="i", document_type="claim", context="ф", language="ru")
        task = api._TASKS.get(job.id)
        if task is not None:
            await task

    asyncio.run(scenario())
    assert started == ["job-1"], started
    api._TASKS.clear()


def test_failed_job_is_reset_instead_of_creating_a_new_one() -> None:
    """Повтор после сбоя продолжает ту же задачу и тот же оплаченный ордер.

    Новая задача означала бы новый ордер, а новый ордер — вторую оплату за уже
    оплаченную работу. Поэтому повтор — это переход состояния существующей
    строки, разрешённый только упавшей задаче: идущую он не трогает.
    """
    import inspect

    body = inspect.getsource(jobs.reset_failed_job)
    assert "WHERE id=$1 AND status='failed'" in body
    assert "INSERT" not in body


def test_one_payment_order_can_hold_only_one_job() -> None:
    """Уникальность ордера в схеме и есть защита от второй задачи за ту же оплату."""
    assert "payment_order_id BIGINT NOT NULL UNIQUE" in jobs._SCHEMA
    import inspect

    body = inspect.getsource(jobs.create_or_get_job)
    assert "ON CONFLICT (payment_order_id) DO UPDATE" in body
