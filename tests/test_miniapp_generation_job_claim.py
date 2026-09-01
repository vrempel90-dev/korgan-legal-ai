"""Одну задачу подготовки выполняет ровно один исполнитель.

Реестр запущенных задач живёт в памяти процесса, поэтому он различает только
двойное нажатие внутри одного процесса. Обновление с перекрытием старой и новой
версии, вторая реплика или перезапуск во время работы дают то, чего реестр не
видит: две работы над одним оплаченным документом.

Ошибка усиливалась восстановлением при старте. Оно объявляло прерванной любую
незавершённую задачу — в том числе ту, которую прямо сейчас выполняет соседний
процесс. Клиент видел «подготовка не завершилась», нажимал повтор, и вторая
генерация запускалась поверх первой: обе писали документ в одно дело.

Здесь проверяется противоположное: работу начинает тот, кто выиграл переход
`queued -> running` в базе, живая задача о себе сообщает, а прерванной считается
только молчащая.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from korgan import miniapp_generation_jobs as jobs


class FakePool:
    def __init__(self, rows: list[dict[str, object] | None] | None = None) -> None:
        self.execute_calls: list[tuple[object, ...]] = []
        self.fetchrow_calls: list[tuple[object, ...]] = []
        self.rows = list(rows or [])

    async def execute(self, *args):
        self.execute_calls.append(args)
        return "UPDATE 1"

    async def fetchrow(self, *args):
        self.fetchrow_calls.append(args)
        return self.rows.pop(0) if self.rows else None

    @asynccontextmanager
    async def acquire(self):
        yield self


def _row(status: str = "running") -> dict[str, object]:
    return {
        "id": "job-1",
        "payment_order_id": 91,
        "user_key": "user-key",
        "case_id": "case-1",
        "status": status,
        "stage": "queued",
        "progress": 0,
        "error_detail": "",
    }


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


class FakeStore:
    def __init__(self) -> None:
        self.state: dict[str, object] = {"cases": {"case-1": {"id": "case-1"}}}
        self.saved: list[dict[str, object]] = []

    async def load(self, _identity: str) -> dict[str, object]:
        return self.state

    async def save(self, _identity: str, state: dict[str, object]) -> None:
        self.saved.append(state)


def test_claim_takes_the_job_only_out_of_the_queued_state(monkeypatch) -> None:
    pool = FakePool([_row()])
    monkeypatch.setattr(jobs, "_POOL", pool)

    claimed = asyncio.run(jobs.claim_job("job-1"))

    assert claimed is not None
    assert claimed.status == "running"
    sql = str(pool.fetchrow_calls[0][0])
    assert "status='running'" in sql
    assert "status='queued'" in sql, "захват задачи не проверяет прежнее состояние"
    assert "RETURNING" in sql


def test_claim_lost_to_another_worker_returns_nothing(monkeypatch) -> None:
    monkeypatch.setattr(jobs, "_POOL", FakePool([None]))

    assert asyncio.run(jobs.claim_job("job-1")) is None


def test_second_worker_of_the_same_job_does_no_work(monkeypatch) -> None:
    store = FakeStore()
    generated: list[str] = []
    updates: list[str] = []

    async def lost_claim(_job_id: str):
        return None

    async def fake_generate(*_args, **_kwargs):
        generated.append("generate")
        return {}

    async def fake_update(_job_id: str, **values):
        updates.append(str(values.get("status")))

    async def forbidden_consume(*_args, **_kwargs):
        raise AssertionError("проигравший исполнитель списал оплату")

    monkeypatch.setattr(jobs, "claim_job", lost_claim)
    monkeypatch.setattr(jobs, "_generate_payload", fake_generate)
    monkeypatch.setattr(jobs, "update_job", fake_update)
    monkeypatch.setattr(jobs.document_store, "consume_document_order", forbidden_consume)

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

    assert generated == [], "вторая генерация запущена поверх уже идущей"
    assert updates == [], "проигравший исполнитель переписал состояние чужой задачи"
    assert store.saved == []


def test_running_job_reports_that_it_is_alive(monkeypatch) -> None:
    """Долгая стадия не должна выглядеть молчанием упавшего процесса."""
    beats: list[str] = []
    store = FakeStore()

    async def fake_claim(_job_id: str):
        return _job("running")

    async def fake_touch(job_id: str):
        beats.append(job_id)

    async def slow_generate(*_args, **kwargs):
        await kwargs["on_stage"]("legal_research", 20)
        for _ in range(40):
            await asyncio.sleep(0)
            if beats:
                break
        return {
            "status": "document_ready",
            "title": "Иск",
            "filename": "claim.docx",
            "document_base64": "ZmlsZQ==",
            "filing_ready": False,
            "release_status": "preliminary",
            "verification_status": "needs_verification",
            "verification_notes": [],
            "quality_score": 8.0,
            "quality_issues": [],
        }

    async def fake_update(_job_id: str, **_values):
        return None

    async def fake_consume(_order_id: int, *, user_key: str):
        return True

    monkeypatch.setattr(jobs, "claim_job", fake_claim)
    monkeypatch.setattr(jobs, "touch_job", fake_touch)
    monkeypatch.setattr(jobs, "_HEARTBEAT_SECONDS", 0)
    monkeypatch.setattr(jobs, "_generate_payload", slow_generate)
    monkeypatch.setattr(jobs, "update_job", fake_update)
    monkeypatch.setattr(jobs.document_store, "consume_document_order", fake_consume)

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

    assert beats, "задача не сообщает, что жива"
    assert len(store.saved) == 1


def test_heartbeat_only_touches_a_job_that_is_still_running(monkeypatch) -> None:
    pool = FakePool()
    monkeypatch.setattr(jobs, "_POOL", pool)

    asyncio.run(jobs.touch_job("job-1"))

    sql = str(pool.execute_calls[0][0])
    assert "updated_at=NOW()" in sql
    assert "status='running'" in sql
    assert "stage" not in sql, "признак жизни не должен переписывать стадию"


def test_recovery_spares_a_job_that_is_still_reporting(monkeypatch) -> None:
    pool = FakePool()

    asyncio.run(jobs.recover_interrupted_jobs(pool))

    sql = str(pool.execute_calls[0][0])
    assert "status IN ('queued', 'running')" in sql
    assert "updated_at <" in sql, "восстановление объявляет прерванной живую задачу"
    assert jobs._LEASE_SECONDS in pool.execute_calls[0]
    assert jobs._LEASE_SECONDS > jobs._HEARTBEAT_SECONDS * 2
