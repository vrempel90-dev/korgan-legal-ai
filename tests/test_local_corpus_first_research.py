from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.legal.corpus import ACT_GPK
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


def _local_payload(**overrides):
    payload = {
        "legal_basis": [{
            "article_id": "offered-1",
            "thesis": "Проверенная норма применяется к спору.",
            "link_to_facts": "Связь с фактами пользователя.",
        }],
        "coverage_complete": True,
        "coverage_gaps": [],
        "case_theory": ["Иск о взыскании подтверждённого долга."],
        "remedies": ["Взыскать подтверждённую сумму долга."],
        "evidence_map": ["Приложить договор и подтверждение оплаты."],
        "risks": ["Оценить возражения ответчика."],
    }
    payload.update(overrides)
    return payload


def _run_strict_local(monkeypatch, payload, *, act_id=ACT_GPK, leaked=None):
    import korgan.local_corpus_runtime as runtime

    offered = SimpleNamespace(prompt_block="offered corpus", offered_ids=("offered-1",))

    class Corpus:
        def close(self) -> None:
            return None

    provision = SimpleNamespace(
        act_id=act_id,
        body="Проверенная норма применяется к спору.",
        url="https://adilet.zan.kz/rus/docs/test",
        act_title="Тестовый нормативный акт",
        label=lambda: "статья 1",
    )
    accepted = SimpleNamespace(
        article_id="offered-1",
        thesis="Проверенная норма применяется к спору.",
        provision=provision,
    )
    validation = SimpleNamespace(rejected=[], accepted=[accepted])

    monkeypatch.setattr(runtime, "research_from_corpus", lambda *args, **kwargs: offered)
    monkeypatch.setattr(runtime, "open_corpus", lambda: Corpus())
    monkeypatch.setattr(runtime, "validate_blocks", lambda *args, **kwargs: validation)
    monkeypatch.setattr(runtime, "paraphrase_defects", lambda *args, **kwargs: [])
    monkeypatch.setattr(runtime, "verified_claim_line", lambda *args, **kwargs: "verified claim")
    monkeypatch.setattr(
        runtime,
        "find_unvalidated_citations",
        lambda rendered, validation_result: leaked(rendered) if leaked else [],
    )

    class Service:
        settings = SimpleNamespace(max_case_text_chars=60000, openai_model="test-model")

        async def _structured_response(self, **kwargs):
            return payload, None

    return asyncio.run(
        runtime.research_case_from_local_corpus(
            Service(),
            "Истец обращается в суд и просит взыскать долг.",
            require_complete_coverage=True,
        )
    )


def test_strict_local_corpus_rejects_each_incomplete_coverage_shape(monkeypatch) -> None:
    invalid_payloads = [
        _local_payload(coverage_complete=False),
        _local_payload(coverage_gaps=["Нужна дополнительная норма."]),
        _local_payload(case_theory=[]),
        _local_payload(remedies=[]),
    ]
    for payload in invalid_payloads:
        assert _run_strict_local(monkeypatch, payload) is None


def test_strict_local_corpus_rejects_litigation_without_gpk(monkeypatch) -> None:
    assert _run_strict_local(monkeypatch, _local_payload(), act_id="civil-code") is None


def test_strict_local_corpus_rejects_unoffered_citation_in_strategy(monkeypatch) -> None:
    payload = _local_payload(risks=["Проверить применение статьи 999 ГК."])
    seen = {"strategy_scanned": False}

    def leaked(rendered: str) -> list[str]:
        seen["strategy_scanned"] = "статьи 999" in rendered
        return ["статья 999"] if seen["strategy_scanned"] else []

    assert _run_strict_local(monkeypatch, payload, leaked=leaked) is None
    assert seen["strategy_scanned"] is True