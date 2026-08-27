from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.consultation_local_corpus_bridge import _consult_local_first
from korgan.legal_types import LegalResearch, VerificationStatus


def _local_research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=["Гражданский кодекс Республики Казахстан"],
        procedural_requirements=[],
        verified_claims=["Проверенный локальный правовой вывод [источник: https://adilet.zan.kz/rus/docs/example]"],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/example"],
        notes=["REMEDY: Соберите договор и подтверждение исполнения обязательства."],
    )


def test_consultation_complete_local_hit_skips_web_fallback(monkeypatch) -> None:
    import korgan.local_corpus_runtime as runtime

    calls = {"local": 0, "web": 0}
    seen: dict[str, object] = {}

    async def local(service, case_context, language="ru", **kwargs):
        calls["local"] += 1
        seen.update(kwargs)
        return _local_research()

    async def web(service, question, case_context="", language="ru"):
        calls["web"] += 1
        raise AssertionError("web consultation must not run after a complete validated local hit")

    monkeypatch.setattr(runtime, "research_case_from_local_corpus", local)
    answer, urls = asyncio.run(
        _consult_local_first(SimpleNamespace(), web, "Как взыскать долг?", language="ru")
    )

    assert calls == {"local": 1, "web": 0}
    assert seen.get("require_complete_coverage") is True
    assert "Подтверждено по действующему праву РК" in answer
    assert urls == ["https://adilet.zan.kz/rus/docs/example"]


def test_consultation_local_gap_uses_existing_guarded_web_path(monkeypatch) -> None:
    import korgan.local_corpus_runtime as runtime

    calls = {"web": 0}

    async def local(service, case_context, language="ru", **kwargs):
        return None

    async def web(service, question, case_context="", language="ru"):
        calls["web"] += 1
        return "WEB-GUARDED", ["https://adilet.zan.kz/rus/docs/fallback"]

    monkeypatch.setattr(runtime, "research_case_from_local_corpus", local)
    result = asyncio.run(
        _consult_local_first(SimpleNamespace(), web, "Редкий специальный вопрос", language="ru")
    )

    assert calls["web"] == 1
    assert result == ("WEB-GUARDED", ["https://adilet.zan.kz/rus/docs/fallback"])
