"""Финальный путь оплаченного документа проходит через собранное приложение.

Нижние уровни отдельно проверяют SQL, блокировки, токены и Telegram-ошибки. Этот
смоук связывает их публичные HTTP-контракты в один путь клиента: дело → запрос
оплаты → ручное подтверждение → сохраняемая задача → настоящий DOCX → повторное
открытие после потери клиентского ``job_id`` → скачивание и Telegram.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any
from urllib.parse import urlencode, urlsplit

from docx import Document
from fastapi.testclient import TestClient

from korgan import miniapp_api
from korgan import miniapp_api_v2 as core
from korgan import miniapp_generation_api as generation_api
from korgan import miniapp_generation_jobs as jobs
from korgan.miniapp_api_recovery_cors import app
from korgan.kaspi_ofd import KaspiFiscalReceipt
from korgan.miniapp_document_payments import DocumentPaymentOrder
from korgan.miniapp_generation_jobs import GenerationJob

TERMS_VERSION = "2026-08-16-v1"
USER_ID = -900000821
ADMIN_ID = -900000822
ORDER_ID = 821
JOB_ID = "00000000-0000-0000-0000-000000000821"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _init_data(user_id: int) -> str:
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "korgan-client-delivery-smoke",
        "user": json.dumps(
            {"id": user_id, "first_name": "KORGAN", "language_code": "ru"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(
        b"WebAppData",
        miniapp_api.settings.telegram_bot_token.encode(),
        hashlib.sha256,
    ).digest()
    pairs["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def _headers(user_id: int) -> dict[str, str]:
    return {"X-Telegram-Init-Data": _init_data(user_id)}


def _docx() -> bytes:
    document = Document()
    document.add_heading("Исковое заявление", level=1)
    document.add_paragraph("О взыскании задолженности по договору подряда.")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_paid_document_survives_reopen_and_is_delivered(monkeypatch) -> None:
    owner_headers = _headers(USER_ID)
    admin_headers = _headers(ADMIN_ID)
    state_by_identity: dict[str, dict[str, Any]] = {}
    order: DocumentPaymentOrder | None = None
    job: GenerationJob | None = None
    worker_release = threading.Event()
    worker_finished = threading.Event()
    telegram: dict[str, Any] = {}
    document_bytes = _docx()

    def payment(status: str) -> DocumentPaymentOrder:
        return DocumentPaymentOrder(
            id=ORDER_ID,
            user_key=core.store.user_key(str(USER_ID)),
            case_id=case_id,
            case_fingerprint="scope-smoke",
            document_type="claim",
            language="ru",
            amount_kzt=1000,
            status=status,
            transaction_id="KASPI-SMOKE-821" if status != "pending_receipt" else "",
            receipt_check={"manual_confirmation_required": True},
            decision_note="",
        )

    async def create_order(**_kwargs):
        nonlocal order
        order = payment("pending_receipt")
        return order

    async def get_scope_order(**_kwargs):
        return order

    async def get_order(order_id: int, *, user_key: str | None = None):
        if order is None or order_id != ORDER_ID:
            return None
        if user_key is not None and user_key != order.user_key:
            return None
        return order

    async def decide_order(order_id: int, *, approved: bool, note: str):
        nonlocal order
        assert order is not None and order_id == ORDER_ID and approved is True
        order = replace(order, status="approved", decision_note=note)
        return True

    async def create_job(**_kwargs):
        nonlocal job
        if job is None:
            job = GenerationJob(
                id=JOB_ID,
                payment_order_id=ORDER_ID,
                user_key=core.store.user_key(str(USER_ID)),
                case_id=case_id,
                status="queued",
                stage="queued",
                progress=0,
                error_detail="",
            )
        return job

    async def latest_job(**kwargs):
        if job is None or kwargs["case_id"] != case_id:
            return None
        return job

    async def require_job(job_id: str, *, user_key: str):
        if job is None or job.id != job_id or job.user_key != user_key:
            raise AssertionError("смоук запросил чужую или отсутствующую задачу")
        return job

    async def run_worker(started_job, **kwargs) -> None:
        nonlocal job, order

        async def wait_for_release() -> None:
            while not worker_release.is_set():
                await asyncio.sleep(0.001)

        job = replace(started_job, status="running", stage="legal_research", progress=20)
        try:
            await wait_for_release()
            state = await core.store.load(kwargs["identity"])
            state["cases"][started_job.case_id].update(
                {
                    "status": "document_ready",
                    "title": "Исковое заявление",
                    "filename": "KORGAN_claim.docx",
                    "document_base64": base64.b64encode(document_bytes).decode("ascii"),
                    "filing_ready": False,
                    "release_status": "preliminary",
                    "verification_status": "needs_verification",
                    "verification_notes": ["Требуется финальная проверка юристом"],
                    "quality_score": 9.0,
                    "quality_issues": ["Проверить приложения"],
                }
            )
            await core.store.save(kwargs["identity"], state)
            assert order is not None
            order = replace(order, status="consumed")
            job = replace(job, status="succeeded", stage="completed", progress=100)
        finally:
            worker_finished.set()

    async def accept_receipt(**kwargs):
        nonlocal order
        assert order is not None and kwargs["order_id"] == ORDER_ID
        assert kwargs["user_key"] == order.user_key
        order = replace(
            order,
            status="awaiting_admin",
            transaction_id=kwargs["transaction_id"],
            receipt_check=kwargs["receipt_check"],
        )
        return True

    async def receipt_created_at(order_id: int, user_key: str):
        assert order is not None and (order_id, user_key) == (ORDER_ID, order.user_key)
        return "2026-09-01T09:59:00+05:00"

    async def receipt_from_upload(file):
        return "https://receipt.kaspi.kz/web/fiscal?t=20260901T100000&f=00000000821&i=00000000000821&s=1000", KaspiFiscalReceipt(
            canonical_url="https://receipt.kaspi.kz/web/fiscal?t=20260901T100000&f=00000000821&i=00000000000821&s=1000",
            body_sha256=hashlib.sha256(b"electronic-kaspi-receipt").hexdigest(),
            ext_transaction_id="",
            receipt_number="KASPI-SMOKE-821",
            successful=True,
            amount_kzt=1000,
            sale_datetime="01.09.2026 10:00:00",
            seller_name="OpenCourt (KORGAN)",
            seller_bin="123456789012",
            rnm="00000000821",
            fp="00000000000821",
            ofd_name="Kaspi ОФД",
            payment_method="Kaspi Pay",
            raw_text="Фискальный чек",
        )

    async def verify_receipt(receipt_url: str, *, expected_amount: int, offered_at):
        assert expected_amount == 1000
        return (await receipt_from_upload(None))[1]

    async def notify_admins(**kwargs):
        assert kwargs["order"].status == "awaiting_admin"
        return 1

    async def consume_order(order_id: int, *, user_key: str):
        nonlocal order
        assert order is not None and order.id == order_id and order.user_key == user_key
        order = replace(order, status="consumed")
        return True

    async def list_admin_orders(*, status: str, limit: int):
        assert limit == 50
        return [order] if order is not None and order.status == status else []

    monkeypatch.setattr(generation_api.settings, "payments_enabled", True)
    monkeypatch.setattr(generation_api.settings, "kaspi_payment_url", "https://pay.korgan.test")
    monkeypatch.setattr(generation_api.settings, "document_price_kzt", 1000)
    monkeypatch.setattr(generation_api.settings, "admin_telegram_ids", str(ADMIN_ID))

    # Lifespan видит включённые платежи и в production потребовал бы PostgreSQL.
    # Смоук заменяет только открытие внешних хранилищ; сами HTTP-контракты ниже
    # проходят через финальные route handlers и устойчивые in-memory fakes.
    async def noop_lifespan_store(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(generation_api.v5.v4, "init_document_payment_store", noop_lifespan_store)
    monkeypatch.setattr(generation_api.v5.v4, "close_document_payment_store", noop_lifespan_store)
    monkeypatch.setattr(generation_api.jobs, "init_generation_job_store", noop_lifespan_store)
    monkeypatch.setattr(generation_api.jobs, "close_generation_job_store", noop_lifespan_store)

    @asynccontextmanager
    async def noop_payment_lock(*args, **kwargs):
        yield

    monkeypatch.setattr(generation_api, "payment_operation_lock", noop_payment_lock)
    monkeypatch.setattr(generation_api.document_store, "_require_pool", lambda: object())
    monkeypatch.setattr(generation_api.document_store, "create_document_order", create_order)
    monkeypatch.setattr(generation_api.document_store, "get_scope_order", get_scope_order)
    monkeypatch.setattr(generation_api.document_store, "get_document_order", get_order)
    monkeypatch.setattr(generation_api.document_store, "accept_document_receipt_precheck", accept_receipt)
    monkeypatch.setattr(generation_api.document_store, "decide_document_order", decide_order)
    monkeypatch.setattr(generation_api.document_store, "list_document_orders_for_admin", list_admin_orders)
    monkeypatch.setattr(generation_api.document_store, "consume_document_order", consume_order)
    monkeypatch.setattr(generation_api.v5.v4, "get_document_order", get_order)
    monkeypatch.setattr(generation_api.v5.v4, "decide_document_order", decide_order)
    monkeypatch.setattr(generation_api.v5.v4, "list_document_orders_for_admin", list_admin_orders)
    monkeypatch.setattr(generation_api.v5.v4, "_document_scope", lambda *args: "scope-smoke")

    from korgan import miniapp_manual_payment_admin as manual_payment

    monkeypatch.setattr(manual_payment.document_store, "get_document_order", get_order)
    monkeypatch.setattr(
        manual_payment.document_store,
        "accept_document_receipt_precheck",
        accept_receipt,
    )
    monkeypatch.setattr(manual_payment.upload_runtime, "_receipt_from_upload", receipt_from_upload)
    monkeypatch.setattr(manual_payment.v5, "_order_created_at", receipt_created_at)
    monkeypatch.setattr(manual_payment.ofd, "_verify_fiscal_receipt", verify_receipt)
    monkeypatch.setattr(manual_payment, "_notify_admins", notify_admins)
    monkeypatch.setattr(jobs, "create_or_get_job", create_job)
    monkeypatch.setattr(jobs, "latest_job_for_case", latest_job)
    monkeypatch.setattr(jobs, "require_job", require_job)
    monkeypatch.setattr(jobs, "run_job", run_worker)

    # Состояние хранится между HTTP-запросами и между двумя TestClient — это
    # серверная сторона refresh/reopen, а не случайно уцелевший React state.
    async def load(identity: str) -> dict[str, Any]:
        return state_by_identity.setdefault(identity, {"consent": None, "cases": {}})

    async def save(identity: str, state: dict[str, Any]) -> None:
        state_by_identity[identity] = state

    async def delete(identity: str) -> None:
        state_by_identity.pop(identity, None)

    monkeypatch.setattr(core.legacy, "_state", load)
    monkeypatch.setattr(core.store, "load", load)
    monkeypatch.setattr(core.store, "save", save)
    monkeypatch.setattr(core.store, "delete", delete)

    class TelegramResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"ok": True, "result": {"message_id": 821}}

    class TelegramClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, *, data=None, files=None):
            telegram.update(url=url, data=data, files=files)
            return TelegramResponse()

    from korgan import miniapp_telegram_delivery as delivery

    monkeypatch.setattr(delivery.httpx, "AsyncClient", TelegramClient)

    with TestClient(app) as client:
        for headers in (owner_headers, admin_headers):
            response = client.post(
                "/miniapp/consent",
                headers=headers,
                json={"accepted": True, "terms_version": TERMS_VERSION},
            )
            assert response.status_code == 200

        created = client.post(
            "/miniapp/cases",
            headers=owner_headers,
            json={
                "description": "Заказчик не оплатил выполненные работы по договору.",
                "document_type": "claim",
                "language": "ru",
            },
        )
        assert created.status_code == 200
        case_id = created.json()["case"]["id"]

        payment_requested = client.post(
            "/miniapp/documents/generate",
            headers=owner_headers,
            json={"case_id": case_id, "document_type": "claim", "language": "ru"},
        )
        assert payment_requested.status_code == 200
        assert payment_requested.json()["payment_required"] is True
        assert payment_requested.json()["payment"]["status"] == "pending_receipt"

        uploaded = client.post(
            f"/miniapp/documents/payments/{ORDER_ID}/receipt",
            headers=owner_headers,
            files={"file": ("Kaspi_receipt.pdf", b"electronic-kaspi-receipt", "application/pdf")},
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["payment"]["status"] == "awaiting_admin"
        assert uploaded.json()["generation_started"] is False

        awaiting = client.get(
            f"/miniapp/documents/payments/{ORDER_ID}", headers=owner_headers
        )
        assert awaiting.json()["payment"]["status"] == "awaiting_admin"

        queue = client.get("/miniapp/admin/document-payments", headers=admin_headers)
        assert queue.status_code == 200
        assert [item["order_id"] for item in queue.json()["orders"]] == [ORDER_ID]

        approved = client.post(
            f"/miniapp/admin/document-payments/{ORDER_ID}/decision",
            headers=admin_headers,
            json={"approved": True, "note": "Сверено в Kaspi Pay"},
        )
        assert approved.status_code == 200
        assert approved.json()["order"]["status"] == "approved"

        started = client.post(
            "/miniapp/documents/generate",
            headers=owner_headers,
            json={"case_id": case_id, "document_type": "claim", "language": "ru"},
        )
        assert started.status_code == 200
        assert started.json()["job"] == {
            "job_id": JOB_ID,
            "case_id": case_id,
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "document_ready": False,
            "retryable": False,
            "error": "",
        }

        # Повторное нажатие не создаёт ни вторую задачу, ни вторую оплату.
        repeated = client.post(
            "/miniapp/documents/generate",
            headers=owner_headers,
            json={"case_id": case_id, "document_type": "claim", "language": "ru"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["job"]["job_id"] == JOB_ID

        deadline = time.monotonic() + 1.0
        progress = client.get(f"/miniapp/documents/generation/{JOB_ID}", headers=owner_headers)
        while progress.json()["job"]["status"] == "queued" and time.monotonic() < deadline:
            time.sleep(0.001)
            progress = client.get(f"/miniapp/documents/generation/{JOB_ID}", headers=owner_headers)
        assert progress.status_code == 200
        assert progress.json()["job"]["progress"] == 20
        assert progress.json()["job"]["document_ready"] is False

        # Пока работа идёт, refresh восстанавливается по делу, даже если job_id
        # потерян вместе с экземпляром фронтенда.
        recovered = client.get(f"/miniapp/cases/{case_id}/generation", headers=owner_headers)
        assert recovered.json()["job"]["job_id"] == JOB_ID
        assert recovered.json()["job"]["stage"] == "legal_research"

        worker_release.set()
        assert worker_finished.wait(timeout=1.0), "фоновая задача не завершилась"

        completed = client.get(f"/miniapp/documents/generation/{JOB_ID}", headers=owner_headers)
        assert completed.status_code == 200
        assert completed.json()["job"]["document_ready"] is True
        assert completed.json()["document"]["filename"] == "KORGAN_claim.docx"
        assert "document_base64" not in completed.json()["document"]

        issued = client.post(
            f"/miniapp/cases/{case_id}/document/access",
            headers=owner_headers,
        )
        assert issued.status_code == 200
        links = issued.json()
        downloaded = client.get(urlsplit(links["download_url"]).path + "?" + urlsplit(links["download_url"]).query)
        preview = client.get(urlsplit(links["preview_url"]).path + "?" + urlsplit(links["preview_url"]).query)
        assert downloaded.status_code == 200
        assert downloaded.headers["content-type"] == DOCX_MIME
        assert downloaded.content == document_bytes
        assert Document(io.BytesIO(downloaded.content)).paragraphs[0].text == "Исковое заявление"
        assert preview.status_code == 200
        assert "О взыскании задолженности" in preview.text

        sent = client.post(f"/miniapp/cases/{case_id}/document/telegram", headers=owner_headers)
        assert sent.status_code == 200
        assert telegram["data"]["chat_id"] == str(USER_ID)
        assert telegram["files"]["document"][1] == document_bytes

    # Новый клиент моделирует закрытие/повторное открытие Mini App. Дело и READY
    # извлекаются по подписанной личности, а не из памяти предыдущего клиента.
    with TestClient(app) as reopened:
        cases = reopened.get("/miniapp/cases", headers=owner_headers)
        assert cases.status_code == 200
        assert [item["id"] for item in cases.json()["cases"]] == [case_id]
        assert cases.json()["cases"][0]["has_document"] is True

        recovered_ready = reopened.get(
            f"/miniapp/cases/{case_id}/generation", headers=owner_headers
        )
        assert recovered_ready.status_code == 200
        assert recovered_ready.json()["job"]["document_ready"] is True
        assert recovered_ready.json()["document"]["filename"] == "KORGAN_claim.docx"

        opened_again = reopened.post(
            f"/miniapp/cases/{case_id}/document/access", headers=owner_headers
        )
        assert opened_again.status_code == 200

        deleted = reopened.delete(f"/miniapp/cases/{case_id}", headers=owner_headers)
        assert deleted.status_code == 200
        assert reopened.get("/miniapp/cases", headers=owner_headers).json()["cases"] == []
