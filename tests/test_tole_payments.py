from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from korgan.tole_payments import (
    ToleAPIError,
    ToleClient,
    ToleConfigurationError,
    ToleWebhookError,
    parse_tole_webhook,
    verify_tole_webhook_signature,
)


def test_live_dynamic_qr_uses_backend_key_and_idempotency() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["idempotency"] = request.headers.get("Idempotency-Key")
        seen["connection"] = request.headers.get("X-Tole-Connection-Id")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "ok": True,
                "data": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "kind": "qr",
                    "status": "created",
                    "amount": 1000,
                    "paymentUrl": "https://pay.tole.test/order-1",
                    "qrToken": "https://qr.kaspi.test/order-1",
                },
                "commandId": "22222222-2222-2222-2222-222222222222",
            },
        )

    client = ToleClient(
        api_key="tole_sk_live_v1.secret",
        connection_id="connection-1",
        transport=httpx.MockTransport(handler),
    )
    intent = asyncio.run(client.create_qr(amount_kzt=1000, idempotency_key="korgan-doc-42-v1"))

    assert seen == {
        "method": "POST",
        "url": "https://api.tolepay.kz/v1/qr",
        "authorization": "Bearer tole_sk_live_v1.secret",
        "idempotency": "korgan-doc-42-v1",
        "connection": "connection-1",
        "body": {"amount": 1000},
    }
    assert intent.id == "11111111-1111-1111-1111-111111111111"
    assert intent.amount_kzt == 1000
    assert intent.payment_url == "https://pay.tole.test/order-1"
    assert intent.paid is False


def test_sandbox_qr_and_reconciliation_use_sandbox_routes() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["X-Tole-Connection-Id"] == "sandbox-connection"
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "ok": True,
                    "data": {
                        "id": "33333333-3333-3333-3333-333333333333",
                        "kind": "qr",
                        "status": "created",
                        "amount": 1000,
                        "paymentUrl": "https://sandbox.tole.test/pay/3",
                        "qrToken": "https://sandbox.tole.test/qr/3",
                        "environment": "sandbox",
                    },
                    "commandId": "44444444-4444-4444-4444-444444444444",
                },
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "id": "33333333-3333-3333-3333-333333333333",
                    "kind": "qr",
                    "status": "paid",
                    "amount": 1000,
                    "currency": "KZT",
                    "environment": "sandbox",
                },
            },
        )

    client = ToleClient(
        api_key="tole_sk_test_v1.secret",
        connection_id="sandbox-connection",
        sandbox=True,
        transport=httpx.MockTransport(handler),
    )
    created = asyncio.run(client.create_qr(amount_kzt=1000, idempotency_key="korgan-doc-1-v1"))
    paid = asyncio.run(client.get_qr_intent(created.id))

    assert paths == [
        "/v1/sandbox/qr",
        "/v1/sandbox/payment-intents/33333333-3333-3333-3333-333333333333",
    ]
    assert paid.paid is True
    assert paid.amount_kzt == 1000


def test_sandbox_requires_connection_id() -> None:
    with pytest.raises(ToleConfigurationError):
        ToleClient(api_key="tole_sk_test_v1.secret", sandbox=True)


def test_create_qr_rejects_amount_mismatch_and_unsafe_url() -> None:
    def mismatch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "ok": True,
                "data": {
                    "id": "id-1",
                    "kind": "qr",
                    "status": "created",
                    "amount": 999,
                    "paymentUrl": "https://pay.tole.test/1",
                    "qrToken": "https://qr.kaspi.test/1",
                },
            },
        )

    client = ToleClient(api_key="secret", transport=httpx.MockTransport(mismatch))
    with pytest.raises(ToleAPIError, match="amount"):
        asyncio.run(client.create_qr(amount_kzt=1000, idempotency_key="order-1"))

    def unsafe(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "ok": True,
                "data": {
                    "id": "id-1",
                    "kind": "qr",
                    "status": "created",
                    "amount": 1000,
                    "paymentUrl": "http://insecure.test/1",
                    "qrToken": "https://qr.kaspi.test/1",
                },
            },
        )

    client = ToleClient(api_key="secret", transport=httpx.MockTransport(unsafe))
    with pytest.raises(ToleAPIError, match="non-HTTPS"):
        asyncio.run(client.create_qr(amount_kzt=1000, idempotency_key="order-1"))


def test_webhook_signature_is_verified_over_exact_raw_body() -> None:
    raw = b'{"id":"evt-1","type":"payment.paid","createdAt":"2026-09-03T00:00:00Z","data":{"environment":"sandbox"}}'
    webhook_id = "evt-1"
    timestamp = "1788393600"
    secret = "whsec_test_secret"
    signed = webhook_id.encode() + b"." + timestamp.encode() + b"." + raw
    signature = "v1=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()

    verify_tole_webhook_signature(
        secret=secret,
        webhook_id=webhook_id,
        timestamp=timestamp,
        raw_body=raw,
        signature=signature,
    )
    event = parse_tole_webhook(raw)
    assert event.id == "evt-1"
    assert event.type == "payment.paid"

    with pytest.raises(ToleWebhookError, match="signature"):
        verify_tole_webhook_signature(
            secret=secret,
            webhook_id=webhook_id,
            timestamp=timestamp,
            raw_body=raw + b" ",
            signature=signature,
        )


def test_webhook_does_not_require_payment_intent_id_in_event_data() -> None:
    # Tole contract v1 explicitly says data fields vary by event and do not
    # guarantee paymentIntentId. The webhook is only a reconciliation signal.
    raw = b'{"id":"evt-2","type":"payment.paid","createdAt":"2026-09-03T00:00:00Z","data":{"providerStatus":"SandboxProcessed"}}'
    event = parse_tole_webhook(raw)
    assert event.type == "payment.paid"
    assert "paymentIntentId" not in event.data
