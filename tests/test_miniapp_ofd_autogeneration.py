from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan import miniapp_api_ofd as ofd
from korgan.miniapp_document_payments import DocumentPaymentOrder


def _order(status: str) -> DocumentPaymentOrder:
    return DocumentPaymentOrder(
        id=901,
        user_key="user-key",
        case_id="case-1",
        case_fingerprint="scope-1",
        document_type="claim",
        language="ru",
        amount_kzt=1000,
        status=status,
        transaction_id="tx-901" if status != "pending_receipt" else "",
        receipt_check={},
        decision_note="",
    )


def _generated_payload() -> dict[str, object]:
    return {
        "status": "document_ready",
        "title": "Исковое заявление",
        "verification_status": "verified",
        "filing_ready": True,
        "release_status": "verified",
        "quality_score": 10,
        "document_base64": "ZHVtbXk=",
        "filename": "claim.docx",
        "payment_required": False,
        "paid": True,
        "payment_order_id": 901,
    }


def _install_identity(monkeypatch) -> None:
    monkeypatch.setattr(ofd.core.legacy, "_identity", lambda _init_data: "identity")

    async def require_consent(_identity: str) -> dict[str, object]:
        return {}

    monkeypatch.setattr(ofd.core.legacy, "_require_consent", require_consent)
    monkeypatch.setattr(ofd.core.store, "user_key", lambda _identity: "user-key")


def test_approved_ofd_payment_immediately_runs_document(monkeypatch) -> None:
    _install_identity(monkeypatch)
    approved = _order("approved")
    calls: list[int] = []

    async def get_order(order_id: int, *, user_key: str | None = None):
        assert order_id == approved.id
        assert user_key == approved.user_key
        return approved

    async def run_document(order: DocumentPaymentOrder, *, x_telegram_init_data: str):
        assert x_telegram_init_data == "tg-init"
        calls.append(order.id)
        return _generated_payload()

    monkeypatch.setattr(ofd.document_store, "get_document_order", get_order)
    monkeypatch.setattr(ofd.v5, "_run_approved_document", run_document)

    result = asyncio.run(
        ofd.document_receipt_url(
            approved.id,
            ofd.FiscalReceiptUrl(receipt_url="https://receipt.kaspi.kz/web/fiscal?dummy=1"),
            x_telegram_init_data="tg-init",
        )
    )

    assert result["payment_required"] is False
    assert result["paid"] is True
    assert result["document_base64"]
    assert calls == [approved.id]


def test_fresh_ofd_verification_approves_then_runs_document(monkeypatch) -> None:
    _install_identity(monkeypatch)
    pending = _order("pending_receipt")
    awaiting = _order("awaiting_admin")
    approved = _order("approved")
    get_calls = 0
    generation_calls: list[int] = []

    async def get_order(order_id: int, *, user_key: str | None = None):
        nonlocal get_calls
        assert order_id == pending.id
        assert user_key == pending.user_key
        get_calls += 1
        if get_calls == 1:
            return pending
        if get_calls == 2:
            return awaiting
        return approved

    async def created_at(order_id: int, user_key: str):
        assert order_id == pending.id
        assert user_key == pending.user_key
        return "2026-08-30T10:00:00+00:00"

    receipt = SimpleNamespace(
        successful=True,
        amount_kzt=1000,
        sale_datetime="2026-08-30T10:01:00+00:00",
        seller_name="KORGAN",
        receipt_number="R-901",
        rnm="RNM-1",
        fp="FP-1",
        seller_bin="BIN-1",
        canonical_url="https://receipt.kaspi.kz/api/v3/receipt/download?dummy=1",
        receipt_fingerprint="fingerprint-901",
        transaction_id="transaction-901",
    )

    async def verify_receipt(receipt_url: str, *, expected_amount: int, offered_at):
        assert receipt_url.startswith("https://receipt.kaspi.kz/")
        assert expected_amount == 1000
        assert offered_at == "2026-08-30T10:00:00+00:00"
        return receipt

    async def accept_receipt(**kwargs):
        assert kwargs["order_id"] == pending.id
        assert kwargs["user_key"] == pending.user_key
        assert kwargs["receipt_hash"] == receipt.receipt_fingerprint
        assert kwargs["transaction_id"] == receipt.transaction_id
        return True

    async def decide(order_id: int, *, approved: bool, note: str):
        assert order_id == pending.id
        assert approved is True
        assert "Kaspi OFD" in note
        return True

    async def run_document(order: DocumentPaymentOrder, *, x_telegram_init_data: str):
        generation_calls.append(order.id)
        return _generated_payload()

    monkeypatch.setattr(ofd.document_store, "get_document_order", get_order)
    monkeypatch.setattr(ofd.v5, "_order_created_at", created_at)
    monkeypatch.setattr(ofd, "_verify_fiscal_receipt", verify_receipt)
    monkeypatch.setattr(ofd.document_store, "accept_document_receipt_precheck", accept_receipt)
    monkeypatch.setattr(ofd.document_store, "decide_document_order", decide)
    monkeypatch.setattr(ofd.v5, "_run_approved_document", run_document)

    result = asyncio.run(
        ofd.document_receipt_url(
            pending.id,
            ofd.FiscalReceiptUrl(receipt_url="https://receipt.kaspi.kz/web/fiscal?dummy=1"),
            x_telegram_init_data="tg-init",
        )
    )

    assert result["payment_required"] is False
    assert result["paid"] is True
    assert result["document_base64"]
    assert generation_calls == [pending.id]
