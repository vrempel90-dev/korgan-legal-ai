from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from korgan.legal.corpus import LegalCorpus, Provision
from korgan.legal import upstream_rag
from korgan.legal import pipeline


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


def _row(*, idx: int, jurisdiction: str = "KZ", lang: str = "ru") -> dict[str, object]:
    return {
        "id": f"{jurisdiction}-{idx}",
        "jurisdiction": jurisdiction,
        "lang": lang,
        "code_id": "K940001000_",
        "code_name": "Civil Code",
        "article_no": str(100 + idx),
        "article_title": f"Статья {100 + idx}. Исполнение обязательства",
        "text": "Обязательство должно исполняться надлежащим образом в соответствии с его условиями.",
        "url": f"https://adilet.zan.kz/rus/docs/K940001000_#z{100 + idx}",
    }


def test_upstream_rows_are_isolated_from_official_act_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "upstream.sqlite3"
    with LegalCorpus(db_path) as corpus:
        corpus.connection.executescript(upstream_rag._META_SCHEMA)
        assert upstream_rag._write_row(corpus.connection, _row(idx=1), loaded_at="2026-09-02")
        assert not upstream_rag._write_row(corpus.connection, _row(idx=2, jurisdiction="UZ"), loaded_at="2026-09-02")
        assert not upstream_rag._write_row(corpus.connection, _row(idx=3, lang="kk"), loaded_at="2026-09-02")
        corpus.connection.commit()

        rows = corpus.connection.execute("SELECT act_id, article_no FROM provisions").fetchall()
        assert len(rows) == 1
        assert str(rows[0]["act_id"]).startswith("RAGKZ_")
        assert rows[0]["article_no"] == "101"


def test_sync_builds_pinned_kz_database_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [json.dumps(_row(idx=i), ensure_ascii=False) for i in range(1, 4)]
    lines.append(json.dumps(_row(idx=9, jurisdiction="UZ"), ensure_ascii=False))
    payload = ("\n".join(lines) + "\n").encode("utf-8")

    monkeypatch.setattr(upstream_rag, "MIN_KZ_ROWS", 2)
    monkeypatch.setattr(upstream_rag, "_open_upstream", lambda timeout=90: _Response(payload))

    target = tmp_path / "legal_rag_kz.sqlite3"
    status = upstream_rag.sync_upstream_rag(path=target, force=True)

    assert status.ready
    assert status.rows == 3
    assert target.exists()
    assert not target.with_name(target.name + ".tmp").exists()

    corpus = upstream_rag.open_upstream_corpus(target)
    assert corpus is not None
    try:
        assert corpus.count() == 3
        meta = upstream_rag._metadata(corpus)
        assert meta["commit"] == upstream_rag.UPSTREAM_COMMIT
    finally:
        corpus.close()


def _provision(article_id: str, *, url: str, article_no: str) -> Provision:
    return Provision(
        article_id=article_id,
        act_id=article_id.split(":", 1)[0],
        act_title="Гражданский кодекс Республики Казахстан",
        article_no=article_no,
        item_no=None,
        heading="Исполнение обязательств",
        body="Обязательство исполняется надлежащим образом.",
        edition_date="2026-01-01",
        url=url,
    )


class _CorpusStub:
    def __init__(self, rows: list[Provision]) -> None:
        self.rows = rows
        self.closed = False

    def search(self, query: str, act_id: str | None = None, limit: int = 20) -> list[Provision]:
        return list(self.rows[:limit])

    def get(self, article_id: str) -> Provision | None:
        return next((row for row in self.rows if row.article_id == article_id), None)

    def close(self) -> None:
        self.closed = True


def test_production_retrieval_fuses_official_and_upstream_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    official = _CorpusStub([
        _provision("GK_RK:272", url="https://adilet.zan.kz/rus/docs/K940001000_#z272", article_no="272"),
    ])
    upstream = _CorpusStub([
        _provision("RAGKZ_abcd:9", url="https://adilet.zan.kz/rus/docs/Z100000274_#z9", article_no="9"),
    ])
    monkeypatch.delenv(pipeline.FLAG_ENV, raising=False)
    monkeypatch.setattr(pipeline, "open_corpus", lambda path=None: official)
    monkeypatch.setattr(pipeline, "open_upstream_corpus", lambda path=None: upstream)

    result = pipeline.research_from_corpus("нарушение договора права потребителя", limit=4)

    assert result is not None
    assert [item.article_id for item in result.provisions] == ["GK_RK:272", "RAGKZ_abcd:9"]
    assert "GK_RK:272" in result.prompt_block
    assert "RAGKZ_abcd:9" in result.prompt_block
    assert official.closed
    assert upstream.closed
