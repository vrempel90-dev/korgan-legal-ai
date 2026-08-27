from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from korgan import miniapp_api_v7 as v7
from korgan.kaspi_receipt_verifier import parse_kaspi_qr, parse_receipt_text


def _valid_check(now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        readable=True,
        looks_like_kaspi=True,
        payment_successful=True,
        amount_kzt=1000,
        date_time=now.isoformat(),
        merchant_or_recipient="ИП TEST EDUCATION",
        receipt_or_transaction_id="QR123456789",
        rnm="010103806424",
        fp="557225556134",
        seller_bin="820608350657",
        qr_url="https://receipt.kaspi.kz/web/fiscal?i=557225556134&f=010103806424&s=1000&t=2026-08-27%2018%3A18%3A22",
        official_verified=True,
        suspicious_signals=(),
    )


def test_parse_kaspi_fiscal_qr() -> None:
    parsed = parse_kaspi_qr(
        "https://receipt.kaspi.kz/web/fiscal?"
        "i=557225556134&f=010103806424&s=1000.0&"
        "t=2026-08-27%2018%3A18%3A22.168302"
    )
    assert parsed["fp"] == "557225556134"
    assert parsed["rnm"] == "010103806424"
    assert parsed["amount_kzt"] == 1000
    assert parsed["date_time"].startswith("2026-08-27 18:18:22")


def test_parse_pdf_text_fields_without_ai() -> None:
    text = """
Фискальный чек
Оплата совершена
1 000 ₸
TEST education на Кунаева
ИП TEST EDUCATION
Продажа
Обработка данных и генерация документа
1 шт. x 1 000 ₸ 1 000 ₸
№ чека QR123456789
Дата и время
по Астане
27.08.2026 18:18
Оплачено с Kaspi Gold
ИИН/БИН продавца 820608350657
РНМ 010103806424
ФП 557225556134
ОФД Kaspi ОФД
"""
    parsed = parse_receipt_text(text)
    assert parsed["readable"] is True
    assert parsed["looks_like_kaspi"] is True
    assert parsed["payment_successful"] is True
    assert parsed["amount_kzt"] == 1000
    assert parsed["seller_bin"] == "820608350657"
    assert parsed["rnm"] == "010103806424"
    assert parsed["fp"] == "557225556134"
    assert parsed["receipt_or_transaction_id"] == "QR123456789"


def test_strict_gate_accepts_verified_ofd_receipt(monkeypatch) -> None:
    monkeypatch.setattr(v7.settings, "kaspi_rnm", "010103806424")
    monkeypatch.setattr(v7.settings, "kaspi_seller_bin", "820608350657")
    now = datetime.now(timezone.utc)
    check = _valid_check(now)
    assert v7._strict_receipt_issues(check, 1000, offered_at=now) == []


def test_strict_gate_rejects_wrong_cash_register(monkeypatch) -> None:
    monkeypatch.setattr(v7.settings, "kaspi_rnm", "010103806424")
    monkeypatch.setattr(v7.settings, "kaspi_seller_bin", "820608350657")
    now = datetime.now(timezone.utc)
    check = _valid_check(now)
    check.rnm = "999999999999"
    assert any("РНМ" in issue for issue in v7._strict_receipt_issues(check, 1000, offered_at=now))


def test_strict_gate_rejects_unverified_public_receipt(monkeypatch) -> None:
    monkeypatch.setattr(v7.settings, "kaspi_rnm", "010103806424")
    monkeypatch.setattr(v7.settings, "kaspi_seller_bin", "820608350657")
    now = datetime.now(timezone.utc)
    check = _valid_check(now)
    check.official_verified = False
    assert any("Kaspi ОФД" in issue for issue in v7._strict_receipt_issues(check, 1000, offered_at=now))
