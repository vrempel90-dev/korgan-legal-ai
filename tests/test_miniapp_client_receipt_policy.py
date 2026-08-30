from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from korgan import miniapp_api_ofd as ofd
from korgan.kaspi_ofd import KaspiFiscalReceipt
from korgan.miniapp_document_payments import DocumentPaymentOrder


KORGAN_BIN = "820608350657"
KORGAN_RNM = "010103806424"


def _receipt(*, sale_datetime: str, amount_kzt: int = 1000, rnm: str = KORGAN_RNM) -> KaspiFiscalReceipt:
    # Mirrors the client-provided Kaspi fiscal receipt structure, but deliberately
    # omits buyer/address fields: they are not payment blockers for KORGAN.
    raw_text = "\n".join(
        [
            "Фискальный чек",
            "Оплата совершена",
            f"{amount_kzt} ₸",
            "ИП YSA EDUCATION",
            "Продажа",
            "Обработка данных и генерация документа",
            "№ чека QR17262148385",
            f"Дата и время по Астане {sale_datetime}",
            "Оплачено с Kaspi Gold",
            f"ИИН/БИН продавца {KORGAN_BIN}",
            f"РНМ {rnm}",
            "ЗНМ KK4160038097",
            "ФП 557225556134",
            "ОФД Kaspi ОФД",
        ]
    )
    return KaspiFiscalReceipt(
        canonical_url=(
            "https://receipt.kaspi.kz/api/v3/receipt/download?"
            "extTranId=QR17262148385&locale=ru&sale_date=2026-08-30"
        ),
        body_sha256="a" * 64,
        ext_transaction_id="QR17262148385",
        receipt_number="QR17262148385",
        successful=True,
        amount_kzt=amount_kzt,
        sale_datetime=sale_datetime,
        seller_name="ИП YSA EDUCATION",
        seller_bin=KORGAN_BIN,
        rnm=rnm,
        fp="557225556134",
        ofd_name="Kaspi ОФД",
        payment_method="с Kaspi Gold",
        raw_text=raw_text,
    )


def _install_receipt_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        ofd,
        "settings",
        SimpleNamespace(
            payment_seller_bin=KORGAN_BIN,
            kaspi_payment_recipient="ИП YSA EDUCATION",
            payment_rnm=KORGAN_RNM,
        ),
    )


def test_client_receipt_fields_pass_without_address_when_fresh(monkeypatch) -> None:
    _install_receipt_settings(monkeypatch)
    receipt = _receipt(sale_datetime="30.08.2026 13:01")

    async def fetch(_url: str):
        return receipt

    monkeypatch.setattr(ofd, "fetch_kaspi_ofd_receipt", fetch)

    verified = asyncio.run(
        ofd._verify_fiscal_receipt(
            receipt.canonical_url,
            expected_amount=1000,
            offered_at="2026-08-30T13:00:00+05:00",
        )
    )

    assert verified.receipt_number == "QR17262148385"
    assert verified.seller_bin == KORGAN_BIN
    assert verified.rnm == KORGAN_RNM
    assert verified.fp == "557225556134"
    assert verified.ofd_name == "Kaspi ОФД"
    assert "Адрес" not in verified.raw_text


def test_old_receipt_cannot_pay_a_new_order(monkeypatch) -> None:
    _install_receipt_settings(monkeypatch)
    receipt = _receipt(sale_datetime="27.08.2026 18:18")

    async def fetch(_url: str):
        return receipt

    monkeypatch.setattr(ofd, "fetch_kaspi_ofd_receipt", fetch)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            ofd._verify_fiscal_receipt(
                receipt.canonical_url,
                expected_amount=1000,
                offered_at="2026-08-30T13:00:00+05:00",
            )
        )

    assert exc_info.value.status_code == 422
    assert "до открытия текущей заявки" in str(exc_info.value.detail)


def test_wrong_amount_or_rnm_never_unlocks_document(monkeypatch) -> None:
    _install_receipt_settings(monkeypatch)
    receipt = _receipt(sale_datetime="30.08.2026 13:01", amount_kzt=999, rnm="999999999999")

    async def fetch(_url: str):
        return receipt

    monkeypatch.setattr(ofd, "fetch_kaspi_ofd_receipt", fetch)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            ofd._verify_fiscal_receipt(
                receipt.canonical_url,
                expected_amount=1000,
                offered_at="2026-08-30T13:00:00+05:00",
            )
        )

    detail = str(exc_info.value.detail)
    assert exc_info.value.status_code == 422
    assert "999 ₸ вместо 1000 ₸" in detail
    assert "РНМ" in detail


def test_paid_order_generates_exact_document_selected_by_client(monkeypatch) -> None:
    order = DocumentPaymentOrder(
        id=1001,
        user_key="user-key",
        case_id="case-contract",
        case_fingerprint="scope-contract",
        document_type="contract",
        language="ru",
        amount_kzt=1000,
        status="approved",
        transaction_id=f"{KORGAN_RNM}:QR17262148385:557225556134",
        receipt_check={},
        decision_note="Kaspi OFD verified",
    )

    monkeypatch.setattr(ofd.core.legacy, "_identity", lambda _init_data: "identity")

    async def require_consent(_identity: str):
        return {
            "cases": {
                "case-contract": {
                    "id": "case-contract",
                    "document_type": "contract",
                    "language": "ru",
                }
            }
        }

    monkeypatch.setattr(ofd.core.legacy, "_require_consent", require_consent)
    monkeypatch.setattr(ofd.core.store, "user_key", lambda _identity: "user-key")
    monkeypatch.setattr(ofd.v4, "_document_scope", lambda _case, doc_type, language: f"scope-{doc_type}")

    generated: list[tuple[str, str, str]] = []

    async def generate_document(payload, x_telegram_init_data: str):
        generated.append((payload.case_id, payload.document_type, payload.language))
        assert x_telegram_init_data == "tg-init"
        return {
            "status": "document_ready",
            "title": "Договор",
            "verification_status": "verified",
            "filing_ready": True,
            "release_status": "verified",
            "quality_score": 10,
            "quality_issues": [],
            "verification_notes": [],
            "document_base64": "ZHVtbXk=",
            "filename": "KORGAN_dogovor.docx",
        }

    async def consume_document_order(order_id: int, *, user_key: str):
        assert order_id == order.id
        assert user_key == "user-key"
        return True

    monkeypatch.setattr(ofd.core, "generate_document", generate_document)
    monkeypatch.setattr(ofd.document_store, "consume_document_order", consume_document_order)

    result = asyncio.run(
        ofd._original_run_approved_document(
            order,
            x_telegram_init_data="tg-init",
        )
    )

    assert generated == [("case-contract", "contract", "ru")]
    assert result["paid"] is True
    assert result["payment_required"] is False
    assert result["filename"] == "KORGAN_dogovor.docx"
