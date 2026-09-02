from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx


DEFAULT_TOLE_BASE_URL = "https://api.tolepay.kz/v1/"


class ToleError(RuntimeError):
    """Base error for Tole payment integration."""


class ToleConfigurationError(ToleError):
    """Raised when the payment provider is configured unsafely/incompletely."""


class ToleAPIError(ToleError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ToleWebhookError(ToleError):
    """Raised when a webhook cannot be authenticated or parsed safely."""


@dataclass(frozen=True)
class TolePaymentIntent:
    id: str
    kind: str
    status: str
    amount_kzt: int
    currency: str = "KZT"
    payment_url: str = ""
    qr_token: str = ""
    command_id: str = ""
    expires_at: str = ""

    @property
    def paid(self) -> bool:
        # Durable payment-intent endpoints use the normalized `paid` status.
        # Do not infer payment from provider-specific values such as Processed.
        return self.status.strip().lower() == "paid"


@dataclass(frozen=True)
class ToleWebhookEvent:
    id: str
    type: str
    created_at: str
    data: dict[str, Any]


class ToleClient:
    """Minimal backend-only client for Tole dynamic Kaspi QR payments.

    KORGAN deliberately uses dynamic QR as the default Tole primitive: it needs
    only the order amount, while a remote invoice additionally requires the
    client's Kazakhstan phone number. The returned Tole UUID is persisted by the
    caller and later reconciled through the durable payment-intent endpoint.
    """

    def __init__(
        self,
        *,
        api_key: str,
        connection_id: str = "",
        sandbox: bool = False,
        base_url: str = DEFAULT_TOLE_BASE_URL,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.connection_id = connection_id.strip()
        self.sandbox = bool(sandbox)
        self.base_url = base_url.strip().rstrip("/") + "/"
        self.timeout_seconds = float(timeout_seconds)
        self.transport = transport
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        if not self.api_key:
            raise ToleConfigurationError("TOLE_API_KEY is required")
        if not self.base_url.startswith("https://"):
            raise ToleConfigurationError("TOLE base URL must use HTTPS")
        if self.sandbox and not self.connection_id:
            raise ToleConfigurationError("Sandbox requires X-Tole-Connection-Id")

    def _path(self, live_path: str) -> str:
        clean = live_path.lstrip("/")
        return f"sandbox/{clean}" if self.sandbox else clean

    def _headers(self, *, idempotency_key: str = "") -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if self.connection_id:
            headers["X-Tole-Connection-Id"] = self.connection_id
        if idempotency_key:
            key = idempotency_key.strip()
            if not key or len(key) > 100:
                raise ToleConfigurationError("Invalid Tole Idempotency-Key")
            headers["Idempotency-Key"] = key
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        idempotency_key: str = "",
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = urljoin(self.base_url, path.lstrip("/"))
        headers = self._headers(idempotency_key=idempotency_key)
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            try:
                response = await client.request(method, url, headers=headers, json=json_body)
            except httpx.HTTPError as exc:
                raise ToleAPIError("Tole API network error") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ToleAPIError(
                "Tole API returned non-JSON response",
                status_code=response.status_code,
            ) from exc

        if response.status_code >= 400:
            detail = ""
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("code") or "")
                elif error:
                    detail = str(error)
                detail = detail or str(payload.get("message") or "")
            raise ToleAPIError(
                f"Tole API rejected request{': ' + detail[:300] if detail else ''}",
                status_code=response.status_code,
            )
        if not isinstance(payload, dict):
            raise ToleAPIError("Tole API returned an invalid response object")
        return payload

    async def create_qr(self, *, amount_kzt: int, idempotency_key: str) -> TolePaymentIntent:
        amount = int(amount_kzt)
        if amount < 1 or amount > 100_000_000:
            raise ToleConfigurationError("Tole amount must be between 1 and 100000000 KZT")
        payload = await self._request(
            "POST",
            self._path("qr"),
            idempotency_key=idempotency_key,
            json_body={"amount": amount},
        )
        return self._intent_from_create(payload, expected_amount=amount)

    async def get_qr_intent(self, payment_intent_id: str) -> TolePaymentIntent:
        intent_id = payment_intent_id.strip()
        if not intent_id:
            raise ToleConfigurationError("Tole payment intent id is required")
        path = (
            self._path(f"payment-intents/{intent_id}")
            if self.sandbox
            else f"payment-intents/qr/{intent_id}"
        )
        payload = await self._request("GET", path)
        return self._intent_from_status(payload, fallback_id=intent_id)

    @staticmethod
    def _safe_https_url(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        parts = urlsplit(text)
        if parts.scheme != "https" or not parts.netloc:
            raise ToleAPIError("Tole returned a non-HTTPS payment URL")
        return text

    def _intent_from_create(self, payload: dict[str, Any], *, expected_amount: int) -> TolePaymentIntent:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ToleAPIError("Tole create QR response has no data object")
        intent_id = str(data.get("id") or "").strip()
        if not intent_id:
            raise ToleAPIError("Tole create QR response has no payment id")
        amount = int(data.get("amount") or 0)
        if amount != expected_amount:
            raise ToleAPIError("Tole create QR response amount does not match the order")
        kind = str(data.get("kind") or "qr").strip().lower()
        if kind != "qr":
            raise ToleAPIError("Tole returned a non-QR payment intent")
        payment_url = self._safe_https_url(data.get("paymentUrl"))
        qr_token = self._safe_https_url(data.get("qrToken"))
        if not payment_url or not qr_token:
            raise ToleAPIError("Tole QR response is missing paymentUrl/qrToken")
        return TolePaymentIntent(
            id=intent_id,
            kind=kind,
            status=str(data.get("status") or "").strip().lower(),
            amount_kzt=amount,
            currency=str(data.get("currency") or "KZT").strip().upper() or "KZT",
            payment_url=payment_url,
            qr_token=qr_token,
            command_id=str(payload.get("commandId") or "").strip(),
            expires_at=str(data.get("expiresAt") or "").strip(),
        )

    @staticmethod
    def _intent_from_status(payload: dict[str, Any], *, fallback_id: str) -> TolePaymentIntent:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ToleAPIError("Tole payment-intent response has no data object")
        currency = str(data.get("currency") or "KZT").strip().upper() or "KZT"
        if currency != "KZT":
            raise ToleAPIError("Unexpected Tole payment currency")
        return TolePaymentIntent(
            id=str(data.get("id") or fallback_id).strip(),
            kind=str(data.get("kind") or "qr").strip().lower(),
            status=str(data.get("status") or "").strip().lower(),
            amount_kzt=int(data.get("amount") or 0),
            currency=currency,
            expires_at=str(data.get("expiresAt") or "").strip(),
        )


def verify_tole_webhook_signature(
    *,
    secret: str,
    webhook_id: str,
    timestamp: str,
    raw_body: bytes,
    signature: str,
) -> None:
    """Verify Tole's v1 HMAC over id.timestamp.exact_raw_body.

    The caller must pass the unmodified request bytes and should persist the
    webhook event id before applying side effects so retries are idempotent.
    """
    key = secret.strip()
    event_id = webhook_id.strip()
    stamp = timestamp.strip()
    actual = signature.strip()
    if not key or not event_id or not stamp or not actual:
        raise ToleWebhookError("Missing Tole webhook authentication headers")
    try:
        int(stamp)
    except ValueError as exc:
        raise ToleWebhookError("Invalid Tole webhook timestamp") from exc

    signed = event_id.encode("utf-8") + b"." + stamp.encode("utf-8") + b"." + raw_body
    expected = "v1=" + hmac.new(key.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise ToleWebhookError("Invalid Tole webhook signature")


def parse_tole_webhook(raw_body: bytes) -> ToleWebhookEvent:
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToleWebhookError("Invalid Tole webhook JSON") from exc
    if not isinstance(payload, dict):
        raise ToleWebhookError("Invalid Tole webhook object")
    event_id = str(payload.get("id") or "").strip()
    event_type = str(payload.get("type") or "").strip()
    created_at = str(payload.get("createdAt") or "").strip()
    data = payload.get("data")
    if not event_id or not event_type or not isinstance(data, dict):
        raise ToleWebhookError("Incomplete Tole webhook event")
    return ToleWebhookEvent(
        id=event_id,
        type=event_type,
        created_at=created_at,
        data=dict(data),
    )
