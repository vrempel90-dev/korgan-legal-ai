from __future__ import annotations

import base64
import json
from typing import Any

from korgan.payment import ReceiptAnalyzer, ReceiptCheck, _RECEIPT_SCHEMA


def install_payment_pdf_hotfix() -> None:
    """Fix only inline PDF receipt encoding for the OpenAI Responses API.

    Images and all payment/session/release logic remain untouched.
    """
    if getattr(ReceiptAnalyzer, "_pdf_data_url_hotfix_installed", False):
        return

    original_analyze = ReceiptAnalyzer.analyze

    async def analyze(self: ReceiptAnalyzer, data: bytes, filename: str, mime_type: str) -> ReceiptCheck:
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if suffix != "pdf" and mime_type != "application/pdf":
            return await original_analyze(self, data, filename, mime_type)

        encoded = base64.b64encode(data).decode("ascii")
        prompt = (
            "Проведи предварительную проверку чека оплаты KORGAN. Извлеки только то, что реально видно. "
            "Определи, похож ли документ на чек/квитанцию Kaspi, отмечена ли оплата как успешная, сумму, дату/время, "
            "получателя, плательщика, номер операции/чека, РНМ и ФП при наличии. Отдельно перечисли визуальные признаки "
            "возможного редактирования, обрезки критичных полей, несовпадающих шрифтов/слоёв или иных аномалий. "
            "Не называй чек подлинным: у тебя нет прямого доступа к Kaspi Pay/ОФД. Если поле не видно — оставь пустую строку, "
            "для суммы используй 0."
        )
        content: list[dict[str, Any]] = [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {
                    "type": "input_file",
                    "filename": filename,
                    "file_data": f"data:application/pdf;base64,{encoded}",
                },
            ],
        }]

        response = await self.client.responses.create(
            model=self.settings.openai_vision_model,
            instructions=(
                "Ты модуль антифрода KORGAN. Работай консервативно: не выдумывай реквизиты и не подтверждай банковский факт оплаты. "
                "Твоя задача — только предварительная визуальная/реквизитная проверка перед подтверждением платёжного сценария KORGAN."
            ),
            input=content,
            text={"format": {"type": "json_schema", "name": "korgan_receipt_check", "schema": _RECEIPT_SCHEMA, "strict": True}},
            store=False,
        )
        payload = json.loads(response.output_text)
        return ReceiptCheck(
            readable=bool(payload["readable"]),
            looks_like_kaspi=bool(payload["looks_like_kaspi"]),
            payment_successful=bool(payload["payment_successful"]),
            amount_kzt=int(payload["amount_kzt"] or 0),
            date_time=str(payload["date_time"] or ""),
            merchant_or_recipient=str(payload["merchant_or_recipient"] or ""),
            payer=str(payload["payer"] or ""),
            receipt_or_transaction_id=str(payload["receipt_or_transaction_id"] or ""),
            rnm=str(payload["rnm"] or ""),
            fp=str(payload["fp"] or ""),
            suspicious_signals=tuple(str(x) for x in payload["suspicious_signals"]),
            notes=tuple(str(x) for x in payload["notes"]),
        )

    ReceiptAnalyzer.analyze = analyze  # type: ignore[method-assign]
    ReceiptAnalyzer._pdf_data_url_hotfix_installed = True  # type: ignore[attr-defined]
