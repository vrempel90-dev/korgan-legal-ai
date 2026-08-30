from __future__ import annotations

import asyncio

import cv2

from korgan.fiscal_qr_extract import _decode_qr_image
from korgan.kaspi_ofd import KaspiOFDVerificationError
from korgan.kaspi_payment_resilience import is_transient_ofd_error, retry_kaspi_ofd


_RECEIPT_URL = (
    "https://receipt.kaspi.kz/web/fiscal?"
    "f=123456789012&i=12345678&s=1000&t=2026-08-30T11%3A30%3A00"
)


def _compressed_rotated_qr() -> bytes:
    encoder = cv2.QRCodeEncoder_create()
    qr = encoder.encode(_RECEIPT_URL)
    qr = cv2.resize(qr, (220, 220), interpolation=cv2.INTER_NEAREST)
    qr = cv2.rotate(qr, cv2.ROTATE_90_CLOCKWISE)
    ok, encoded = cv2.imencode(".jpg", qr, [cv2.IMWRITE_JPEG_QUALITY, 58])
    assert ok
    return encoded.tobytes()


def test_rotated_compressed_kaspi_qr_is_decoded_without_ai() -> None:
    assert _decode_qr_image(_compressed_rotated_qr()) == _RECEIPT_URL


def test_transient_ofd_failure_retries_and_recovers() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise KaspiOFDVerificationError("Kaspi ОФД вернул HTTP 503")
        return "ok"

    result = asyncio.run(retry_kaspi_ofd(operation, delays=(0.0, 0.0, 0.0)))
    assert result == "ok"
    assert calls == 3


def test_bad_receipt_is_not_retried() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        raise KaspiOFDVerificationError("Kaspi ОФД вернул HTTP 404")

    try:
        asyncio.run(retry_kaspi_ofd(operation, delays=(0.0, 0.0, 0.0)))
    except KaspiOFDVerificationError as exc:
        assert "HTTP 404" in str(exc)
    else:
        raise AssertionError("deterministic receipt failure must remain fail-closed")
    assert calls == 1


def test_only_known_temporary_failures_are_retryable() -> None:
    assert is_transient_ofd_error(KaspiOFDVerificationError("Kaspi ОФД вернул HTTP 429"))
    assert is_transient_ofd_error(KaspiOFDVerificationError("Не удалось получить фискальный чек с Kaspi ОФД"))
    assert not is_transient_ofd_error(KaspiOFDVerificationError("Некорректные параметры ссылки фискального чека"))
