from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from korgan import miniapp_payment_idempotency as idem
from korgan.consultation_quota import ConsultationOrder
from korgan.miniapp_document_payments import DocumentPaymentOrder


@asynccontextmanager
async def _fake_lock(*args, **kwargs):
    yield


def _consultation(status: str) -> ConsultationOrder:
    return ConsultationOrder(
        id=41,
        user_id=12345,
        chat_id=12345,
        question="Платная консультация",
        case_context="контекст",
        language="ru",
        amount_kzt=1000,
        status=status,
    )


def _document(status: str) -> DocumentPaymentOrder:
    return DocumentPaymentOrder(
        id=51,
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


def test_consumed_consultation_never_invokes_paid_ai_delivery_again(monkeypatch) -> None:
    async def fake_get(order_id: int, user_id: int):
        return _consultation("consumed")

    async def forbidden_original(*args, **kwargs):
        raise AssertionError("consumed consultation must not invoke AI/delivery")

    monkeypatch.setattr(idem.consultation_store, "_require_pool", lambda: object())
    monkeypatch.setattr(idem.consultation_store, "get_consultation_order", fake_get)
    monkeypatch.setattr(idem, "payment_operation_lock", _fake_lock)
    monkeypatch.setattr(idem, "_ORIGINAL_ANSWER_PAID", forbidden_original)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            idem._shared_answer_paid_order(
                identity="12345",
                state={},
                order=_consultation("paid"),
            )
        )
    assert exc.value.status_code == 409
    assert "уже была выдана" in str(exc.value.detail)


def test_consumed_document_never_generates_second_time(monkeypatch) -> None:
    async def fake_get(order_id: int, *, user_key: str | None = None):
        return _document("consumed")

    async def forbidden_original(*args, **kwargs):
        raise AssertionError("consumed document payment must not invoke generation again")

    monkeypatch.setattr(idem.document_store, "_require_pool", lambda: object())
    monkeypatch.setattr(idem.document_store, "get_document_order", fake_get)
    monkeypatch.setattr(idem, "payment_operation_lock", _fake_lock)
    monkeypatch.setattr(idem, "_ORIGINAL_RUN_APPROVED_DOCUMENT", forbidden_original)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            idem._shared_run_approved_document(
                _document("approved"),
                x_telegram_init_data="test",
            )
        )
    assert exc.value.status_code == 409
    assert "уже использована" in str(exc.value.detail)


def test_document_order_creation_is_serialized_by_user_and_case(monkeypatch) -> None:
    seen: list[tuple[str, object]] = []

    @asynccontextmanager
    async def recording_lock(pool, namespace: str, identity: object):
        seen.append((namespace, identity))
        yield

    async def fake_original(**kwargs):
        return _document("pending_receipt")

    monkeypatch.setattr(idem.document_store, "_require_pool", lambda: object())
    monkeypatch.setattr(idem, "payment_operation_lock", recording_lock)
    monkeypatch.setattr(idem, "_ORIGINAL_CREATE_DOCUMENT_ORDER", fake_original)

    result = asyncio.run(
        idem._locked_create_document_order(
            user_key="user-key",
            case_id="case-1",
            case_fingerprint="scope-1",
            document_type="claim",
            language="ru",
            amount_kzt=1000,
        )
    )
    assert result.id == 51
    assert seen == [("miniapp-document-order", "user-key:case-1")]
