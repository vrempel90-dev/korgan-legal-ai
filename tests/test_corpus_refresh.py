from __future__ import annotations

from pathlib import Path

import pytest

from korgan.legal.corpus import KNOWN_ACTS, LegalCorpus
from korgan.legal.corpus_refresh import (
    AUTOLOAD_ENV,
    REFRESH_HOURS_ENV,
    _is_allowed_adilet_url,
    autoload_enabled,
    refresh_corpus_once,
    refresh_hours,
)


def test_adilet_url_allowlist_is_strict() -> None:
    assert _is_allowed_adilet_url("https://adilet.zan.kz/rus/docs/K1500000377")
    assert _is_allowed_adilet_url("https://www.adilet.zan.kz/rus/docs/K1500000377")
    assert not _is_allowed_adilet_url("http://adilet.zan.kz/rus/docs/K1500000377")
    assert not _is_allowed_adilet_url("https://adilet.zan.kz/eng/docs/K1500000377")
    assert not _is_allowed_adilet_url("https://evil.example/rus/docs/K1500000377")


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_autoload_truthy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(AUTOLOAD_ENV, value)
    assert autoload_enabled()


def test_refresh_hours_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REFRESH_HOURS_ENV, "0.1")
    assert refresh_hours() == 1.0
    monkeypatch.setenv(REFRESH_HOURS_ENV, "99999")
    assert refresh_hours() == 24.0 * 30.0
    monkeypatch.setenv(REFRESH_HOURS_ENV, "bad")
    assert refresh_hours() == 24.0


def test_failed_both_official_sources_keeps_previous_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "corpus.sqlite3"
    target.write_bytes(b"previous-corpus")

    import korgan.legal.corpus_refresh as refresh

    monkeypatch.setattr(
        refresh,
        "fetch_adilet",
        lambda url, timeout=60: (_ for _ in ()).throw(RuntimeError("adilet unavailable")),
    )
    monkeypatch.setattr(
        refresh,
        "fetch_zan",
        lambda act_id, timeout=90: (_ for _ in ()).throw(RuntimeError("zan unavailable")),
    )

    # Сообщение изменилось: сбой отдельного акта теперь не прерывает сборку,
    # а копится, и итоговая ошибка говорит, что не загрузился НИ ОДИН акт.
    # Охраняемое поведение то же — живой корпус остаётся нетронутым.
    with pytest.raises(RuntimeError, match="Ни один акт не загружен"):
        refresh_corpus_once(target)

    assert target.read_bytes() == b"previous-corpus"
    assert not target.with_name(target.name + ".refreshing").exists()


def _fake_load_act(corpus, act_id, html, *, url=None, edition_date=None, articles=None):
    adilet_id, title = KNOWN_ACTS[act_id]
    corpus.upsert_act(
        act_id=act_id,
        adilet_id=adilet_id,
        title_ru=title,
        url=url or f"https://adilet.zan.kz/rus/docs/{adilet_id}",
        edition_date="2026-08-22",
        loaded_at="2026-08-22",
    )
    corpus.upsert_provision(
        act_id=act_id,
        article_no="1",
        item_no=None,
        heading="Тестовая норма",
        body="Тестовая норма достаточной длины для проверки атомарного обновления корпуса KORGAN.",
        edition_date="2026-08-22",
        url=(url or f"https://adilet.zan.kz/rus/docs/{adilet_id}") + "#z1",
        sort_key=0,
    )
    return 1


def _fake_load_act_text(
    corpus,
    act_id,
    text,
    *,
    source_url,
    citation_url=None,
    edition_date=None,
    articles=None,
):
    adilet_id, title = KNOWN_ACTS[act_id]
    corpus.upsert_act(
        act_id=act_id,
        adilet_id=adilet_id,
        title_ru=title,
        url=source_url,
        edition_date="2026-08-22",
        loaded_at="2026-08-22",
    )
    corpus.upsert_provision(
        act_id=act_id,
        article_no="1",
        item_no=None,
        heading="Тестовая норма",
        body="Тестовая норма достаточной длины для проверки официального ZAN fallback KORGAN.",
        edition_date="2026-08-22",
        url=(citation_url or source_url) + "#z1",
        sort_key=0,
    )
    return 1


def test_successful_primary_refresh_never_calls_zan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "corpus.sqlite3"
    import korgan.legal.corpus_refresh as refresh

    monkeypatch.setattr(
        refresh,
        "fetch_adilet",
        lambda url, timeout=60: ("<html>official</html>", url),
    )
    monkeypatch.setattr(refresh, "load_act", _fake_load_act)

    zan_calls = 0

    def unexpected_zan(act_id: str, timeout: int = 90):
        nonlocal zan_calls
        zan_calls += 1
        raise AssertionError("ZAN must not be called when Adilet succeeds")

    monkeypatch.setattr(refresh, "fetch_zan", unexpected_zan)

    total = refresh_corpus_once(target)

    assert total == len(KNOWN_ACTS)
    assert zan_calls == 0
    with LegalCorpus(target) as corpus:
        assert corpus.count() == len(KNOWN_ACTS)


def test_adilet_failure_uses_zan_per_act_and_keeps_canonical_citations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "corpus.sqlite3"
    import korgan.legal.corpus_refresh as refresh

    monkeypatch.setattr(
        refresh,
        "fetch_adilet",
        lambda url, timeout=60: (_ for _ in ()).throw(RuntimeError("railway TLS reset")),
    )
    monkeypatch.setattr(
        refresh,
        "fetch_zan",
        lambda act_id, timeout=90: (
            "Статья 1. Тестовая официальная норма\nТекст нормы для ZAN fallback.",
            f"https://zan.gov.kz/api/documents/{refresh.zan_pdf_url(act_id).split('/')[5]}/rus/download/pdf",
            "2026-08-01",
        ),
    )
    monkeypatch.setattr(refresh, "load_act_text", _fake_load_act_text)

    total = refresh_corpus_once(target)

    assert total == len(KNOWN_ACTS)
    with LegalCorpus(target) as corpus:
        assert corpus.count() == len(KNOWN_ACTS)
        rows = corpus.connection.execute(
            "SELECT a.url AS source_url, p.url AS citation_url FROM acts a JOIN provisions p ON p.act_id = a.act_id"
        ).fetchall()
        assert rows
        assert all("zan.gov.kz/api/documents/" in str(row["source_url"]) for row in rows)
        assert all("adilet.zan.kz/rus/docs/" in str(row["citation_url"]) for row in rows)


def test_successful_refresh_atomically_builds_complete_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "corpus.sqlite3"

    import korgan.legal.corpus_refresh as refresh

    monkeypatch.setattr(
        refresh,
        "fetch_adilet",
        lambda url, timeout=60: ("<html>official</html>", url),
    )
    monkeypatch.setattr(refresh, "load_act", _fake_load_act)

    total = refresh_corpus_once(target)

    assert total == len(KNOWN_ACTS)
    assert target.exists()
    assert not target.with_name(target.name + ".refreshing").exists()
    with LegalCorpus(target) as corpus:
        assert corpus.count() == len(KNOWN_ACTS)
