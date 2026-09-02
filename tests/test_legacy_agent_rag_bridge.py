from __future__ import annotations

from types import SimpleNamespace

from korgan import legacy_agent_rag_bridge as bridge
from korgan.openai_legal import OpenAILegalService


def test_bridge_is_installed_on_live_openai_service() -> None:
    assert getattr(OpenAILegalService, bridge._INSTALLED_ATTR, False) is True


def test_candidate_context_is_explicitly_non_authoritative(monkeypatch) -> None:
    monkeypatch.setattr(
        bridge,
        "research_from_corpus",
        lambda query, limit=12: SimpleNamespace(
            prompt_block=(
                "article_id: RAGKZ_test:272\n"
                "ст. 272 ГК РК\n"
                "Обязательство должно исполняться надлежащим образом."
            )
        ),
    )

    block = bridge._candidate_context("нарушение обязательства")

    assert "ТОЛЬКО ПОИСКОВЫЕ КАНДИДАТЫ" in block
    assert "НЕ является VERIFIED-правом" in block
    assert "source-bound web search" in block
    assert "RAGKZ_test:272" in block


def test_empty_local_retrieval_does_not_modify_case_context(monkeypatch) -> None:
    monkeypatch.setattr(bridge, "research_from_corpus", lambda query, limit=12: None)

    original = "Факты дела"
    assert bridge._augment_context(original, "вопрос") == original


def test_candidate_context_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(
        bridge,
        "research_from_corpus",
        lambda query, limit=12: SimpleNamespace(prompt_block="X" * (bridge._MAX_HINT_CHARS + 5000)),
    )

    block = bridge._candidate_context("вопрос")

    assert "X" * bridge._MAX_HINT_CHARS in block
    assert "X" * (bridge._MAX_HINT_CHARS + 1) not in block
