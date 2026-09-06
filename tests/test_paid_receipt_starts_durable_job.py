"""Подтверждённый чек запускает сохраняемую задачу, а не работу внутри запроса.

Путь Kaspi ОФД подтверждал оплату и тут же готовил документ прямо в HTTP-запросе:
конвейер занимает около двух минут, поэтому такой запрос жил на грани таймаута
Telegram WebView и прокси. Последствия видел клиент:

* строки задачи не существовало — прогресс показать было нечем, а закрытие
  Mini App теряло работу целиком;
* обрыв запроса выглядел как «Сервис временно недоступен» при списанной оплате;
* ответ не содержал `payment`, хотя экран оплаты именно его и разбирает.

Оплату подтверждает провайдер, а готовит документ одна и та же сохраняемая
задача — та же, что у Tole.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from korgan.miniapp_document_payments import DocumentPaymentOrder


def _order(status: str = "approved") -> DocumentPaymentOrder:
    return DocumentPaymentOrder(
        id=7101,
        user_key="d" * 64,
        case_id="case-receipt",
        case_fingerprint="scope-receipt",
        document_type="claim",
        language="ru",
        amount_kzt=1000,
        status=status,
        transaction_id="tx-7101",
        receipt_check={},
        decision_note="",
    )


def _job(runtime, status: str = "queued") -> object:
    return runtime.jobs.GenerationJob(
        id="33333333-3333-3333-3333-333333333333",
        payment_order_id=7101,
        user_key="d" * 64,
        case_id="case-receipt",
        status=status,
        stage="queued" if status == "queued" else status,
        progress=0,
        error_detail="",
    )


def test_approved_receipt_schedules_the_job_instead_of_generating_inline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import korgan.miniapp_paid_autostart_runtime as runtime

    async def scenario() -> None:
        order, job = _order(), _job(runtime)
        started: list[int] = []
        generated: list[str] = []

        async def start(order_id: int):
            started.append(order_id)
            return job

        async def never_generate(*_args, **_kwargs):
            generated.append("inline")
            raise AssertionError("Оплаченный документ не готовится внутри HTTP-запроса")

        monkeypatch.setattr(runtime, "start_paid_generation", start)
        monkeypatch.setattr(runtime.generation_runtime.core, "generate_document", never_generate)

        result = await runtime._durable_run_approved_document(order, x_telegram_init_data="init")

        assert started == [7101]
        assert generated == []
        assert result["payment_required"] is False
        assert result["generation_started"] is True
        assert result["job"]["job_id"] == job.id
        assert result["job"]["status"] == "queued"
        # Экран оплаты разбирает именно это поле; без него подтверждённый платёж
        # заканчивался сообщением «Получен неполный статус оплаты».
        assert result["payment"]["order_id"] == 7101
        assert result["payment"]["status"] == "approved"

    asyncio.run(scenario())


def test_already_finished_job_is_reported_as_ready_without_a_second_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Повторный чек по той же оплате не запускает вторую подготовку."""
    import korgan.miniapp_paid_autostart_runtime as runtime

    async def scenario() -> None:
        order = _order()
        finished = _job(runtime, status="succeeded")
        calls: list[int] = []

        async def start(order_id: int):
            calls.append(order_id)
            return finished

        monkeypatch.setattr(runtime, "start_paid_generation", start)

        first = await runtime._durable_run_approved_document(order, x_telegram_init_data="init")
        second = await runtime._durable_run_approved_document(order, x_telegram_init_data="init")

        assert first["job"]["status"] == "succeeded"
        assert first["generation_started"] is False
        assert second["job"]["status"] == "succeeded"
        # Планирование идемпотентно на стороне задачи: она уже завершена.
        assert calls == [7101, 7101]

    asyncio.run(scenario())


def test_unschedulable_payment_is_refused_without_consuming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если задачу создать не удалось, оплата остаётся действующей."""
    import korgan.miniapp_paid_autostart_runtime as runtime
    from fastapi import HTTPException

    async def scenario() -> None:
        async def start(order_id: int):
            return None

        monkeypatch.setattr(runtime, "start_paid_generation", start)

        with pytest.raises(HTTPException) as error:
            await runtime._durable_run_approved_document(_order(), x_telegram_init_data="init")

        assert error.value.status_code == 503
        assert "повторно" in str(error.value.detail).lower()

    asyncio.run(scenario())


def test_durable_path_replaces_the_inline_generator_in_the_live_chain() -> None:
    """Слой действительно установлен: чек больше не идёт в синхронную генерацию."""
    import korgan.miniapp_payment_idempotency as idempotency
    import korgan.miniapp_paid_autostart_runtime as runtime

    assert idempotency._ORIGINAL_RUN_APPROVED_DOCUMENT is runtime._durable_run_approved_document


def test_unavailable_job_store_is_reported_as_a_temporary_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Недоступное хранилище задач не превращается в сырую ошибку у клиента.

    Оплата к этому моменту уже подтверждена и сохранена. Клиенту сообщается
    задержка и то, что платить второй раз не нужно; техническая причина
    остаётся в журнале.
    """
    import korgan.miniapp_paid_autostart_runtime as runtime
    from fastapi import HTTPException

    async def scenario() -> None:
        async def broken(order_id: int):
            raise RuntimeError("Mini App generation job store is not initialized")

        monkeypatch.setattr(runtime, "start_paid_generation", broken)

        with pytest.raises(HTTPException) as error:
            await runtime._durable_run_approved_document(_order(), x_telegram_init_data="init")

        assert error.value.status_code == 503
        detail = str(error.value.detail)
        assert "job store" not in detail
        assert "повторно" in detail.lower()

    asyncio.run(scenario())
