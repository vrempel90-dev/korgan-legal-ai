from __future__ import annotations

from pathlib import Path

import pytest

from korgan.legal.corpus import LegalCorpus
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.production_cost_speed_optimizer import (
    _all_issues_external_only,
    _corpus_act_ids,
    _economic_court_candidate,
    _merge_staged_act,
    _progressive_refresh_factory,
    _strong_rag_prompt,
)


def _research(*verified: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(verified),
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="И С К о взыскании задолженности",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: суд]",
        claimant=["Истец: ТОО «СтройИнжиниринг KZ»"],
        defendant=["Ответчик: ТОО «Астана Девелопмент»"],
        price_of_claim="8 400 000 тенге",
        state_duty="",
        facts=[],
        legal_basis=[],
        requests=["Взыскать задолженность 8 400 000 тенге."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def _add_act(path: Path, act_id: str, article_no: str = "1") -> None:
    with LegalCorpus(path) as corpus:
        corpus.upsert_act(
            act_id=act_id,
            adilet_id=f"DOC-{act_id}",
            title_ru=f"Act {act_id}",
            url=f"https://adilet.zan.kz/rus/docs/{act_id}",
            edition_date="2026-08-25",
            loaded_at="2026-08-25",
        )
        corpus.upsert_provision(
            act_id=act_id,
            article_no=article_no,
            item_no=None,
            heading="Тестовая статья",
            body="Проверенный текст нормы для теста.",
            edition_date="2026-08-25",
            url=f"https://adilet.zan.kz/rus/docs/{act_id}",
            sort_key=1,
        )


def test_strong_rag_switch_requires_material_and_gpk_candidates():
    blocks = [
        "article_id: GK_RK_OBSHAYA:272",
        "article_id: GK_RK_OSOBENNAYA:616",
        "article_id: GK_RK_OSOBENNAYA:621",
        "article_id: GPK_RK:27",
        "article_id: GPK_RK:29",
        "article_id: GPK_RK:148",
    ]
    content = "ЛОКАЛЬНЫЕ RAG-КАНДИДАТЫ ИЗ КОРПУСА ADILET\n" + "\n".join(blocks)
    assert _strong_rag_prompt(content) is True

    no_gpk = content.replace("GPK_RK:", "GK_RK_OBSHAYA:")
    assert _strong_rag_prompt(no_gpk) is False
    assert _strong_rag_prompt("обычный prompt без локального RAG") is False


def test_only_nonrepairable_missing_external_data_can_skip_ai_repair():
    assert _all_issues_external_only([
        "не определено конкретное наименование суда",
        "не указан адрес ответчика",
    ]) is True

    assert _all_issues_external_only([
        "не определено конкретное наименование суда",
        "отсутствует правовое обоснование по материальному праву",
    ]) is False

    assert _all_issues_external_only([
        "Пользователь просил взыскать пеню, но требование исчезло из ПРОШУ СУД"
    ]) is False


def test_verified_staged_act_is_merged_atomically_into_live_corpus(tmp_path: Path):
    live = tmp_path / "corpus.sqlite3"
    staged = tmp_path / "staged.sqlite3"
    _add_act(staged, "GK_TEST", "272")

    merged = _merge_staged_act(live, staged, "GK_TEST")
    assert merged == 1
    assert _corpus_act_ids(live) == {"GK_TEST"}

    with LegalCorpus(live) as corpus:
        assert corpus.count("GK_TEST") == 1
        provision = corpus.get("GK_TEST:272")
        assert provision is not None
        assert provision.article_no == "272"


def test_progressive_bootstrap_keeps_verified_act_when_another_source_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from korgan import production_cost_speed_optimizer as optimizer

    target = tmp_path / "corpus.sqlite3"
    monkeypatch.setattr(optimizer, "KNOWN_ACTS", {"A_OK": ("1", "OK"), "B_FAIL": ("2", "FAIL")})

    def original(_path):
        raise AssertionError("complete atomic refresh must not run for an incomplete corpus")

    def loader(corpus: LegalCorpus, act_id: str):
        if act_id == "B_FAIL":
            raise RuntimeError("official source unavailable")
        corpus.upsert_act(
            act_id=act_id,
            adilet_id="DOC",
            title_ru="Verified act",
            url="https://adilet.zan.kz/rus/docs/DOC",
            edition_date="2026-08-25",
            loaded_at="2026-08-25",
        )
        corpus.upsert_provision(
            act_id=act_id,
            article_no="1",
            item_no=None,
            heading="Норма",
            body="Проверенный текст.",
            edition_date="2026-08-25",
            url="https://adilet.zan.kz/rus/docs/DOC",
            sort_key=1,
        )
        return 1, "adilet", "https://adilet.zan.kz/rus/docs/DOC"

    progressive = _progressive_refresh_factory(original, loader)
    total = progressive(target)

    assert total == 1
    assert _corpus_act_ids(target) == {"A_OK"}


def test_common_too_vs_too_astana_route_uses_verified_economic_registry():
    research = _research(
        "Специализированные межрайонные экономические суды рассматривают соответствующие споры юридических лиц [основание: статья 27 ГПК РК; текст нормы: «...»; источник: https://adilet.zan.kz/rus/docs/K1500000377]",
        "Иск предъявляется по месту нахождения ответчика [основание: статья 29 ГПК РК; текст нормы: «...»; источник: https://adilet.zan.kz/rus/docs/K1500000377]",
    )
    draft = _draft()
    context = "Истец — ТОО. Ответчик — ТОО. Обе компании зарегистрированы в г. Астана."

    candidate = _economic_court_candidate(context, research, draft)

    assert candidate is not None
    assert candidate["court"] == "Специализированный межрайонный экономический суд города Астаны"
    assert candidate["jurisdiction"] == "economic"


def test_economic_registry_does_not_guess_without_verified_venue():
    research = _research(
        "Экономические суды рассматривают часть споров [основание: статья 27 ГПК РК; текст нормы: «...»; источник: https://adilet.zan.kz/rus/docs/K1500000377]"
    )
    assert _economic_court_candidate(
        "Обе компании зарегистрированы в г. Астана.", research, _draft()
    ) is None
