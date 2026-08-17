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


def test_failed_refresh_keeps_previous_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "corpus.sqlite3"
    target.write_bytes(b"previous-corpus")

    import korgan.legal.corpus_refresh as refresh

    def fail_fetch(url: str, timeout: int = 60):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(refresh, "fetch_adilet", fail_fetch)

    with pytest.raises(RuntimeError, match="network unavailable"):
        refresh_corpus_once(target)

    assert target.read_bytes() == b"previous-corpus"
    assert not target.with_name(target.name + ".refreshing").exists()


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

    def fake_load_act(corpus, act_id, html, *, url=None, edition_date=None, articles=None):
        adilet_id, title = KNOWN_ACTS[act_id]
        corpus.upsert_act(
            act_id=act_id,
            adilet_id=adilet_id,
            title_ru=title,
            url=url or f"https://adilet.zan.kz/rus/docs/{adilet_id}",
            edition_date="2026-08-17",
            loaded_at="2026-08-17",
        )
        corpus.upsert_provision(
            act_id=act_id,
            article_no="1",
            item_no=None,
            heading="Тестовая норма",
            body="Тестовая норма достаточной длины для проверки атомарного обновления корпуса KORGAN.",
            edition_date="2026-08-17",
            url=(url or f"https://adilet.zan.kz/rus/docs/{adilet_id}") + "#z1",
            sort_key=0,
        )
        return 1

    monkeypatch.setattr(refresh, "load_act", fake_load_act)

    total = refresh_corpus_once(target)

    assert total == len(KNOWN_ACTS)
    assert target.exists()
    assert not target.with_name(target.name + ".refreshing").exists()
    with LegalCorpus(target) as corpus:
        assert corpus.count() == len(KNOWN_ACTS)
