"""Подключение локального корпуса: включено по умолчанию; Web Search остаётся fallback."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from korgan.legal.corpus import ACT_GK_SPECIAL, ACT_GPK, LegalCorpus  # noqa: E402
from korgan.legal.pipeline import (  # noqa: E402
    FLAG_ENV,
    local_corpus_enabled,
    open_corpus,
    research_from_corpus,
)
from scripts.load_corpus import load_act  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RUS_URL = "https://adilet.zan.kz/rus/docs/K990000409_"


@pytest.fixture()
def corpus(tmp_path: Path) -> LegalCorpus:
    with LegalCorpus(tmp_path / "corpus.sqlite3") as db:
        html = (FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8")
        load_act(db, ACT_GK_SPECIAL, html, url=RUS_URL, edition_date="2026-01-01")
        yield db


@pytest.fixture()
def flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FLAG_ENV, "1")


def test_flag_is_on_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FLAG_ENV, raising=False)
    assert local_corpus_enabled()


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_flag_accepts_common_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(FLAG_ENV, value)
    assert local_corpus_enabled()


@pytest.mark.parametrize("value", ["", "0", "false", "нет"])
def test_flag_stays_off_for_explicit_non_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(FLAG_ENV, value)
    assert not local_corpus_enabled()


def test_disabled_flag_falls_back(corpus: LegalCorpus, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FLAG_ENV, "0")
    assert research_from_corpus("предоплата подряд возврат", corpus=corpus) is None


def test_enabled_flag_returns_offered_provisions(corpus: LegalCorpus, flag_on: None) -> None:
    research = research_from_corpus("предоплата подряд возврат", corpus=corpus)
    assert research is not None
    assert research.provisions
    assert all(corpus.exists(article_id) for article_id in research.offered_ids)
    assert "article_id:" in research.prompt_block


def test_offered_ids_match_the_returned_provisions(corpus: LegalCorpus, flag_on: None) -> None:
    research = research_from_corpus("предоплата подряд возврат", corpus=corpus)
    assert research is not None
    assert research.offered_ids == {p.article_id for p in research.provisions}


def test_source_urls_are_deduplicated(corpus: LegalCorpus, flag_on: None) -> None:
    research = research_from_corpus("подряд заказчик", corpus=corpus)
    assert research is not None
    assert len(research.source_urls) == len(set(research.source_urls))
    assert all(url.startswith("https://adilet.zan.kz/rus/") for url in research.source_urls)


def test_query_without_matches_falls_back(corpus: LegalCorpus, flag_on: None) -> None:
    """Пустая выдача — это «используй старый путь», а не «права нет»."""
    assert research_from_corpus("таможенный транзит контейнеров", corpus=corpus) is None


def test_act_filter_is_passed_through(corpus: LegalCorpus, flag_on: None) -> None:
    assert research_from_corpus("подряд", corpus=corpus, act_id=ACT_GPK) is None
    assert research_from_corpus("подряд", corpus=corpus, act_id=ACT_GK_SPECIAL) is not None


def test_missing_database_falls_back(tmp_path: Path, flag_on: None) -> None:
    assert open_corpus(tmp_path / "absent.sqlite3") is None


def test_empty_database_falls_back(tmp_path: Path, flag_on: None) -> None:
    db_path = tmp_path / "empty.sqlite3"
    with LegalCorpus(db_path):
        pass
    assert open_corpus(db_path) is None


def test_limit_is_respected(corpus: LegalCorpus, flag_on: None) -> None:
    research = research_from_corpus("подряд заказчик работа", corpus=corpus, limit=2)
    assert research is not None
    assert len(research.provisions) <= 2
