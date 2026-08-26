from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.professional_rag_bridge import _research_local_first


def _verified_local() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=["Гражданский кодекс Республики Казахстан"],
        procedural_requirements=["Иск должен соответствовать требованиям ГПК."],
        verified_claims=[
            "Возврат долга подтверждён нормой из текущего локального корпуса.",
            "Процессуальное требование подтверждено нормой из текущего локального корпуса.",
        ],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
        notes=[
            "CASE_THEORY: взыскание подтверждённого договорного долга",
            "REMEDY: взыскать основной долг",
        ],
    )


def test_complete_verified_local_research_skips_web_fallback(monkeypatch) -> None:
    import korgan.local_corpus_runtime as runtime

    calls = {"local": 0, "web": 0}
    seen_kwargs: dict[str, object] = {}

    async def local(service, case_context, language="ru", **kwargs):
        calls["local"] += 1
        seen_kwargs.update(kwargs)
        return _verified_local()

    async def web(service, case_context, language="ru"):
        calls["web"] += 1
        raise AssertionError("web research must not run for a complete validated local hit")

    monkeypatch.setattr(runtime, "research_case_from_local_corpus", local)
    service = SimpleNamespace()
    result = asyncio.run(
        _research_local_first(service, web, "Истец просит взыскать долг по иску.", "ru")
    )

    assert result.status == VerificationStatus.VERIFIED
    assert calls == {"local": 1, "web": 0}
    assert seen_kwargs.get("require_complete_coverage") is True


def test_incomplete_local_research_preserves_original_web_path(monkeypatch) -> None:
    import korgan.local_corpus_runtime as runtime

    calls = {"local": 0, "web": 0}
    expected = LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=["web fallback result"],
        source_urls=[],
        notes=[],
    )

    async def local(service, case_context, language="ru", **kwargs):
        calls["local"] += 1
        return None

    async def web(service, case_context, language="ru"):
        calls["web"] += 1
        return expected

    monkeypatch.setattr(runtime, "research_case_from_local_corpus", local)
    result = asyncio.run(_research_local_first(SimpleNamespace(), web, "редкий спор", "ru"))

    assert result is expected
    assert calls == {"local": 1, "web": 1}


def test_local_needs_verification_cannot_bypass_web_fallback(monkeypatch) -> None:
    import korgan.local_corpus_runtime as runtime

    calls = {"web": 0}
    weak = _verified_local()
    weak.status = VerificationStatus.NEEDS_VERIFICATION
    weak.unverified_claims.append("Нужна норма вне локального корпуса.")

    async def local(service, case_context, language="ru", **kwargs):
        return weak

    async def web(service, case_context, language="ru"):
        calls["web"] += 1
        return _verified_local()

    monkeypatch.setattr(runtime, "research_case_from_local_corpus", local)
    result = asyncio.run(_research_local_first(SimpleNamespace(), web, "иск", "ru"))

    assert calls["web"] == 1
    assert result.status == VerificationStatus.VERIFIED
