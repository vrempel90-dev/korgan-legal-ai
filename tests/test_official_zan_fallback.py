from __future__ import annotations

from pathlib import Path

import pytest

from korgan.legal.corpus import ACT_GK_SPECIAL, ACT_GPK, LegalCorpus
from korgan.legal.corpus_refresh import _validate_zan_identity, fetch_zan
from korgan.legal.official_sources import (
    ZAN_DOCUMENT_IDS,
    is_allowed_zan_pdf_url,
    official_source_kind,
    zan_pdf_url,
)
from scripts.load_corpus import load_act_text, strip_html

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_zan_pdf_allowlist_is_exact_and_bound_to_known_document_id() -> None:
    current = "https://zan.gov.kz/api/documents/95109/rus/download/pdf"
    dated = "https://zan.gov.kz/api/documents/95109/rus/30.12.2024/download/pdf"
    assert is_allowed_zan_pdf_url(current, act_id=ACT_GPK)
    assert is_allowed_zan_pdf_url(dated, act_id=ACT_GPK)
    assert official_source_kind(current) == "zan"

    assert not is_allowed_zan_pdf_url("http://zan.gov.kz/api/documents/95109/rus/download/pdf")
    assert not is_allowed_zan_pdf_url("https://evil.example/api/documents/95109/rus/download/pdf")
    assert not is_allowed_zan_pdf_url("https://zan.gov.kz/api/documents/95109/kaz/download/pdf")
    assert not is_allowed_zan_pdf_url("https://zan.gov.kz/api/documents/999999/rus/download/pdf")
    assert not is_allowed_zan_pdf_url("https://zan.gov.kz/api/documents/95109/rus/meta")
    assert not is_allowed_zan_pdf_url("https://zan.gov.kz/api/documents/95109/rus/download/pdf?next=evil")
    assert not is_allowed_zan_pdf_url("https://user@zan.gov.kz/api/documents/95109/rus/download/pdf")
    assert not is_allowed_zan_pdf_url("https://zan.gov.kz:444/api/documents/95109/rus/download/pdf")
    assert not is_allowed_zan_pdf_url(current, act_id=ACT_GK_SPECIAL)


def test_all_supported_acts_have_distinct_zan_ids() -> None:
    assert len(ZAN_DOCUMENT_IDS) == 6
    assert len(set(ZAN_DOCUMENT_IDS.values())) == len(ZAN_DOCUMENT_IDS)
    assert ZAN_DOCUMENT_IDS[ACT_GPK] == 95109
    assert ZAN_DOCUMENT_IDS[ACT_GK_SPECIAL] == 3559


def test_zan_identity_requires_title_adoption_markers_and_revision() -> None:
    text = """
    Эталонный контрольный банк нормативных правовых актов Республики Казахстан в электронном виде
    Дата редакции 30.12.2024
    Кодекс Республики Казахстан от 31 октября 2015 года № 377-V ЗРК
    Гражданский процессуальный кодекс Республики Казахстан
    Статья 1. Законодательство о гражданском судопроизводстве
    """
    final_url = "https://zan.gov.kz/api/documents/95109/rus/30.12.2024/download/pdf"

    assert _validate_zan_identity(ACT_GPK, text, final_url) == "2024-12-30"

    with pytest.raises(RuntimeError, match="identity mismatch"):
        _validate_zan_identity(
            ACT_GPK,
            text.replace("377-V", "999-X"),
            final_url,
        )

    with pytest.raises(RuntimeError, match="revision mismatch"):
        _validate_zan_identity(
            ACT_GPK,
            text,
            "https://zan.gov.kz/api/documents/95109/rus/29.12.2024/download/pdf",
        )


def test_fetch_zan_binds_downloaded_payload_to_same_act(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.legal.corpus_refresh as refresh

    text = """
    Эталонный контрольный банк нормативных правовых актов Республики Казахстан в электронном виде
    Дата редакции 07.04.2026
    Кодекс Республики Казахстан от 23 ноября 2015 года № 414-V ЗРК
    Трудовой кодекс Республики Казахстан
    Статья 1. Основные понятия, используемые в настоящем Кодексе
    """

    from korgan.legal.corpus import ACT_LABOR

    monkeypatch.setattr(
        refresh,
        "_read_zan_pdf",
        lambda act_id, timeout=90: (
            b"%PDF-fake",
            "https://zan.gov.kz/api/documents/95666/rus/07.04.2026/download/pdf",
        ),
    )
    monkeypatch.setattr(refresh, "_extract_zan_pdf_text", lambda payload: text)

    extracted, final_url, revision = fetch_zan(ACT_LABOR)

    assert extracted == text
    assert final_url == "https://zan.gov.kz/api/documents/95666/rus/07.04.2026/download/pdf"
    assert revision == "2026-04-07"


def test_zan_text_uses_same_article_parser_but_preserves_refresh_provenance(tmp_path: Path) -> None:
    text = strip_html((FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8"))
    source_url = zan_pdf_url(ACT_GK_SPECIAL)
    citation_url = "https://adilet.zan.kz/rus/docs/K990000409_"

    with LegalCorpus(tmp_path / "corpus.sqlite3") as corpus:
        loaded = load_act_text(
            corpus,
            ACT_GK_SPECIAL,
            text,
            source_url=source_url,
            citation_url=citation_url,
            edition_date="2026-08-22",
        )
        act = corpus.connection.execute(
            "SELECT url FROM acts WHERE act_id = ?",
            (ACT_GK_SPECIAL,),
        ).fetchone()
        provision = corpus.connection.execute(
            "SELECT url FROM provisions WHERE act_id = ? ORDER BY sort_key LIMIT 1",
            (ACT_GK_SPECIAL,),
        ).fetchone()

    assert loaded == 8
    assert act is not None and str(act["url"]).startswith("https://zan.gov.kz/api/documents/3559/")
    assert provision is not None and str(provision["url"]).startswith(citation_url)
