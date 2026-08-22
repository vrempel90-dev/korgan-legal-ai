from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from korgan.legal.corpus import (
    ACT_GK_SPECIAL,
    ACT_GPK,
    KNOWN_ACTS,
    LegalCorpus,
)
from korgan.legal.pipeline import CorpusResearch
from korgan.legal.validator import build_offer
from korgan.local_corpus_runtime import research_case_from_local_corpus


def _seed(path: Path) -> list:
    with LegalCorpus(path) as corpus:
        for act_id in (ACT_GK_SPECIAL, ACT_GPK):
            adilet_id, title = KNOWN_ACTS[act_id]
            corpus.upsert_act(
                act_id=act_id,
                adilet_id=adilet_id,
                title_ru=title,
                url=f"https://adilet.zan.kz/rus/docs/{adilet_id}",
                edition_date="2026-08-17",
                loaded_at="2026-08-17",
            )

        rows = [
            (
                ACT_GK_SPECIAL,
                "715",
                "Договор займа",
                "По договору займа одна сторона передает другой стороне деньги, а заемщик обязуется возвратить полученную сумму займа.",
            ),
            (
                ACT_GK_SPECIAL,
                "722",
                "Возврат предмета займа",
                "Заемщик обязан возвратить предмет займа в порядке и сроки, предусмотренные договором займа.",
            ),
            (
                ACT_GPK,
                "148",
                "Форма и содержание иска",
                "Исковое заявление подается в суд в письменной форме и должно содержать предусмотренные настоящей статьей сведения.",
            ),
            (
                ACT_GPK,
                "149",
                "Документы, прилагаемые к иску",
                "К исковому заявлению прилагаются документы, предусмотренные настоящей статьей и подтверждающие заявленные обстоятельства.",
            ),
        ]
        for index, (act_id, article, heading, body) in enumerate(rows):
            corpus.upsert_provision(
                act_id=act_id,
                article_no=article,
                item_no=None,
                heading=heading,
                body=body,
                edition_date="2026-08-17",
                url=f"https://adilet.zan.kz/rus/docs/{KNOWN_ACTS[act_id][0]}#z{article}",
                sort_key=index,
            )

        return [corpus.get(f"{act_id}:{article}") for act_id, article, _, _ in rows]


class FakeService:
    def __init__(self, blocks):
        self.blocks = blocks
        self.settings = SimpleNamespace(openai_model="gpt-test", max_case_text_chars=40000)

    async def _structured_response(self, **kwargs):
        return {"legal_basis": self.blocks}, object()


def test_local_runtime_accepts_only_offered_existing_provisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "corpus.sqlite3"
    provisions = _seed(path)
    offered_ids, prompt_block = build_offer(provisions)
    offered = CorpusResearch(
        provisions=tuple(provisions),
        offered_ids=frozenset(offered_ids),
        prompt_block=prompt_block,
    )

    import korgan.local_corpus_runtime as runtime

    monkeypatch.setattr(runtime, "research_from_corpus", lambda *a, **k: offered)
    monkeypatch.setattr(runtime, "open_corpus", lambda: LegalCorpus(path))

    blocks = [
        {
            "article_id": provision.article_id,
            "thesis": provision.body,
            "link_to_facts": "Норма проверяется применительно к материалам пользователя.",
        }
        for provision in provisions
    ]
    result = asyncio.run(
        research_case_from_local_corpus(
            FakeService(blocks),
            "Истец передал ответчику деньги по договору займа и требует возврата.",
        )
    )

    assert result is not None
    assert result.status.value == "VERIFIED"
    assert any("715" in claim for claim in result.verified_claims)
    assert any("722" in claim for claim in result.verified_claims)
    assert any("148" in claim for claim in result.verified_claims)
    assert any("149" in claim for claim in result.verified_claims)
    assert all(url.startswith("https://adilet.zan.kz/rus/") for url in result.source_urls)


def test_local_runtime_rejects_unknown_article_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "corpus.sqlite3"
    provisions = _seed(path)
    offered_ids, prompt_block = build_offer(provisions)
    offered = CorpusResearch(tuple(provisions), frozenset(offered_ids), prompt_block)

    import korgan.local_corpus_runtime as runtime

    monkeypatch.setattr(runtime, "research_from_corpus", lambda *a, **k: offered)
    monkeypatch.setattr(runtime, "open_corpus", lambda: LegalCorpus(path))
    service = FakeService(
        [{"article_id": "GK_RK_OSOBENNAYA:9999", "thesis": "Неизвестная норма.", "link_to_facts": ""}]
    )

    assert asyncio.run(research_case_from_local_corpus(service, "займ")) is None


def test_local_runtime_rejects_paraphrase_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "corpus.sqlite3"
    provisions = _seed(path)
    provision = next(p for p in provisions if p.article_no == "715")
    offered_ids, prompt_block = build_offer([provision])
    offered = CorpusResearch((provision,), frozenset(offered_ids), prompt_block)

    import korgan.local_corpus_runtime as runtime

    monkeypatch.setattr(runtime, "research_from_corpus", lambda *a, **k: offered)
    monkeypatch.setattr(runtime, "open_corpus", lambda: LegalCorpus(path))
    service = FakeService(
        [{
            "article_id": provision.article_id,
            "thesis": "Заемщик обязан уплатить штраф и возвратить полученную сумму займа.",
            "link_to_facts": "",
        }]
    )

    assert asyncio.run(research_case_from_local_corpus(service, "займ")) is None
