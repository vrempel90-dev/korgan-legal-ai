from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Header, HTTPException, Request

from korgan import miniapp_api_v5 as v5
from korgan import miniapp_document_payments as document_store
from korgan import miniapp_manual_payment_admin as manual_runtime
from korgan.payment_operation_lock import payment_operation_lock

LOGGER = logging.getLogger(__name__)

app = manual_runtime.app
core = manual_runtime.core
settings = manual_runtime.settings

_TOLE_BASE_URL = "https://api.tolepay.kz/v1"
_TOLE_TIMEOUT = 12.0
_TOLE_WEBHOOK_MAX_SKEW_SECONDS = 300
_SCHEMA_LOCK = asyncio.Lock()
_SCHEMA_READY = False
_ROUTES_INSTALLED = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS korgan_miniapp_tole_payments (
    order_id BIGINT PRIMARY KEY REFERENCES korgan_miniapp_document_orders(id) ON DELETE CASCADE,
    provider_intent_id TEXT UNIQUE,
    command_id TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    payment_url TEXT NOT NULL DEFAULT '',
    qr_token TEXT NOT NULL DEFAULT '',
    provider_status TEXT NOT NULL DEFAULT 'initializing',
    amount_kzt INTEGER NOT NULL CHECK (amount_kzt > 0),
    currency TEXT NOT NULL DEFAULT 'KZT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS korgan_miniapp_tole_pending_idx
ON korgan_miniapp_tole_payments(provider_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS korgan_miniapp_tole_webhook_events (
    webhook_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


@dataclass(frozen=True)
class TolePayment:
    order_id: int
    provider_intent_id: str
    command_id: str
    idempotency_key: str
    payment_url: str
    qr_token: str
    provider_status: str
    amount_kzt: int
    currency: str


class ToleAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 0, kind: str = "") -> None:
        super().__init__(message)
        self.status_code = int(status_code or 0)
        self.kind = str(kind or "")


class ToleClient:
    def __init__(
        self,
        *,
        api_key: str,
        connection_id: str,
        base_url: str = _TOLE_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.connection_id = connection_id.strip()
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    def _headers(self, *, idempotency_key: str = "") -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if self.connection_id:
            headers["X-Tole-Connection-Id"] = self.connection_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> tuple[int, dict[str, Any]]:
        try:
            async with httpx.AsyncClient(
                timeout=_TOLE_TIMEOUT,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self._headers(idempotency_key=idempotency_key),
                    json=json_body,
                )
        except httpx.HTTPError as exc:
            raise ToleAPIError("Tole API временно недоступен") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ToleAPIError(
                "Tole API вернул некорректный ответ",
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise ToleAPIError("Tole API вернул некорректный ответ", status_code=response.status_code)
        if response.status_code >= 400:
            raise ToleAPIError(
                str(payload.get("message") or payload.get("code") or "Tole API отклонил запрос"),
                status_code=response.status_code,
                kind=str(payload.get("code") or ""),
            )
        return response.status_code, payload

    async def create_qr(self, *, amount_kzt: int, idempotency_key: str) -> dict[str, Any]:
        status, payload = await self._request(
            "POST",
            "/qr",
            json_body={"amount": int(amount_kzt)},
            idempotency_key=idempotency_key,
        )
        if status not in {200, 201, 202}:
            raise ToleAPIError("Неожиданный статус Tole при создании QR", status_code=status)
        return payload

    async def get_command(self, command_id: str) -> dict[str, Any]:
        status, payload = await self._request("GET", f"/commands/{command_id}")
        if status != 200:
            raise ToleAPIError("Не удалось сверить команду Tole", status_code=status)
        return payload

    async def get_qr_intent(self, payment_intent_id: str) -> dict[str, Any]:
        status, payload = await self._request("GET", f"/payment-intents/qr/{payment_intent_id}")
        if status != 200:
            raise ToleAPIError("Не удалось сверить статус оплаты Tole", status_code=status)
        return payload


def _env(name: str) -> str:
    return str(os.getenv(name, "") or "").strip()


def tole_configured() -> bool:
    return bool(_env("TOLE_API_KEY") and _env("TOLE_CONNECTION_ID") and _env("TOLE_WEBHOOK_SECRET"))


def _client() -> ToleClient:
    api_key = _env("TOLE_API_KEY")
    connection_id = _env("TOLE_CONNECTION_ID")
    if not api_key or not connection_id:
        raise HTTPException(status_code=503, detail="Автоматическая оплата Tole временно не настроена")
    return ToleClient(api_key=api_key, connection_id=connection_id)


def verify_tole_webhook_signature(
    *,
    raw_body: bytes,
    webhook_id: str,
    timestamp: str,
    signature: str,
    secret: str,
    now: int | None = None,
) -> bool:
    event_id = str(webhook_id or "").strip()
    stamp = str(timestamp or "").strip()
    actual = str(signature or "").strip()
    signing_secret = str(secret or "").strip()
    if not event_id or not stamp or not actual or not signing_secret:
        return False
    try:
        stamp_int = int(stamp)
    except ValueError:
        return False
    current = int(time.time() if now is None else now)
    if abs(current - stamp_int) > _TOLE_WEBHOOK_MAX_SKEW_SECONDS:
        return False
    signed = event_id.encode("utf-8") + b"." + stamp.encode("ascii") + b"." + raw_body
    expected = "v1=" + hmac.new(signing_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(actual, expected)


async def _ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    async with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        await document_store._require_pool().execute(_SCHEMA)
        _SCHEMA_READY = True


def _payment_from_row(row: Any) -> TolePayment | None:
    if row is None:
        return None
    return TolePayment(
        order_id=int(row["order_id"]),
        provider_intent_id=str(row["provider_intent_id"] or ""),
        command_id=str(row["command_id"] or ""),
        idempotency_key=str(row["idempotency_key"] or ""),
        payment_url=str(row["payment_url"] or ""),
        qr_token=str(row["qr_token"] or ""),
        provider_status=str(row["provider_status"] or ""),
        amount_kzt=int(row["amount_kzt"]),
        currency=str(row["currency"] or "KZT"),
    )


async def _get_tole_payment(order_id: int) -> TolePayment | None:
    await _ensure_schema()
    row = await document_store._require_pool().fetchrow(
        """
        SELECT order_id, provider_intent_id, command_id, idempotency_key,
               payment_url, qr_token, provider_status, amount_kzt, currency
        FROM korgan_miniapp_tole_payments WHERE order_id=$1
        """,
        int(order_id),
    )
    return _payment_from_row(row)


async def _upsert_provider_result(
    order_id: int,
    *,
    provider_intent_id: str = "",
    command_id: str = "",
    payment_url: str = "",
    qr_token: str = "",
    provider_status: str = "",
    currency: str = "KZT",
) -> None:
    await _ensure_schema()
    await document_store._require_pool().execute(
        """
        UPDATE korgan_miniapp_tole_payments
        SET provider_intent_id=COALESCE(NULLIF($2,''), provider_intent_id),
            command_id=COALESCE(NULLIF($3,''), command_id),
            payment_url=CASE WHEN $4<>'' THEN $4 ELSE payment_url END,
            qr_token=CASE WHEN $5<>'' THEN $5 ELSE qr_token END,
            provider_status=CASE WHEN $6<>'' THEN $6 ELSE provider_status END,
            currency=CASE WHEN $7<>'' THEN $7 ELSE currency END,
            updated_at=NOW()
        WHERE order_id=$1
        """,
        int(order_id), provider_intent_id, command_id, payment_url, qr_token, provider_status, currency,
    )


async def _reserve_tole_payment(order: document_store.DocumentPaymentOrder) -> TolePayment:
    await _ensure_schema()
    idempotency_key = f"korgan-doc-{order.id}-qr-v1"
    await document_store._require_pool().execute(
        """
        INSERT INTO korgan_miniapp_tole_payments(order_id, idempotency_key, amount_kzt)
        VALUES($1,$2,$3)
        ON CONFLICT (order_id) DO NOTHING
        """,
        order.id,
        idempotency_key,
        order.amount_kzt,
    )
    payment = await _get_tole_payment(order.id)
    if payment is None:
        raise RuntimeError("Не удалось сохранить платёж Tole")
    return payment


def _extract_create_result(payload: dict[str, Any]) -> dict[str, str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return {
        "provider_intent_id": str(data.get("id") or ""),
        "command_id": str(payload.get("commandId") or ""),
        "payment_url": str(data.get("paymentUrl") or ""),
        "qr_token": str(data.get("qrToken") or ""),
        "provider_status": str(data.get("status") or payload.get("kind") or ""),
        "currency": str(data.get("currency") or "KZT"),
    }


async def _resolve_command(payment: TolePayment, client: ToleClient) -> TolePayment:
    if payment.provider_intent_id or not payment.command_id:
        return payment
    payload = await client.get_command(payment.command_id)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    command_status = str(data.get("status") or "")
    if command_status != "succeeded":
        await _upsert_provider_result(payment.order_id, provider_status=f"command_{command_status or 'pending'}")
        return (await _get_tole_payment(payment.order_id)) or payment
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    extracted = _extract_create_result(result)
    await _upsert_provider_result(payment.order_id, **extracted)
    return (await _get_tole_payment(payment.order_id)) or payment


async def _ensure_tole_qr(order: document_store.DocumentPaymentOrder) -> TolePayment:
    client = _client()
    async with payment_operation_lock(document_store._require_pool(), "tole-create-qr", order.id):
        payment = await _reserve_tole_payment(order)
        if payment.provider_intent_id and payment.payment_url:
            return payment
        if payment.command_id and not payment.provider_intent_id:
            payment = await _resolve_command(payment, client)
            if payment.provider_intent_id or payment.command_id:
                return payment

        payload = await client.create_qr(amount_kzt=order.amount_kzt, idempotency_key=payment.idempotency_key)
        extracted = _extract_create_result(payload)
        await _upsert_provider_result(order.id, **extracted)
        payment = (await _get_tole_payment(order.id)) or payment

        if not payment.provider_intent_id and payment.command_id:
            payment = await _resolve_command(payment, client)
        return payment


async def _approve_order_from_tole(order_id: int, *, provider_intent_id: str) -> None:
    pool = document_store._require_pool()
    async with payment_operation_lock(pool, "tole-approve-document", order_id):
        await pool.execute(
            """
            UPDATE korgan_miniapp_document_orders
            SET status='approved', decided_at=NOW(),
                decision_note=$2, transaction_id=$3
            WHERE id=$1 AND status IN ('pending_receipt','awaiting_admin')
            """,
            int(order_id),
            "Tole payment verified automatically",
            provider_intent_id,
        )


async def _cancel_order_from_tole(order_id: int, *, provider_status: str) -> None:
    await document_store._require_pool().execute(
        """
        UPDATE korgan_miniapp_document_orders
        SET status='cancelled', decided_at=NOW(), decision_note=$2
        WHERE id=$1 AND status IN ('pending_receipt','awaiting_admin')
        """,
        int(order_id),
        f"Tole payment {provider_status}"[:500],
    )


async def _reconcile_payment(payment: TolePayment, *, client: ToleClient | None = None) -> TolePayment:
    if not payment.provider_intent_id:
        if payment.command_id:
            payment = await _resolve_command(payment, client or _client())
        if not payment.provider_intent_id:
            return payment

    api = client or _client()
    payload = await api.get_qr_intent(payment.provider_intent_id)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    status = str(data.get("status") or "").lower()
    amount = int(data.get("amount") or 0)
    currency = str(data.get("currency") or "KZT").upper()

    if amount != payment.amount_kzt or currency != "KZT":
        LOGGER.error(
            "TOLE_PAYMENT_AMOUNT_MISMATCH order_id=%s provider_intent=%s expected=%s actual=%s currency=%s",
            payment.order_id, payment.provider_intent_id, payment.amount_kzt, amount, currency,
        )
        await _upsert_provider_result(payment.order_id, provider_status="amount_mismatch", currency=currency)
        return (await _get_tole_payment(payment.order_id)) or payment

    await _upsert_provider_result(payment.order_id, provider_status=status, currency=currency)
    if status == "paid":
        await _approve_order_from_tole(payment.order_id, provider_intent_id=payment.provider_intent_id)
    elif status in {"cancelled", "expired", "failed"}:
        await _cancel_order_from_tole(payment.order_id, provider_status=status)
    return (await _get_tole_payment(payment.order_id)) or payment


async def _reconcile_pending_payments(limit: int = 50) -> int:
    await _ensure_schema()
    rows = await document_store._require_pool().fetch(
        """
        SELECT t.order_id, t.provider_intent_id, t.command_id, t.idempotency_key,
               t.payment_url, t.qr_token, t.provider_status, t.amount_kzt, t.currency
        FROM korgan_miniapp_tole_payments t
        JOIN korgan_miniapp_document_orders o ON o.id=t.order_id
        WHERE o.status IN ('pending_receipt','awaiting_admin')
        ORDER BY t.updated_at ASC
        LIMIT $1
        """,
        max(1, min(int(limit), 100)),
    )
    client = _client()
    processed = 0
    for row in rows:
        try:
            await _reconcile_payment(_payment_from_row(row), client=client)  # type: ignore[arg-type]
            processed += 1
        except Exception:
            LOGGER.exception("TOLE_RECONCILE_FAILED order_id=%s", row["order_id"])
    return processed


def _payment_payload(order: document_store.DocumentPaymentOrder, payment: TolePayment | None) -> dict[str, Any]:
    url = payment.payment_url if payment is not None else ""
    provider_status = payment.provider_status if payment is not None else ""
    return {
        "order_id": order.id,
        "case_id": order.case_id,
        "document_type": order.document_type,
        "amount_kzt": order.amount_kzt,
        "status": order.status,
        "decision_note": order.decision_note,
        "payment_provider": "tole",
        "payment_url": url,
        "kaspi_url": url,
        "automatic_confirmation": True,
        "approval_required": False,
        "receipt_accept": [],
        "provider_status": provider_status,
    }


async def _resolve_document_order(
    payload: Any,
    x_telegram_init_data: str,
) -> tuple[str, document_store.DocumentPaymentOrder]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    case = state["cases"].get(payload.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    document_type = str(case.get("document_type") or payload.document_type or "claim")
    if document_type not in core._DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported document type")
    if payload.document_type and payload.document_type != document_type:
        raise HTTPException(status_code=409, detail="Тип документа не соответствует активному делу")
    language = "kk" if str(case.get("language") or payload.language) == "kk" else "ru"
    if not core._case_context(case).strip():
        raise HTTPException(status_code=422, detail="Добавьте описание ситуации или загрузите материалы дела")

    user_key = core.store.user_key(identity)
    scope = v5.v4._document_scope(case, document_type, language)
    order = await document_store.get_scope_order(
        user_key=user_key,
        case_id=payload.case_id,
        case_fingerprint=scope,
    )
    if order is None:
        order = await document_store.create_document_order(
            user_key=user_key,
            case_id=payload.case_id,
            case_fingerprint=scope,
            document_type=document_type,
            language=language,
            amount_kzt=settings.document_price_kzt,
        )
    return identity, order


async def _mark_waiting(order_id: int) -> None:
    await document_store._require_pool().execute(
        """
        UPDATE korgan_miniapp_document_orders
        SET status='awaiting_admin', decision_note='Waiting for automatic Tole confirmation'
        WHERE id=$1 AND status='pending_receipt'
        """,
        int(order_id),
    )


def _require_tole_runtime() -> None:
    if not tole_configured():
        raise HTTPException(status_code=503, detail="Автоматическая оплата Tole временно не настроена")


def _drop_payment_routes() -> None:
    for path, method in (
        ("/miniapp/parity", "GET"),
        ("/miniapp/pricing", "GET"),
        ("/miniapp/documents/generate", "POST"),
        ("/miniapp/documents/payments/{order_id}", "GET"),
        ("/miniapp/documents/payments/{order_id}/receipt", "POST"),
        ("/miniapp/documents/payments/{order_id}/receipt-url", "POST"),
    ):
        v5._drop(path, method)


def install_tole_payment_routes() -> bool:
    global _ROUTES_INSTALLED
    if _ROUTES_INSTALLED or not tole_configured():
        return False
    _drop_payment_routes()

    @app.get("/miniapp/parity")
    async def tole_parity() -> dict[str, Any]:
        payload = await v5.v4.parity()
        payload.update({
            "document_payments_enabled": bool(settings.payments_enabled),
            "document_payment_provider": "tole",
            "document_manual_confirmation": False,
            "automatic_receipt_verification": False,
            "automatic_payment_confirmation": True,
            "tole_configured": True,
        })
        return payload

    @app.get("/miniapp/pricing")
    async def tole_pricing(x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
        payload = await v5.v4.pricing(x_telegram_init_data)
        payload.update({
            "document_payments_enabled": bool(settings.payments_enabled),
            "document_price_kzt": int(settings.document_price_kzt),
            "document_payment_provider": "tole",
            "document_manual_confirmation": False,
            "automatic_payment_confirmation": True,
            "kaspi_url": "",
        })
        return payload

    @app.post("/miniapp/documents/generate")
    async def tole_generate_document(
        payload: core.GenerateRequest,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        if not settings.payments_enabled:
            return await v5.generate_document(payload, x_telegram_init_data)
        _require_tole_runtime()
        _, order = await _resolve_document_order(payload, x_telegram_init_data)
        payment = await _get_tole_payment(order.id)
        if payment is not None:
            try:
                payment = await _reconcile_payment(payment)
            except ToleAPIError:
                LOGGER.warning("TOLE_STATUS_UNAVAILABLE order_id=%s", order.id)
            refreshed = await document_store.get_document_order(order.id, user_key=order.user_key)
            if refreshed is not None:
                order = refreshed
        if order.status == "approved":
            return await v5._run_approved_document(order, x_telegram_init_data=x_telegram_init_data)
        try:
            payment = await _ensure_tole_qr(order)
        except ToleAPIError as exc:
            LOGGER.warning("TOLE_QR_CREATE_FAILED order_id=%s status=%s kind=%s", order.id, exc.status_code, exc.kind)
            raise HTTPException(status_code=502, detail="Не удалось создать безопасную оплату Tole. Повторно платить не нужно.") from exc
        await _mark_waiting(order.id)
        order = (await document_store.get_document_order(order.id, user_key=order.user_key)) or order
        if not payment.payment_url:
            raise HTTPException(status_code=503, detail="Tole создаёт QR оплаты. Повторите через несколько секунд; новая заявка не создастся.")
        return {
            "payment_required": True,
            "generation_started": False,
            "payment": _payment_payload(order, payment),
        }

    @app.get("/miniapp/documents/payments/{order_id}")
    async def tole_document_payment_status(
        order_id: int,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        identity = core.legacy._identity(x_telegram_init_data)
        await core.legacy._require_consent(identity)
        user_key = core.store.user_key(identity)
        order = await document_store.get_document_order(order_id, user_key=user_key)
        if order is None:
            raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
        payment = await _get_tole_payment(order.id)
        if payment is not None and order.status in {"pending_receipt", "awaiting_admin"}:
            try:
                payment = await _reconcile_payment(payment)
            except ToleAPIError:
                LOGGER.warning("TOLE_STATUS_POLL_FAILED order_id=%s", order.id)
            order = (await document_store.get_document_order(order.id, user_key=user_key)) or order
        return {"payment": _payment_payload(order, payment)}

    @app.post("/miniapp/documents/payments/{order_id}/receipt")
    async def tole_receipt_disabled(order_id: int) -> dict[str, Any]:
        raise HTTPException(
            status_code=409,
            detail="Чек загружать не нужно. Tole подтвердит оплату автоматически через Kaspi Pay.",
        )

    @app.post("/miniapp/documents/payments/{order_id}/receipt-url")
    async def tole_receipt_url_disabled(order_id: int) -> dict[str, Any]:
        raise HTTPException(
            status_code=409,
            detail="QR фискального чека не нужен. Tole подтвердит оплату автоматически.",
        )

    @app.post("/miniapp/payments/tole/webhook")
    async def tole_webhook(request: Request) -> dict[str, Any]:
        secret = _env("TOLE_WEBHOOK_SECRET")
        raw = await request.body()
        webhook_id = request.headers.get("webhook-id", "")
        timestamp = request.headers.get("webhook-timestamp", "")
        signature = request.headers.get("webhook-signature", "")
        if not verify_tole_webhook_signature(
            raw_body=raw,
            webhook_id=webhook_id,
            timestamp=timestamp,
            signature=signature,
            secret=secret,
        ):
            raise HTTPException(status_code=401, detail="Invalid Tole webhook signature")
        try:
            event = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid Tole webhook body") from exc
        if not isinstance(event, dict) or str(event.get("id") or "") != str(webhook_id):
            raise HTTPException(status_code=400, detail="Tole webhook id mismatch")
        event_type = str(event.get("type") or "")
        await _ensure_schema()
        result = await document_store._require_pool().execute(
            """
            INSERT INTO korgan_miniapp_tole_webhook_events(webhook_id, event_type, payload_sha256)
            VALUES($1,$2,$3) ON CONFLICT (webhook_id) DO NOTHING
            """,
            webhook_id,
            event_type[:120],
            hashlib.sha256(raw).hexdigest(),
        )
        inserted = result.endswith("1")
        if event_type.startswith("payment.") or event_type.startswith("operation."):
            await _reconcile_pending_payments(limit=50)
        LOGGER.info("TOLE_WEBHOOK_ACCEPTED id=%s type=%s duplicate=%s", webhook_id, event_type, not inserted)
        return {"ok": True, "duplicate": not inserted}

    _ROUTES_INSTALLED = True
    LOGGER.info("TOLE_PAYMENT_RUNTIME_INSTALLED provider=tole mode=dynamic_qr")
    return True


install_tole_payment_routes()
