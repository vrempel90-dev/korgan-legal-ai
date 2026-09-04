from __future__ import annotations

import asyncio

import pytest

from korgan.legal.corpus import ACT_GK_GENERAL, LegalCorpus


def _build_corpus(path, *, source_url: str = "https://adilet.zan.kz/rus/docs/K940001000_") -> None:
    with LegalCorpus(path) as corpus:
        corpus.upsert_act(
            act_id=ACT_GK_GENERAL,
            adilet_id="K940001000_",
            title_ru="Гражданский кодекс Республики Казахстан (Общая часть)",
            url=source_url,
            edition_date="2026-09-01",
            loaded_at="2026-09-04",
        )
        corpus.upsert_provision(
            act_id=ACT_GK_GENERAL,
            article_no="272",
            item_no=None,
            heading="Надлежащее исполнение обязательства",
            body=(
                "Обязательство должно исполняться надлежащим образом в соответствии "
                "с условиями обязательства и требованиями законодательства."
            ),
            edition_date="2026-09-01",
            url="https://adilet.zan.kz/rus/docs/K940001000_#z272",
            sort_key=272,
        )


def test_stable_release_loads_exact_act_from_verified_official_corpus(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from korgan import live_article_release_stable_runtime as stable

    db_path = tmp_path / "corpus.sqlite3"
    _build_corpus(db_path)
    monkeypatch.setattr(stable.pipeline, "open_corpus", lambda: LegalCorpus(db_path))

    act = stable.load_official_corpus_act(ACT_GK_GENERAL)

    assert act is not None
    assert act.act_id == ACT_GK_GENERAL
    assert act.edition_date == "2026-09-01"
    assert "272" in act.articles
    assert "надлежащим образом" in act.articles["272"][""]


def test_stable_release_does_not_call_network_when_verified_corpus_act_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    from korgan import live_article_release_runtime as runtime
    from korgan import live_article_release_stable_runtime as stable

    corpus_act = runtime.LiveAct(
        act_id=ACT_GK_GENERAL,
        source_url="https://adilet.zan.kz/rus/docs/K940001000_",
        edition_date="2026-09-01",
        articles={"272": {"": "Проверенный текст нормы."}},
    )
    monkeypatch.setattr(stable, "load_official_corpus_act", lambda act_id: corpus_act)

    async def forbidden_network(act_id: str):
        raise AssertionError(f"network must not be called for {act_id}")

    monkeypatch.setattr(stable, "_NETWORK_LIVE_ACT", forbidden_network)
    resolved = asyncio.run(stable._stable_live_act(ACT_GK_GENERAL))
    assert resolved is corpus_act


def test_stable_release_falls_back_to_existing_live_verifier_when_corpus_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from korgan import live_article_release_runtime as runtime
    from korgan import live_article_release_stable_runtime as stable

    live = runtime.LiveAct(
        act_id=ACT_GK_GENERAL,
        source_url="https://adilet.zan.kz/rus/docs/K940001000_",
        edition_date="2026-09-04",
        articles={"272": {"": "Живой текст нормы."}},
    )
    monkeypatch.setattr(stable, "load_official_corpus_act", lambda act_id: None)

    async def network(act_id: str):
        assert act_id == ACT_GK_GENERAL
        return live

    monkeypatch.setattr(stable, "_NETWORK_LIVE_ACT", network)
    assert asyncio.run(stable._stable_live_act(ACT_GK_GENERAL)) is live


def test_stable_release_rejects_non_official_corpus_provenance(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from korgan import live_article_release_stable_runtime as stable

    db_path = tmp_path / "corpus.sqlite3"
    _build_corpus(db_path, source_url="https://example.com/not-official")
    monkeypatch.setattr(stable.pipeline, "open_corpus", lambda: LegalCorpus(db_path))

    assert stable.load_official_corpus_act(ACT_GK_GENERAL) is None
