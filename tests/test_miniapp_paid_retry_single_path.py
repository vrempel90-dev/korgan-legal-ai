"""Оплаченный документ готовится ровно одной работой.

Подготовка документа переехала в сохраняемую задачу, но маршрут повторного
запуска по платёжному ордеру остался синхронным: он генерировал документ прямо
в запросе и списывал ту же оплату мимо блокировки задачи. Поэтому повторное
нажатие могло запустить вторую полную генерацию поверх уже идущей — две работы
писали разные документы в одно дело, побеждал последний, а проигравший получал
отказ уже после выполненной работы.

Здесь проверяется противоположное свойство: у оплаченного документа один
исполнитель, и повторный запуск возвращает состояние той же работы.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from korgan import miniapp_generation_api as generation_api
from korgan.miniapp_document_payments import DocumentPaymentOrder
from korgan.miniapp_generation_jobs import GenerationJob
from tests.production_routes import all_routes, owner

# Синхронная генерация внутри HTTP-запроса. Ни один живой маршрут боевого
# приложения не должен вести сюда: работа идёт только через задачу.
_SYNCHRONOUS_GENERATION = {
    "korgan.miniapp_api_v5.retry_paid_document",
    "korgan.miniapp_api_v5.generate_document",
    "korgan.miniapp_api_ofd.document_receipt_url",
}


@asynccontextmanager
async def _noop_lock(*args, **kwargs):
    yield


def _order(status: str = "approved") -> DocumentPaymentOrder:
    return DocumentPaymentOrder(
        id=777,
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


def _job(status: str) -> GenerationJob:
    return GenerationJob(
        id="00000000-0000-0000-0000-000000000777",
        payment_order_id=777,
        user_key="user-key",
        case_id="case-1",
        status=status,
        stage="queued" if status == "queued" else status,
        progress=0,
        error_detail="",
    )


def _install(monkeypatch, *, order: DocumentPaymentOrder | None, job: GenerationJob | None):
    monkeypatch.setattr(generation_api.settings, "payments_enabled", True)
    monkeypatch.setattr(generation_api.settings, "kaspi_payment_url", "https://pay.korgan.test")
    state = {
        "cases": {
            "case-1": {
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

    async def get_document_order(order_id: int, *, user_key: str):
        return order if order is not None and order_id == order.id else None

    async def get_scope_order(**_kwargs):
        return order

    async def latest_job_for_case(**_kwargs):
        return job

    async def deny_synchronous(*_args, **_kwargs):
        raise AssertionError("оплаченный документ пошёл по синхронной генерации")

    monkeypatch.setattr(generation_api.core.legacy, "_require_consent", require_consent)
    monkeypatch.setattr(generation_api.core.store, "user_key", lambda _identity: "user-key")
    monkeypatch.setattr(generation_api.document_store, "_require_pool", lambda: object())
    monkeypatch.setattr(generation_api, "payment_operation_lock", _noop_lock)
    monkeypatch.setattr(generation_api.document_store, "get_document_order", get_document_order)
    monkeypatch.setattr(generation_api.document_store, "get_scope_order", get_scope_order)
    monkeypatch.setattr(generation_api.jobs, "latest_job_for_case", latest_job_for_case)
    monkeypatch.setattr(generation_api.v5.v4, "_document_scope", lambda *args: "scope-1")
    monkeypatch.setattr(generation_api.v5, "_run_approved_document", deny_synchronous)
    return state


def _retry(order_id: int = 777):
    return asyncio.run(
        generation_api.retry_paid_document_job(order_id, x_telegram_init_data="signed")
    )


def test_paid_retry_is_owned_by_the_job_pipeline() -> None:
    assert owner("/miniapp/documents/payments/{order_id}/retry", "POST") == (
        "korgan.miniapp_generation_api.retry_paid_document_job"
    )


def test_no_live_route_generates_a_document_inside_the_request() -> None:
    reachable = set()
    for item in all_routes():
        handler = getattr(item, "endpoint", None)
        if handler is None:
            continue
        reachable.add(f"{handler.__module__}.{handler.__qualname__}")

    assert not (reachable & _SYNCHRONOUS_GENERATION), (
        "у оплаченного документа снова два исполнителя: "
        f"{sorted(reachable & _SYNCHRONOUS_GENERATION)}"
    )


def test_paid_retry_returns_the_running_job_instead_of_starting_a_second_one(monkeypatch) -> None:
    running = _job("running")
    _install(monkeypatch, order=_order(), job=running)
    schedules: list[str] = []

    async def create_or_get_job(**_kwargs):
        return running

    async def schedule(*_args, **kwargs):
        schedules.append(kwargs["job"].id)

    monkeypatch.setattr(generation_api.jobs, "create_or_get_job", create_or_get_job)
    monkeypatch.setattr(generation_api, "_schedule_job", schedule)

    result = _retry()

    assert result["payment_required"] is False
    assert result["job"]["job_id"] == running.id
    assert result["job"]["status"] == "running"
    assert schedules == [], "поверх идущей работы запущена вторая"


def test_paid_retry_restarts_a_failed_job_without_a_second_payment(monkeypatch) -> None:
    failed = _job("failed")
    _install(monkeypatch, order=_order(), job=failed)
    reset: list[str] = []
    scheduled: list[str] = []

    async def require_job(job_id: str, *, user_key: str):
        assert job_id == failed.id
        assert user_key == "user-key"
        return failed

    async def reset_failed_job(job_id: str):
        reset.append(job_id)
        return _job("queued")

    async def schedule(*_args, **kwargs):
        scheduled.append(kwargs["job"].id)

    async def forbidden_order(**_kwargs):
        raise AssertionError("повтор создал второй платёжный запрос")

    monkeypatch.setattr(generation_api.jobs, "require_job", require_job)
    monkeypatch.setattr(generation_api.jobs, "reset_failed_job", reset_failed_job)
    monkeypatch.setattr(generation_api.document_store, "create_document_order", forbidden_order)
    monkeypatch.setattr(generation_api, "_schedule_job", schedule)

    result = _retry()

    assert result["generation_started"] is True
    assert reset == [failed.id]
    assert scheduled == [failed.id]


def test_paid_retry_reports_the_ready_document_instead_of_regenerating(monkeypatch) -> None:
    succeeded = _job("succeeded")
    state = _install(monkeypatch, order=_order("consumed"), job=succeeded)
    state["cases"]["case-1"].update(
        {
            "status": "document_ready",
            "title": "Исковое заявление",
            "filename": "claim.docx",
            "document_base64": "ZmlsZQ==",
        }
    )

    async def forbidden_schedule(*_args, **_kwargs):
        raise AssertionError("готовый документ подготовлен заново")

    monkeypatch.setattr(generation_api, "_schedule_job", forbidden_schedule)

    result = _retry()

    assert result["generation_started"] is False
    assert result["document"]["filename"] == "claim.docx"
    assert "document_base64" not in result["document"]


def test_paid_retry_of_an_unknown_order_is_not_found(monkeypatch) -> None:
    _install(monkeypatch, order=None, job=None)

    with pytest.raises(HTTPException) as failure:
        _retry(999)

    assert failure.value.status_code == 404


def test_paid_retry_does_not_charge_again_when_the_case_materials_changed(monkeypatch) -> None:
    _install(monkeypatch, order=_order(), job=None)
    monkeypatch.setattr(generation_api.v5.v4, "_document_scope", lambda *args: "scope-2")

    async def forbidden_order(**_kwargs):
        raise AssertionError("повтор создал второй платёжный запрос")

    monkeypatch.setattr(generation_api.document_store, "create_document_order", forbidden_order)

    with pytest.raises(HTTPException) as failure:
        _retry()

    assert failure.value.status_code == 409
    assert "не платите" in failure.value.detail
