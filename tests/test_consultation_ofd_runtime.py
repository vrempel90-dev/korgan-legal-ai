from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_paid_consultation_runtime_uses_kaspi_ofd_not_ai_receipt_decision() -> None:
    source = (ROOT / "korgan" / "consultation_quota_runtime.py").read_text(encoding="utf-8")
    assert "fetch_kaspi_ofd_receipt" in source
    assert "fiscal_receipt_issues" in source
    assert "accept_consultation_receipt" in source
    assert "ReceiptAnalyzer" not in source
    assert "_receipt_bytes" not in source
    assert "AI не принимает решение об оплате" in source


def test_photo_or_pdf_cannot_unlock_paid_consultation() -> None:
    source = (ROOT / "korgan" / "consultation_quota_runtime.py").read_text(encoding="utf-8")
    assert "Фото/PDF не подтверждают оплату" in source
    assert "receipt.kaspi.kz" in source
