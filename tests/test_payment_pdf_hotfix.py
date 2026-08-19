from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from korgan.payment import ReceiptAnalyzer
from korgan.payment_pdf_hotfix import install_payment_pdf_hotfix


class _Responses:
    def __init__(self) -> None:
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text=json.dumps({
            "readable": True,
            "looks_like_kaspi": True,
            "payment_successful": True,
            "amount_kzt": 1000,
            "date_time": "2026-08-19 09:00",
            "merchant_or_recipient": "KORGAN",
            "payer": "Client",
            "receipt_or_transaction_id": "TX-1",
            "rnm": "",
            "fp": "",
            "suspicious_signals": [],
            "notes": [],
        }))


@pytest.mark.asyncio
async def test_pdf_receipt_uses_responses_data_url() -> None:
    install_payment_pdf_hotfix()
    analyzer = object.__new__(ReceiptAnalyzer)
    analyzer.settings = SimpleNamespace(openai_vision_model="gpt-5.1")
    responses = _Responses()
    analyzer.client = SimpleNamespace(responses=responses)

    result = await analyzer.analyze(b"%PDF-1.4 test", "receipt.pdf", "application/pdf")

    assert result.amount_kzt == 1000
    content = responses.kwargs["input"][0]["content"]
    file_part = next(item for item in content if item["type"] == "input_file")
    assert file_part["filename"] == "receipt.pdf"
    assert file_part["file_data"].startswith("data:application/pdf;base64,")
    assert "%PDF" not in file_part["file_data"]


def test_runtime_installs_pdf_receipt_hotfix() -> None:
    source = __import__("pathlib").Path("korgan/strict_bot.py").read_text(encoding="utf-8")
    assert "install_payment_pdf_hotfix()" in source
