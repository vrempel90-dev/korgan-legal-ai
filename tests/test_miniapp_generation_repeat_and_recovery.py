"""Готовый документ не оплачивается второй раз, а начатая подготовка находится после перезапуска.

Два дефекта одного корня: единственным следом задачи для клиента был `job_id`,
выданный в ответ на запуск. Хранилище платёжных ордеров после списания оплаты
переводит ордер в `consumed`, а поиск действующего ордера по делу такие ордера
не видит. Поэтому повторное нажатие «Подготовить документ» на уже готовом деле
создавало новый ордер и просило клиента заплатить второй раз за то, что у него
уже есть. По той же причине закрытие Mini App во время подготовки теряло
`job_id` навсегда: при повторном открытии клиенту нечего было опросить.

Обе ситуации закрываются одним запросом — последней задачей по делу.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from korgan import miniapp_generation_api as generation_api
from korgan import miniapp_generation_jobs as jobs
from korgan.miniapp_document_payments import DocumentPaymentOrder
from korgan.miniapp_generation_jobs import GenerationJob
from tests.production_routes import owner


@asynccontextmanager
async def _noop_lock(*args, **kwargs):
    yield


class FakePool:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self.row = row
        self.fetchrow_calls: list[tuple[object, ...]] = []

    async def fetchrow(self, *args):
        self.fetchrow_calls.append(args)
        return self.row


READY_CASE: dict[str, object] = {
    "id": "case-1",
    "description": "Проверяемые факты",
    "document_type": "claim",
    "language": "ru",
    "status": "document_ready",
    "title": "Исковое заявление",
    "filename": "claim.docx",
    "filing_ready": False,
    "release_status": "preliminary",
    "verification_status": "needs_verification",
    "verification_notes": ["Проверить госпошлину"],
    "quality_score": 8.4,
    "quality_issues": ["Указать банковские реквизиты"],
    "document_base64": "ZmlsZQ==",
}


def _job(status: str, *, case_id: str = "case-1") -> GenerationJob:
    return GenerationJob(
        id="00000000-0000-0000-0000-000000000501",
        payment_order_id=501,
        user_key="user-key",
        case_id=case_id,
        status=status,
        stage="completed" if status == "succeeded" else status,
        progress=100 if status == "succeeded" else 40,
        error_detail="",
    )


def _install_identity(monkeypatch, *, case: dict[str, object] | None = None) -> dict[str, object]:
    monkeypatch.setattr(generation_api.settings, "payments_enabled", True)
    monkeypatch.setattr(generation_api.settings, "kaspi_payment_url", "https://pay.korgan.test")
    state: dict[str, object] = {
        "cases": {
            "case-1": dict(case if case is not None else {
                "id": "case-1",
                "description": "Проверяемые факты",
                "document_type": "claim",
                "language": "ru",
            })
        }
    }
    monkeypatch.setattr(generation_api.core.legacy, "_identity", lambda _raw: "identity")

    async def require_consent(_identity: str):
        return state

    monkeypatch.setattr(generation_api.core.legacy, "_require_consent", require_consent)
    monkeypatch.setattr(generation_api.core.store, "user_key", lambda _identity: "user-key")
    return state


def _forbid_payment_store(monkeypatch, *, created: list[str], scope_lookups: list[str]) -> None:
    async def get_scope_order(**kwargs):
        scope_lookups.append(str(kwargs.get("case_id")))
        return None

    async def create_document_order(**kwargs):
        created.append(str(kwargs.get("case_id")))
        return DocumentPaymentOrder(
            id=777,
            user_key="user-key",
            case_id="case-1",
            case_fingerprint="scope-2",
            document_type="claim",
            language="ru",
            amount_kzt=1000,
            status="pending_receipt",
            transaction_id="tx-2",
            receipt_check={},
            decision_note="",
        )

    monkeypatch.setattr(generation_api.document_store, "_require_pool", lambda: object())
    monkeypatch.setattr(generation_api, "payment_operation_lock", _noop_lock)
    monkeypatch.setattr(generation_api.document_store, "get_scope_order", get_scope_order)
    monkeypatch.setattr(generation_api.document_store, "create_document_order", create_document_order)


def test_latest_job_for_case_is_owner_scoped_and_takes_the_newest(monkeypatch) -> None:
    pool = FakePool(
        {
            "id": "job-1",
            "payment_order_id": 91,
            "user_key": "user-key",
            "case_id": "case-1",
            "status": "running",
            "stage": "legal_research",
            "progress": 20,
            "error_detail": "",
        }
    )
    monkeypatch.setattr(jobs, "_POOL", pool)

    job = asyncio.run(jobs.latest_job_for_case(user_key="user-key", case_id="case-1"))

    assert job is not None
    assert job.id == "job-1"
    sql = str(pool.fetchrow_calls[0][0])
    assert "user_key=$1 AND case_id=$2" in sql
    assert "ORDER BY created_at DESC" in sql
    assert "LIMIT 1" in sql


def test_latest_job_for_case_can_be_narrowed_to_one_material_set(monkeypatch) -> None:
    """Добавленные материалы — другой документ, а не повтор уже готового."""
    pool = FakePool(None)
    monkeypatch.setattr(jobs, "_POOL", pool)

    job = asyncio.run(
        jobs.latest_job_for_case(
            user_key="user-key",
            case_id="case-1",
            case_fingerprint="scope-1",
        )
    )

    assert job is None
    sql = str(pool.fetchrow_calls[0][0])
    assert "case_fingerprint" in sql
    assert pool.fetchrow_calls[0][3] == "scope-1"


def test_repeat_generate_on_a_ready_case_never_asks_for_a_second_payment(monkeypatch) -> None:
    _install_identity(monkeypatch, case=READY_CASE)
    created: list[str] = []
    scope_lookups: list[str] = []
    _forbid_payment_store(monkeypatch, created=created, scope_lookups=scope_lookups)
    monkeypatch.setattr(generation_api.v5.v4, "_document_scope", lambda *args: "scope-1")

    async def latest_job_for_case(**kwargs):
        assert kwargs["user_key"] == "user-key"
        assert kwargs["case_id"] == "case-1"
        assert kwargs["case_fingerprint"] == "scope-1"
        return _job("succeeded")

    monkeypatch.setattr(jobs, "latest_job_for_case", latest_job_for_case)

    result = asyncio.run(
        generation_api.generate_document_job(
            generation_api.core.GenerateRequest(case_id="case-1", document_type="claim", language="ru"),
            x_telegram_init_data="signed",
        )
    )

    assert result["payment_required"] is False
    assert result["generation_started"] is False
    assert result["job"]["document_ready"] is True
    assert created == []
    assert scope_lookups == []


def test_new_material_set_still_starts_a_paid_document(monkeypatch) -> None:
    _install_identity(monkeypatch, case=READY_CASE)
    created: list[str] = []
    scope_lookups: list[str] = []
    _forbid_payment_store(monkeypatch, created=created, scope_lookups=scope_lookups)
    monkeypatch.setattr(generation_api.v5.v4, "_document_scope", lambda *args: "scope-2")

    async def latest_job_for_case(**kwargs):
        # Готовая задача осталась за прежним составом материалов.
        assert kwargs["case_fingerprint"] == "scope-2"
        return None

    monkeypatch.setattr(jobs, "latest_job_for_case", latest_job_for_case)

    result = asyncio.run(
        generation_api.generate_document_job(
            generation_api.core.GenerateRequest(case_id="case-1", document_type="claim", language="ru"),
            x_telegram_init_data="signed",
        )
    )

    assert result["payment_required"] is True
    assert created == ["case-1"]


def test_case_recovery_route_has_one_outer_owner() -> None:
    assert owner("/miniapp/cases/{case_id}/generation", "GET") == (
        "korgan.miniapp_generation_api.case_generation_status"
    )


def test_reopened_case_finds_the_running_job_without_a_stored_job_id(monkeypatch) -> None:
    _install_identity(monkeypatch)

    async def latest_job_for_case(**kwargs):
        assert kwargs["user_key"] == "user-key"
        assert kwargs["case_id"] == "case-1"
        assert kwargs.get("case_fingerprint") is None
        return _job("running")

    monkeypatch.setattr(jobs, "latest_job_for_case", latest_job_for_case)

    result = asyncio.run(
        generation_api.case_generation_status("case-1", x_telegram_init_data="signed")
    )

    assert result["job"]["job_id"] == "00000000-0000-0000-0000-000000000501"
    assert result["job"]["status"] == "running"
    assert result["job"]["progress"] == 40
    assert result["job"]["document_ready"] is False
    assert "document" not in result


def test_reopened_case_without_generation_reports_no_job(monkeypatch) -> None:
    _install_identity(monkeypatch)

    async def latest_job_for_case(**kwargs):
        return None

    monkeypatch.setattr(jobs, "latest_job_for_case", latest_job_for_case)

    result = asyncio.run(
        generation_api.case_generation_status("case-1", x_telegram_init_data="signed")
    )

    assert result["job"] is None
    assert "document" not in result


def test_reopened_ready_case_returns_the_document_description(monkeypatch) -> None:
    _install_identity(monkeypatch, case=READY_CASE)

    async def latest_job_for_case(**kwargs):
        return _job("succeeded")

    monkeypatch.setattr(jobs, "latest_job_for_case", latest_job_for_case)

    result = asyncio.run(
        generation_api.case_generation_status("case-1", x_telegram_init_data="signed")
    )

    assert result["job"]["document_ready"] is True
    assert result["document"]["filename"] == "claim.docx"
    assert "document_base64" not in result["document"]


def test_recovery_refuses_to_report_ready_without_a_stored_document(monkeypatch) -> None:
    """Успешная задача без сохранённого документа — не READY, а восстановление."""
    _install_identity(monkeypatch)

    async def latest_job_for_case(**kwargs):
        return _job("succeeded")

    monkeypatch.setattr(jobs, "latest_job_for_case", latest_job_for_case)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(generation_api.case_generation_status("case-1", x_telegram_init_data="signed"))

    assert exc.value.status_code == 409
    assert "оплат" in str(exc.value.detail).lower()


def test_recovery_of_a_foreign_case_is_not_found(monkeypatch) -> None:
    _install_identity(monkeypatch)

    async def forbidden(**kwargs):
        raise AssertionError("чужое дело не должно доходить до хранилища задач")

    monkeypatch.setattr(jobs, "latest_job_for_case", forbidden)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(generation_api.case_generation_status("case-9", x_telegram_init_data="signed"))

    assert exc.value.status_code == 404


def test_recovery_without_payments_reports_no_job(monkeypatch) -> None:
    """Бесплатный режим не поднимает хранилище задач — и не должен падать."""
    _install_identity(monkeypatch)
    monkeypatch.setattr(generation_api.settings, "payments_enabled", False)

    async def forbidden(**kwargs):
        raise AssertionError("без платежей хранилище задач не инициализировано")

    monkeypatch.setattr(jobs, "latest_job_for_case", forbidden)

    result = asyncio.run(
        generation_api.case_generation_status("case-1", x_telegram_init_data="signed")
    )

    assert result["job"] is None
