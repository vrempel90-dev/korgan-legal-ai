"""Отказ финальной проверки договора не должен превращаться в петлю повторов.

Проверка правильно не выпускает договор с перепутанными сторонами, выдуманной
суммой или неподтверждённой ссылкой на закон. Но пока причина отказа не
доходила до клиента, повтор шёл с теми же материалами и упирался в тот же
дефект. Здесь проверяется, что проверка осталась на месте, а причина стала
названной — и что исправленные материалы проходят.
"""

from __future__ import annotations

import asyncio

import pytest

from korgan.robust_production_legal import ContractQualityBlocked


def _contract_service():
    """Объект, который реально выполняет договорные методы в этом процессе.

    Слоёв сервиса несколько, и какой из них окажется под адаптером, зависит от
    установленных рантайм-слоёв. Тест ищет владельца `draft_contract` вместо
    того, чтобы называть класс по имени: иначе он проверял бы не тот объект,
    который отвечает на боевой запрос.
    """
    from korgan import miniapp_api as legacy

    seen: list[object] = []
    pending: list[object] = [legacy.service]
    while pending:
        candidate = pending.pop()
        if candidate is None or any(candidate is item for item in seen):
            continue
        seen.append(candidate)
        if "draft_contract" in dir(candidate) and hasattr(candidate, "validate_contract"):
            return candidate
        for attr in ("inner", "_inner", "stable", "service", "_service"):
            pending.append(getattr(candidate, attr, None))
    raise AssertionError("не найден сервис, выполняющий договорные методы")


def test_blocked_contract_tells_the_client_what_to_clarify() -> None:
    blocked = ContractQualityBlocked(
        [
            "перепутаны стороны: исполнитель указан как заказчик",
            "сумма вознаграждения не следует из материалов",
        ]
    )

    assert "новая оплата не потребуется" in blocked.detail
    assert "перепутаны стороны" in blocked.detail
    assert "сумма вознаграждения" in blocked.detail


def test_blocked_contract_never_quotes_internal_text_to_the_client() -> None:
    """Служебный протокол проверок клиенту не показывают."""
    blocked = ContractQualityBlocked(
        [
            "CONTRACT_QA_BLOCK: korgan_contract_validation",
            "FILING_ACTION: внутренняя пометка",
            "Error code: 429 rate_limit_exceeded",
            "перепутаны стороны договора",
        ]
    )

    for leak in ("CONTRACT_QA_BLOCK", "korgan_contract_validation", "FILING_ACTION", "Error code"):
        assert leak not in blocked.detail, blocked.detail
    assert "перепутаны стороны договора" in blocked.detail


def test_block_without_showable_reason_still_explains_itself() -> None:
    """Если показать нечего — остаётся объяснение, а не перечень служебных строк."""
    blocked = ContractQualityBlocked(["korgan_contract_validation", "traceback"])

    assert "Требует уточнения" not in blocked.detail
    assert "финальная юридическая проверка" in blocked.detail
    assert "новая оплата не потребуется" in blocked.detail


def test_blocked_contract_reason_reaches_the_client_through_the_job(monkeypatch) -> None:
    """Причина доходит до строки задачи, а не подменяется общим отказом."""
    from korgan import miniapp_generation_jobs as jobs

    detail = jobs._client_detail(
        ContractQualityBlocked(["перепутаны стороны: исполнитель указан как заказчик"])
    )

    assert detail != jobs._TECHNICAL_FAILURE
    assert "перепутаны стороны" in detail


def test_final_qa_still_blocks_an_unsafe_contract(monkeypatch) -> None:
    """Проверку нельзя обойти: неподтверждённая ссылка на закон не выпускается."""
    from korgan import miniapp_api_v2 as core

    owner = _contract_service()

    async def blocking_validation(case_context, research, draft):
        return {
            "critical_errors": ["перепутаны стороны: исполнитель указан как заказчик"],
            "unsupported_legal_claims": [],
            "missing_essential_terms": [],
        }

    async def fake_research_method(context, language="ru"):
        from korgan.legal_types import LegalResearch, VerificationStatus

        return LegalResearch(
            status=VerificationStatus.NEEDS_VERIFICATION,
            applicable_law=[],
            procedural_requirements=[],
            verified_claims=[],
            unverified_claims=[],
            source_urls=[],
            notes=[],
        )

    monkeypatch.setattr(owner, "validate_contract", blocking_validation, raising=False)
    monkeypatch.setattr(core.legacy.service, "research_contract", fake_research_method, raising=False)

    calls: list[str] = []

    async def fake_structured(*args, **kwargs):
        calls.append(str(kwargs.get("schema_name")))
        return {}, object()

    monkeypatch.setattr(owner, "_structured_response", fake_structured, raising=False)

    with pytest.raises(ContractQualityBlocked) as raised:
        asyncio.run(core._generate("contract", "материалы договора", "ru"))

    assert "перепутаны стороны" in raised.value.detail
    # Один круг починки перед отказом обязателен: отказ — не первая реакция.
    assert len(calls) >= 2, calls


def test_clean_qa_releases_the_contract(monkeypatch) -> None:
    """Исправленные материалы проходят: отказ не становится тупиком.

    Это вторая половина требования. Первая — не выпускать небезопасный договор;
    без этой повтор был бы бессмысленным при любой формулировке отказа.
    """
    import io

    from docx import Document

    from korgan import miniapp_api_v2 as core

    owner = _contract_service()

    async def clean_validation(case_context, research, draft):
        return {"critical_errors": [], "unsupported_legal_claims": [], "missing_essential_terms": []}

    async def fake_research_method(context, language="ru"):
        from korgan.legal_types import LegalResearch, VerificationStatus

        return LegalResearch(
            status=VerificationStatus.NEEDS_VERIFICATION,
            applicable_law=[],
            procedural_requirements=[],
            verified_claims=[],
            unverified_claims=[],
            source_urls=[],
            notes=[],
        )

    async def fake_structured(*args, **kwargs):
        return {
            "contract_type": "Договор поставки",
            "title": "Договор поставки товара",
            "sections": [
                {
                    "heading": "Предмет договора",
                    "clauses": [
                        {
                            "text": "Поставщик обязуется передать покупателю товар, "
                            "а покупатель принять и оплатить его.",
                            "subclauses": [],
                        }
                    ],
                }
            ],
        }, object()

    monkeypatch.setattr(owner, "validate_contract", clean_validation, raising=False)
    monkeypatch.setattr(owner, "_structured_response", fake_structured, raising=False)
    monkeypatch.setattr(core.legacy.service, "research_contract", fake_research_method, raising=False)

    _draft, file_bytes, filename, _meta = asyncio.run(
        core._generate("contract", "материалы договора", "ru")
    )

    assert filename.endswith(".docx")
    assert len(file_bytes) > 5000
    assert Document(io.BytesIO(file_bytes)).paragraphs, "Word не открылся"
