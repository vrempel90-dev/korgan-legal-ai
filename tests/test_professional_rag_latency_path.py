from __future__ import annotations

import korgan.professional_rag_bridge as rag
from korgan.legal_routing import detect_claim_profile
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.professional_rag_bridge import (
    _compact_consult_research_content,
    _consult_query_from_prompt,
    _preferred_search_context,
    _research_is_sufficient,
    _with_search_context,
)


def _research(*verified: str, urls: tuple[str, ...] = ("https://adilet.zan.kz/rus/docs/K990000409_",)) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(verified),
        unverified_claims=[],
        source_urls=list(urls),
        notes=[],
    )


def test_common_service_dispute_starts_with_low_context() -> None:
    context = "По договору оказания услуг заказчик не оплатил 600 000 тенге."
    assert _preferred_search_context(context) == "low"


def test_complex_labor_dispute_keeps_medium_context() -> None:
    context = "Работодатель не выплатил заработную плату после увольнения."
    assert _preferred_search_context(context) == "medium"


def test_fast_research_requires_material_gk_and_source_bound_result() -> None:
    profile = detect_claim_profile("Договор оказания услуг, долг 600 000 тенге")
    assert not _research_is_sufficient(profile, _research(urls=()))
    assert not _research_is_sufficient(profile, _research())
    assert not _research_is_sufficient(profile, _research("Подсудность [основание: статья 29 ГПК РК]"))
    assert _research_is_sufficient(profile, _research("Оплата услуг подтверждена [основание: статья 685 ГК РК]"))


def test_loan_profile_requires_exact_backbone_articles() -> None:
    profile = detect_claim_profile("Деньги переданы по расписке как займ")
    assert profile.code == "loan_debt"
    incomplete = _research(
        "Форма займа [основание: статья 716 ГК РК]",
        "Возврат займа [основание: статья 722 ГК РК]",
    )
    assert not _research_is_sufficient(profile, incomplete)

    wrong_digits = _research(
        "Иная норма [основание: статья 1715 ГК РК]",
        "Форма займа [основание: статья 716 ГК РК]",
        "Возврат займа [основание: статья 722 ГК РК]",
    )
    assert not _research_is_sufficient(profile, wrong_digits)

    complete = _research(
        "Заем [основание: статья 715 ГК РК]",
        "Форма займа [основание: статья 716 ГК РК]",
        "Возврат займа [основание: статья 722 ГК РК]",
    )
    assert _research_is_sufficient(profile, complete)


def test_search_context_override_does_not_mutate_original_tools() -> None:
    tools = [{"type": "web_search", "search_context_size": "medium", "filters": {"allowed_domains": ["adilet.zan.kz"]}}]
    updated = _with_search_context(tools, "low")
    assert updated[0]["search_context_size"] == "low"
    assert tools[0]["search_context_size"] == "medium"


def test_consult_query_excludes_boilerplate() -> None:
    prompt = (
        "Дата проверки: 2026-08-18. Правила...\n\n"
        "ВОПРОС:\nМожно ли взыскать долг по договору услуг?\n\n"
        "КОНТЕКСТ:\nАкт подписан, 600 000 тенге не оплачены."
    )
    query = _consult_query_from_prompt(prompt)
    assert "Можно ли взыскать долг" in query
    assert "600 000" in query
    assert "Дата проверки" not in query


def test_consult_research_gets_compact_budget_without_changing_authority(monkeypatch) -> None:
    monkeypatch.setattr(rag, "research_from_corpus", lambda *_args, **_kwargs: None)
    original = [{
        "role": "user",
        "content": [{
            "type": "input_text",
            "text": "ВОПРОС:\nМожно ли взыскать долг?\n\nКОНТЕКСТ:\nДоговор услуг, акт подписан.",
        }],
    }]
    updated = _compact_consult_research_content(original)
    text = updated[0]["content"][0]["text"]

    assert "максимум 4 verified_points" in text
    assert "unresolved_facts: максимум 3" in text
    assert "не открывай соседние статьи" in text
    assert "реально открытый Adilet" not in text  # no local candidate was auto-promoted
    assert original[0]["content"][0]["text"].endswith("акт подписан.")
