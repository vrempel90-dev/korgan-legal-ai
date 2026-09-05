"""Число обращений к модели — это и есть время подготовки документа.

Детерминированные слои занимают десятки миллисекунд; всё остальное — ожидание
ответа провайдера. Поэтому бюджет латентности сторожится здесь как счётчик
вызовов: лишний вызов стоит клиенту десятков секунд, и добавить его случайно
проще всего.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from korgan import miniapp_api_v2 as core
from tests.test_document_generation_e2e import CONTEXT, _fill, _service_objects


class _Response:
    def __init__(self, text: str) -> None:
        self.output_text = text
        self.output: list[Any] = []
        self.usage = None


class _CountingResponses:
    def __init__(self, owner: "CountingProvider") -> None:
        self._owner = owner

    async def create(self, **kwargs: Any) -> _Response:
        fmt = (kwargs.get("text") or {}).get("format") or {}
        self._owner.schemas.append(str(fmt.get("name") or ""))
        schema = fmt.get("schema") or {"type": "object", "properties": {}}
        return _Response(json.dumps(_fill(schema), ensure_ascii=False))


class CountingProvider:
    def __init__(self) -> None:
        self.schemas: list[str] = []
        self.responses = _CountingResponses(self)


@pytest.fixture()
def counting_provider(monkeypatch: pytest.MonkeyPatch) -> CountingProvider:
    from korgan import openai_legal

    fake = CountingProvider()
    monkeypatch.setattr(openai_legal, "build_legal_client", lambda settings: (fake, "fake"))
    for target in _service_objects():
        monkeypatch.setattr(target, "client", fake, raising=False)
    return fake


#: Нормальный путь — исследование, черновик и не более одной доработки.
#: Доработка вызывается только по замечаниям проверки; в этом наборе черновик
#: собирается из схемы и замечания получает всегда, поэтому три — это потолок.
_MAX_MODEL_CALLS = 3


@pytest.mark.parametrize("document_type", ["claim", "pretrial", "pretrial_response"])
def test_document_costs_no_more_than_three_model_calls(counting_provider, document_type: str) -> None:
    asyncio.run(core._generate(document_type, CONTEXT, "ru"))
    assert len(counting_provider.schemas) <= _MAX_MODEL_CALLS, counting_provider.schemas


@pytest.mark.parametrize("document_type", ["claim", "pretrial", "pretrial_response"])
def test_research_runs_once_per_document(counting_provider, document_type: str) -> None:
    """Повторное исследование по тем же материалам — чистая потеря минуты."""
    asyncio.run(core._generate(document_type, CONTEXT, "ru"))
    research_calls = [name for name in counting_provider.schemas if "research" in name]
    assert len(research_calls) == 1, counting_provider.schemas


def test_repair_is_the_last_call_and_never_the_first(counting_provider) -> None:
    """Доработка — исключение после проверки, а не обычный шаг конвейера."""
    asyncio.run(core._generate("claim", CONTEXT, "ru"))
    repairs = [name for name in counting_provider.schemas if "repair" in name or "10_of_10" in name]
    if repairs:
        assert counting_provider.schemas.index(repairs[0]) >= 2, counting_provider.schemas


def test_clean_draft_needs_no_repair_call() -> None:
    """Когда проверка не нашла замечаний, доработка не запускается вовсе."""
    from korgan.legal_types import LegalResearch, VerificationStatus
    from korgan.universal_word_quality_guard import repair_pretrial_to_target
    from korgan.pretrial import PretrialDraft

    verified = (
        "Покупатель обязан оплатить принятый товар "
        "[основание: статья 439 ГК РК (Особенная часть); "
        "текст нормы: «Покупатель обязан оплатить товар непосредственно до или после "
        "передачи ему продавцом товара»; источник: https://adilet.zan.kz/rus/docs/K990000409_]"
    )
    research = LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=["статья 439 ГК РК (Особенная часть)"],
        procedural_requirements=[],
        verified_claims=[verified],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
        notes=[],
    )
    clean = PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="ПРЕТЕНЗИЯ",
        sender=["ТОО «Альфа Трейд»"],
        recipient=["ТОО «Бета Снаб»"],
        facts=["15.01.2026 поставлен товар, оплата не произведена."],
        legal_basis=[
            "Покупатель обязан оплатить принятый товар. "
            "Правовое основание: статья 439 ГК РК (Особенная часть)."
        ],
        demands=["Требуем оплатить задолженность."],
        deadline="10 календарных дней с момента получения претензии.",
        consequences=["При неисполнении требование будет заявлено в суд."],
        attachments=["Договор поставки №12"],
        verification_notes=[],
        source_urls=[],
        calculation=[],
    )

    calls: list[int] = []

    class _Service:
        async def _quality_repair(self, **_kwargs):
            calls.append(1)
            raise AssertionError("доработка не должна вызываться для чистого черновика")

    async def original(_self, _context, _research, language="ru"):
        return clean

    result = asyncio.run(
        repair_pretrial_to_target(_Service(), original, "материалы", research, "ru")
    )
    assert result is clean
    assert calls == []
