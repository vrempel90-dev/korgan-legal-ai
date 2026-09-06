"""Полный путь клиента: оплата → задача → реальный прогресс → готовый документ.

Проверяется то, ради чего существует вся цепочка, и ровно теми переходами,
которые происходят в production: подтверждение оплаты планирует одну
сохраняемую задачу, конвейер сообщает свои фактические стадии, строка задачи
двигается только вперёд, а завершённая задача остаётся завершённой.

Платёжный провайдер здесь не нужен: подтверждение оплаты воспроизводится тем же
переходом состояния ордера, каким его делает webhook Tole и проверенный
фискальный чек. Хранилище задач — в памяти, но контракт у него тот же, что у
таблицы: уникальность по ордеру, переход `queued -> running` как захват работы
и запрет двигать прогресс назад.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from korgan import generation_progress as progress
from korgan.miniapp_document_payments import DocumentPaymentOrder


class FakeJobStore:
    """Строки задач в памяти с теми же инвариантами, что и в таблице."""

    def __init__(self) -> None:
        self.rows: dict[str, SimpleNamespace] = {}
        self.by_order: dict[int, str] = {}
        self.inserts = 0

    def _job(self, row: SimpleNamespace):
        from korgan.miniapp_generation_jobs import GenerationJob

        return GenerationJob(
            id=row.id,
            payment_order_id=row.payment_order_id,
            user_key=row.user_key,
            case_id=row.case_id,
            status=row.status,
            stage=row.stage,
            progress=row.progress,
            error_detail=row.error_detail,
        )

    async def create_or_get_job(self, **kwargs):
        order_id = int(kwargs["payment_order_id"])
        # UNIQUE(payment_order_id): один оплаченный заказ — одна задача.
        existing = self.by_order.get(order_id)
        if existing is not None:
            return self._job(self.rows[existing])
        self.inserts += 1
        job_id = f"job-{order_id}"
        self.rows[job_id] = SimpleNamespace(
            id=job_id,
            payment_order_id=order_id,
            user_key=kwargs["user_key"],
            case_id=kwargs["case_id"],
            status="queued",
            stage="queued",
            progress=0,
            error_detail="",
        )
        self.by_order[order_id] = job_id
        return self._job(self.rows[job_id])

    async def claim_job(self, job_id: str):
        row = self.rows.get(job_id)
        # Переход queued -> running и есть захват работы: второй запуск уходит.
        if row is None or row.status != "queued":
            return None
        row.status = "running"
        return self._job(row)

    async def update_job(self, job_id: str, *, status: str, stage: str, progress: int, error_detail: str = ""):
        row = self.rows[job_id]
        row.status, row.stage, row.progress, row.error_detail = status, stage, progress, error_detail

    async def advance_stage(self, job_id: str, *, stage: str, progress_value: int):
        row = self.rows[job_id]
        # Полоса не едет назад: работа назад не идёт.
        if row.status == "running" and row.progress < progress_value:
            row.stage, row.progress = stage, progress_value

    async def require_job(self, job_id: str, *, user_key: str):
        return self._job(self.rows[job_id])

    async def latest_job_for_case(self, *, user_key: str, case_id: str, case_fingerprint: str | None = None):
        for row in self.rows.values():
            if row.user_key == user_key and row.case_id == case_id:
                return self._job(row)
        return None


def _order(status: str = "approved") -> DocumentPaymentOrder:
    return DocumentPaymentOrder(
        id=5001,
        user_key="e" * 64,
        case_id="case-e2e",
        case_fingerprint="scope-e2e",
        document_type="claim",
        language="ru",
        amount_kzt=1000,
        status=status,
        transaction_id="tx-5001",
        receipt_check={},
        decision_note="",
    )


@pytest.fixture()
def flow(monkeypatch: pytest.MonkeyPatch):
    import korgan.miniapp_paid_autostart_runtime as runtime

    runtime._AUTO_TASKS.clear()
    store = FakeJobStore()
    order_status = {"value": "approved"}
    ai_calls: list[str] = []
    state = {
        "consent": True,
        "cases": {"case-e2e": {"document_type": "claim", "language": "ru", "description": "факты дела"}},
    }
    saved_states: list[dict] = []

    async def get_order(order_id: int, **_kwargs):
        return _order(order_status["value"])

    async def load_state(user_key: str):
        return state

    async def save_state(user_key: str, value):
        saved_states.append(value)

    async def claim_payment(_job):
        order_status["value"] = "consumed"

    async def heartbeat(_job_id):
        await asyncio.sleep(3600)

    async def pipeline(document_type, context, language, *, case_id, report_stage=None):
        ai_calls.append(case_id)
        # Конвейер сообщает свои фактические границы — те же, что в production.
        for stage in progress.STAGE_ORDER[1:-1]:
            report_stage(stage, progress.progress_for(stage))
            await asyncio.sleep(0)
        return {
            "status": "document_ready",
            "title": "Исковое заявление",
            "filename": "claim.docx",
            "document_base64": "ZHVtbXk=",
            "filing_ready": True,
        }

    for name in ("create_or_get_job", "claim_job", "update_job", "advance_stage", "require_job", "latest_job_for_case"):
        monkeypatch.setattr(runtime.jobs, name, getattr(store, name))
    monkeypatch.setattr(runtime.jobs, "_heartbeat", heartbeat)
    monkeypatch.setattr(runtime.jobs, "_claim_payment", claim_payment)
    monkeypatch.setattr(runtime.jobs, "_generate_payload", pipeline)
    monkeypatch.setattr(runtime.document_store, "get_document_order", get_order)
    monkeypatch.setattr(runtime.generation_runtime.core.store, "load_by_user_key", load_state)
    monkeypatch.setattr(runtime.generation_runtime.core.store, "save_by_user_key", save_state)
    monkeypatch.setattr(runtime.v5.v4, "_document_scope", lambda *_a, **_k: "scope-e2e")
    monkeypatch.setattr(runtime.generation_runtime.core, "_case_context", lambda case: "материалы дела")

    return SimpleNamespace(
        runtime=runtime,
        store=store,
        ai_calls=ai_calls,
        state=state,
        saved_states=saved_states,
        order_status=order_status,
    )


async def _settle(runtime) -> None:
    await asyncio.gather(*list(runtime._AUTO_TASKS.values()), return_exceptions=True)
    await asyncio.sleep(0)


def test_confirmed_payment_produces_one_document_through_real_stages(flow) -> None:
    async def scenario() -> None:
        seen: list[tuple[str, int]] = []
        original = flow.store.advance_stage

        async def spy(job_id: str, *, stage: str, progress_value: int):
            await original(job_id, stage=stage, progress_value=progress_value)
            seen.append((flow.store.rows[job_id].stage, flow.store.rows[job_id].progress))

        flow.runtime.jobs.advance_stage = spy

        job = await flow.runtime.start_paid_generation(5001)
        assert job.status == "queued"
        await _settle(flow.runtime)

        # Один платёж — одна задача, один вызов конвейера, один документ.
        assert flow.store.inserts == 1
        assert flow.ai_calls == ["case-e2e"]
        assert len(flow.saved_states) == 1

        row = flow.store.rows["job-5001"]
        assert (row.status, row.stage, row.progress) == ("succeeded", "completed", 100)
        assert flow.order_status["value"] == "consumed"
        assert flow.state["cases"]["case-e2e"]["filename"] == "claim.docx"

        # Прогресс шёл по фактическим стадиям конвейера и только вперёд.
        assert [stage for stage, _ in seen] == list(progress.STAGE_ORDER[1:-1])
        values = [value for _, value in seen]
        assert values == sorted(values)
        assert values[0] >= progress.progress_for(progress.LEGAL_RESEARCH)

    asyncio.run(scenario())


def test_duplicate_confirmation_never_starts_a_second_generation(flow) -> None:
    """Повторный webhook, повторный чек и обновление экрана — одна задача."""

    async def scenario() -> None:
        await flow.runtime.start_paid_generation(5001)
        await flow.runtime.start_paid_generation(5001)
        await _settle(flow.runtime)
        await flow.runtime.start_paid_generation(5001)
        await _settle(flow.runtime)

        assert flow.store.inserts == 1
        assert flow.ai_calls == ["case-e2e"]
        assert len(flow.saved_states) == 1

    asyncio.run(scenario())


def test_completed_job_stays_completed_on_reopen(flow) -> None:
    """Повторное открытие завершённого дела не возвращает его в подготовку."""

    async def scenario() -> None:
        await flow.runtime.start_paid_generation(5001)
        await _settle(flow.runtime)

        reopened = await flow.runtime.start_paid_generation(5001)
        await _settle(flow.runtime)

        assert reopened.status == "succeeded"
        assert reopened.progress == 100
        assert flow.ai_calls == ["case-e2e"]

        from korgan.miniapp_generation_jobs import public_job

        payload = public_job(reopened)
        assert payload["document_ready"] is True
        assert payload["retryable"] is False
        assert payload["error"] == ""

    asyncio.run(scenario())


def test_generation_runs_without_the_client_returning_to_telegram(flow) -> None:
    """Подготовка не ждёт ни возврата человека, ни подписи Telegram."""

    async def scenario() -> None:
        # Ни один шаг ниже не получает initData: путь идёт по ключу из ордера.
        await flow.runtime.start_paid_generation(5001)
        await _settle(flow.runtime)

        assert flow.store.rows["job-5001"].status == "succeeded"
        assert flow.state["cases"]["case-e2e"]["status"] == "document_ready"

    asyncio.run(scenario())


def test_failed_generation_is_retryable_without_a_second_payment(flow) -> None:
    async def scenario() -> None:
        async def failing(document_type, context, language, *, case_id, report_stage=None):
            report_stage(progress.LEGAL_RESEARCH, progress.progress_for(progress.LEGAL_RESEARCH))
            await asyncio.sleep(0)
            raise RuntimeError("Error code: 500 upstream")

        flow.runtime.jobs._generate_payload = failing

        await flow.runtime.start_paid_generation(5001)
        await _settle(flow.runtime)

        row = flow.store.rows["job-5001"]
        assert row.status == "failed"
        # Оплата не израсходована: повтор не потребует второго платежа.
        assert flow.order_status["value"] == "approved"
        # Технический текст провайдера клиенту не показывается.
        assert "500" not in row.error_detail
        assert "повтор" in row.error_detail.lower()

    asyncio.run(scenario())
