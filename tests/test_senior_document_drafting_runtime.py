from __future__ import annotations

import asyncio

from korgan import senior_document_drafting_runtime as runtime


def test_senior_rules_require_fact_law_relief_chain_and_no_citation_padding() -> None:
    rules = runtime.senior_drafting_rules()
    assert "установленный факт → подтверждающий материал" in rules
    assert "Не делай «россыпь статей»" in rules
    assert "Процессуальная статья не заменяет материальное основание" in rules
    assert "Не выдумывай цену, процент, срок, дату, штраф" in rules


def test_senior_rules_are_appended_to_existing_document_specific_rules(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_original(self, *args, **kwargs):
        captured["extra_rules"] = str(kwargs.get("extra_rules") or "")
        return {"ok": True}

    monkeypatch.setattr(runtime, "_ORIGINAL_QUALITY_REPAIR", fake_original)
    result = asyncio.run(
        runtime._senior_quality_repair(
            object(),
            extra_rules="DOCUMENT-SPECIFIC RULE",
        )
    )

    assert result == {"ok": True}
    assert "DOCUMENT-SPECIFIC RULE" in captured["extra_rules"]
    assert "SENIOR LEGAL DRAFTING STANDARD" in captured["extra_rules"]
    assert "Не делай «россыпь статей»" in captured["extra_rules"]
