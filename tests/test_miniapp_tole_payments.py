from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json

import httpx

from korgan import miniapp_tole_payments as tole_payments
from korgan.miniapp_tole_payments import ToleClient, verify_tole_webhook_signature


def _signature(secret: str, webhook_id: str, timestamp: str, body: bytes) -> str:
    signed = webhook_id.encode() + b"." + timestamp.encode() + b"." + body
    return "v1=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def test_tole_webhook_signature_uses_exact_raw_body_and_timestamp_window() -> None:
    secret = "whsec_test_secret"
    webhook_id = "c2e94dd8-9802-44e7-a52b-14f45d5b9cdb"
    timestamp = "1788420000"
    body = b'{"id":"c2e94dd8-9802-44e7-a52b-14f45d5b9cdb","type":"payment.paid","data":{"providerStatus":"Processed"}}'
    signature = _signature(secret, webhook_id, timestamp, body)

    assert verify_tole_webhook_signature(
        raw_body=body,
        webhook_id=webhook_id,
        timestamp=timestamp,
        signature=signature,
        secret=secret,
        now=1788420000,
    )
    assert not verify_tole_webhook_signature(
        raw_body=body + b" ",
        webhook_id=webhook_id,
        timestamp=timestamp,
        signature=signature,
        secret=secret,
        now=1788420000,
    )
    assert not verify_tole_webhook_signature(
        raw_body=body,
        webhook_id=webhook_id,
        timestamp=timestamp,
        signature=signature,
        secret=secret,
        now=1788420400,
    )


def test_tole_qr_create_sends_server_auth_connection_and_stable_idempotency() -> None:
    observed: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers.get("Authorization")
        observed["connection"] = request.headers.get("X-Tole-Connection-Id")
        observed["idempotency"] = request.headers.get("Idempotency-Key")
        observed["body"] = json.loads(request.content.decode())
        return httpx.Response(
            201,
            json={
                "ok": True,
                "data": {
                    "id": "33ec20dc-8d82-4077-a557-d59328853df9",
                    "kind": "qr",
                    "status": "created",
                    "amount": 1000,
                    "paymentUrl": "https://pay.example/qr/1",
                    "qrToken": "https://qr.kaspi.kz/example",
                },
                "commandId": "a7a5d4dc-c623-456c-b176-8ec1f1000dc1",
                "replayed": False,
            },
        )

    async def run() -> dict[str, object]:
        client = ToleClient(
            api_key="tole_sk_live_v1.test.secret",
            connection_id="7a67d6bd-5daf-47af-b899-fdb8b7db4d63",
            transport=httpx.MockTransport(handler),
        )
        return await client.create_qr(amount_kzt=1000, idempotency_key="korgan-doc-42-qr-v1")

    result = asyncio.run(run())
    assert result["data"]["status"] == "created"
    assert observed == {
        "authorization": "Bearer tole_sk_live_v1.test.secret",
        "connection": "7a67d6bd-5daf-47af-b899-fdb8b7db4d63",
        "idempotency": "korgan-doc-42-qr-v1",
        "body": {"amount": 1000},
    }


def test_tole_durable_qr_status_read_is_normalized() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/payment-intents/qr/33ec20dc-8d82-4077-a557-d59328853df9")
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "id": "33ec20dc-8d82-4077-a557-d59328853df9",
                    "kind": "qr",
                    "status": "paid",
                    "amount": 1000,
                    "currency": "KZT",
                },
            },
        )

    async def run() -> dict[str, object]:
        client = ToleClient(
            api_key="tole_sk_live_v1.test.secret",
            connection_id="7a67d6bd-5daf-47af-b899-fdb8b7db4d63",
            transport=httpx.MockTransport(handler),
        )
        return await client.get_qr_intent("33ec20dc-8d82-4077-a557-d59328853df9")

    result = asyncio.run(run())
    assert result["data"]["status"] == "paid"
    assert result["data"]["amount"] == 1000
    assert result["data"]["currency"] == "KZT"


def test_tole_orders_never_enter_legacy_manual_admin_state() -> None:
    source = inspect.getsource(tole_payments)
    assert "SET status='awaiting_admin'" not in source
    assert "status IN ('pending_receipt','awaiting_admin')" not in source
    approve_source = inspect.getsource(tole_payments._approve_order_from_tole)
    assert "WHERE id=$1 AND status='pending_receipt'" in approve_source
