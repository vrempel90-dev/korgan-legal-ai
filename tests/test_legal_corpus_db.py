"""Блок 1: локальный корпус норм (SQLite + FTS5) и загрузчик с adilet."""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from korgan.legal.corpus import (  # noqa: E402
    ACT_GK_SPECIAL,
    ACT_GPK,
    ACT_TAX_DUTY,
    LegalCorpus,
    compile_query,
    make_article_id,
)
from scripts.load_corpus import (  # noqa: E402
    SourceRejected,
    check_source,
    cyrillic_share,
    parse_provisions,
    load_act,
    strip_html,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RUS_URL = "https://adilet.zan.kz/rus/docs/K990000409_"
ENG_URL = "https://adilet.zan.kz/eng/docs/K990000409_"


@pytest.fixture()
def corpus(tmp_path: Path) -> LegalCorpus:
    with LegalCorpus(tmp_path / "corpus.sqlite3") as db:
        yield db


@pytest.fixture()
def loaded_corpus(corpus: LegalCorpus) -> LegalCorpus:
    html = (FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8")
    load_act(corpus, ACT_GK_SPECIAL, html, url=RUS_URL, edition_date="2026-01-01")
    return corpus


# --- разбор страницы ---------------------------------------------------------


def test_strip_html_drops_scripts_and_styles() -> None:
    text = strip_html((FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8"))

    assert "Статья 616. Договор подряда" in text
    assert "analytics" not in text
    assert "display: none" not in text


def test_parse_splits_articles_and_items() -> None:
    text = strip_html((FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8"))

    provisions = parse_provisions(text)

    articles = {p.article_no for p in provisions}
    assert articles == {"616", "621", "630", "683"}
    # 616: 2 пункта, 621: 3, 630: 2, 683: без пунктов — 8 норм.
    assert len(provisions) == 8

    item_621 = [p for p in provisions if p.article_no == "621"]
    assert [p.item_no for p in item_621] == ["1", "2", "3"]
    assert all(p.heading == "Цена работы и порядок оплаты" for p in item_621)


def test_article_without_items_is_stored_whole() -> None:
    text = strip_html((FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8"))

    single = [p for p in parse_provisions(text) if p.article_no == "683"]

    assert len(single) == 1
    assert single[0].item_no is None
    assert "возмездного оказания услуг" in single[0].body


def test_article_filter_limits_the_load() -> None:
    """Налоговый кодекс грузится только в части госпошлины в судах."""
    text = strip_html((FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8"))

    provisions = parse_provisions(text, articles={"621"})

    assert {p.article_no for p in provisions} == {"621"}


# --- отбраковка источника ----------------------------------------------------


def test_non_adilet_source_is_rejected() -> None:
    with pytest.raises(SourceRejected, match="не adilet"):
        check_source("https://online.zakon.kz/document/?doc_id=1013880", "Статья 616. Договор подряда")


def test_english_url_is_rejected() -> None:
    text = strip_html((FIXTURES / "adilet_gk_english.html").read_text(encoding="utf-8"))

    with pytest.raises(SourceRejected, match="не русская редакция"):
        check_source(ENG_URL, text)


def test_english_text_on_russian_url_is_rejected() -> None:
    """Перевод кодекса парсится не хуже оригинала — язык проверяется по содержанию."""
    text = strip_html((FIXTURES / "adilet_gk_english.html").read_text(encoding="utf-8"))

    with pytest.raises(SourceRejected, match="доля кириллицы"):
        check_source(RUS_URL, text)


def test_page_without_articles_is_rejected() -> None:
    with pytest.raises(SourceRejected, match="не найдено ни одной"):
        check_source(RUS_URL, "Обычная страница сайта без текста нормативного акта и его статей.")


def test_cyrillic_share_separates_editions() -> None:
    russian = strip_html((FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8"))
    english = strip_html((FIXTURES / "adilet_gk_english.html").read_text(encoding="utf-8"))

    assert cyrillic_share(russian) > 0.9
    assert cyrillic_share(english) < 0.2


def test_unknown_act_is_rejected(corpus: LegalCorpus) -> None:
    with pytest.raises(SourceRejected, match="не входит в список"):
        load_act(corpus, "UK_RK", "<p>Статья 1. Что-то</p>", url=RUS_URL)


# --- хранение и поиск --------------------------------------------------------


def test_load_act_fills_the_corpus(loaded_corpus: LegalCorpus) -> None:
    assert loaded_corpus.count() == 8
    assert loaded_corpus.count(ACT_GK_SPECIAL) == 8


def test_article_id_is_stable_across_reloads(loaded_corpus: LegalCorpus) -> None:
    html = (FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8")
    before = {p.article_id for p in loaded_corpus.search("подряд")}

    load_act(loaded_corpus, ACT_GK_SPECIAL, html, url=RUS_URL, edition_date="2026-02-01")

    assert {p.article_id for p in loaded_corpus.search("подряд")} == before
    assert loaded_corpus.count() == 8


def test_get_and_exists_use_the_article_id(loaded_corpus: LegalCorpus) -> None:
    article_id = make_article_id(ACT_GK_SPECIAL, "621", "2")

    provision = loaded_corpus.get(article_id)

    assert loaded_corpus.exists(article_id)
    assert provision is not None
    assert provision.article_no == "621"
    assert provision.item_no == "2"
    assert "предоплата" in provision.body
    assert provision.url.endswith("#z621")
    assert provision.edition_date == "2026-01-01"


def test_missing_article_id_does_not_exist(loaded_corpus: LegalCorpus) -> None:
    assert not loaded_corpus.exists(make_article_id(ACT_GK_SPECIAL, "9999"))
    assert loaded_corpus.get(make_article_id(ACT_GK_SPECIAL, "9999")) is None


def test_provision_label_names_article_and_item(loaded_corpus: LegalCorpus) -> None:
    provision = loaded_corpus.get(make_article_id(ACT_GK_SPECIAL, "621", "2"))

    assert provision is not None
    # Сокращение, а не полное имя акта: в судебном тексте оно не склоняется.
    assert provision.label() == "ст. 621 ГК РК (Особенная часть), п. 2"


def test_readiness_query_returns_profile_articles(loaded_corpus: LegalCorpus) -> None:
    """Критерий готовности: «предоплата подряд возврат» → профильные статьи ГК РК."""
    results = loaded_corpus.search("предоплата подряд возврат")

    assert results, "поиск ничего не нашёл"
    articles = [p.article_no for p in results]
    # Норма о возврате неотработанной предоплаты по подряду обязана попасть в выдачу.
    assert "630" in articles
    assert "621" in articles


def test_search_matches_inflected_forms(loaded_corpus: LegalCorpus) -> None:
    """В корпусе «предоплаты», запрос — «предоплата»: без стемминга FTS5 не найдёт."""
    assert loaded_corpus.search("предоплата")
    assert loaded_corpus.search("возврат предоплаты")


def test_search_can_be_filtered_by_act(loaded_corpus: LegalCorpus) -> None:
    assert loaded_corpus.search("подряд", act_id=ACT_GK_SPECIAL)
    assert loaded_corpus.search("подряд", act_id=ACT_GPK) == []


def test_search_limit_is_respected(loaded_corpus: LegalCorpus) -> None:
    assert len(loaded_corpus.search("подряд заказчик работа", limit=2)) <= 2


def test_empty_query_returns_nothing(loaded_corpus: LegalCorpus) -> None:
    assert loaded_corpus.search("   ") == []


def test_compile_query_builds_prefix_terms() -> None:
    # OR, а не AND: профильная норма может содержать не все слова запроса,
    # порядок выдачи задаёт bm25.
    assert compile_query("предоплата подряд возврат") == "предопла* OR подря* OR возвр*"
    assert compile_query("иск") == "иск*"
    assert compile_query("   ") == ""


def test_search_is_under_100ms_on_5000_provisions(tmp_path: Path) -> None:
    """Критерий готовности: поиск быстрее 100 мс."""
    with LegalCorpus(tmp_path / "bench.sqlite3") as db:
        db.upsert_act(
            act_id=ACT_TAX_DUTY,
            adilet_id="K2500000214",
            title_ru="Налоговый кодекс",
            url="https://adilet.zan.kz/rus/docs/K2500000214",
            edition_date="2026-01-01",
            loaded_at="2026-01-01",
        )
        for index in range(5000):
            db.upsert_provision(
                act_id=ACT_TAX_DUTY,
                article_no=str(600 + index),
                item_no=None,
                heading=f"Норма {index} о государственной пошлине",
                body=(
                    f"Пункт {index}. Предоплата по договору подряда, возврат аванса, "
                    "государственная пошлина и порядок исчисления сроков."
                ),
                edition_date="2026-01-01",
                url="https://adilet.zan.kz/rus/docs/K2500000214",
                sort_key=index,
            )

        started = time.perf_counter()
        results = db.search("предоплата подряд возврат", limit=20)
        elapsed_ms = (time.perf_counter() - started) * 1000

    assert results
    assert elapsed_ms < 100, f"поиск занял {elapsed_ms:.1f} мс"
