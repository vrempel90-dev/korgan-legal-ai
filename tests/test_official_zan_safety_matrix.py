from __future__ import annotations

from pathlib import Path

import pytest

import korgan.legal.corpus_refresh as refresh
from korgan.legal.corpus import ACT_GK_SPECIAL, ACT_LABOR, ACT_GPK, KNOWN_ACTS, LegalCorpus
from korgan.legal.corpus_refresh import _extract_zan_pdf_text, _read_zan_pdf, fetch_zan
from korgan.legal.official_sources import zan_pdf_url
from scripts.load_corpus import SourceRejected, act_url, load_act_text, strip_html

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _Headers:
    def __init__(self, content_type: str = "application/pdf", content_length: str | None = None) -> None:
        self._content_type = content_type
        self._content_length = content_length

    def get_content_type(self) -> str:
        return self._content_type

    def get(self, name: str, default=None):
        if name == "Content-Length":
            return self._content_length
        return default


class _Response:
    def __init__(
        self,
        payload: bytes,
        *,
        final_url: str,
        content_type: str = "application/pdf",
        content_length: str | None = None,
    ) -> None:
        self._payload = payload
        self._final_url = final_url
        self.headers = _Headers(content_type, content_length)

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info: object) -> None:
        return None

    def geturl(self) -> str:
        return self._final_url

    def read(self, limit: int = -1) -> bytes:
        if limit < 0:
            return self._payload
        return self._payload[:limit]


def _patch_open(monkeypatch: pytest.MonkeyPatch, response: _Response) -> None:
    def fake_open(*_args, **_kwargs):
        return response

    monkeypatch.setattr(refresh, "_open_allowlisted", fake_open)


def _labor_text() -> str:
    return """
    Эталонный контрольный банк нормативных правовых актов Республики Казахстан в электронном виде
    Дата редакции 07.04.2026
    Кодекс Республики Казахстан от 23 ноября 2015 года № 414-V ЗРК
    Трудовой кодекс Республики Казахстан
    Статья 1. Основные понятия, используемые в настоящем Кодексе
    """


def test_fetch_zan_rejects_payload_url_of_another_act(monkeypatch: pytest.MonkeyPatch) -> None:
    def wrong_act(_act_id: str, timeout: int = 90) -> tuple[bytes, str]:
        del timeout
        return (
            b"%PDF-fake",
            "https://zan.gov.kz/api/documents/95109/rus/07.04.2026/download/pdf",
        )

    monkeypatch.setattr(refresh, "_read_zan_pdf", wrong_act)
    monkeypatch.setattr(refresh, "_extract_zan_pdf_text", lambda _payload: _labor_text())

    with pytest.raises(RuntimeError, match="identity mismatch"):
        fetch_zan(ACT_LABOR)


@pytest.mark.parametrize(
    ("payload", "content_type", "content_length", "error"),
    [
        (b"not-a-pdf" + b"x" * 2048, "application/pdf", None, "PDF magic"),
        (b"%PDF-" + b"x" * 10, "application/pdf", None, "unexpectedly small"),
        (b"%PDF-" + b"x" * 2048, "text/plain", None, "not PDF content-type"),
        (
            b"%PDF-" + b"x" * 2048,
            "application/pdf",
            str(refresh.MAX_ZAN_PDF_BYTES + 1),
            "exceeds size limit",
        ),
    ],
)
def test_read_zan_pdf_rejects_invalid_payload_matrix(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    content_type: str,
    content_length: str | None,
    error: str,
) -> None:
    _patch_open(
        monkeypatch,
        _Response(
            payload,
            final_url=zan_pdf_url(ACT_GPK),
            content_type=content_type,
            content_length=content_length,
        ),
    )

    with pytest.raises(RuntimeError, match=error):
        _read_zan_pdf(ACT_GPK)


def test_extract_zan_pdf_text_rejects_malformed_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_reader(*_args, **_kwargs):
        raise ValueError("broken pdf")

    monkeypatch.setattr(refresh, "PdfReader", broken_reader)
    with pytest.raises(RuntimeError, match="ZAN PDF parse failed"):
        _extract_zan_pdf_text(b"%PDF-broken")


def test_extract_zan_pdf_text_rejects_encrypted_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    class EncryptedReader:
        is_encrypted = True
        pages: list[object] = []

    monkeypatch.setattr(refresh, "PdfReader", lambda *_args, **_kwargs: EncryptedReader())
    with pytest.raises(RuntimeError, match="encrypted"):
        _extract_zan_pdf_text(b"%PDF-encrypted")


def test_extract_zan_pdf_text_rejects_too_short_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class Page:
        def extract_text(self) -> str:
            return "Статья 1. Короткий текст"

    class ShortReader:
        is_encrypted = False
        pages = [Page()]

    monkeypatch.setattr(refresh, "PdfReader", lambda *_args, **_kwargs: ShortReader())
    with pytest.raises(RuntimeError, match="unexpectedly short"):
        _extract_zan_pdf_text(b"%PDF-short")


@pytest.mark.parametrize("act_id", sorted(KNOWN_ACTS))
def test_zan_provenance_and_canonical_citation_are_isolated_for_every_act(
    tmp_path: Path,
    act_id: str,
) -> None:
    text = strip_html((FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8"))
    db = tmp_path / f"{act_id}.sqlite3"

    with LegalCorpus(db) as corpus:
        load_act_text(
            corpus,
            act_id,
            text,
            source_url=zan_pdf_url(act_id),
            edition_date="2026-08-22",
        )
        act = corpus.connection.execute(
            "SELECT url FROM acts WHERE act_id = ?",
            (act_id,),
        ).fetchone()
        provision = corpus.connection.execute(
            "SELECT url FROM provisions WHERE act_id = ? ORDER BY sort_key LIMIT 1",
            (act_id,),
        ).fetchone()

    assert act is not None
    assert str(act["url"]) == zan_pdf_url(act_id)
    assert provision is not None
    assert str(provision["url"]).startswith(act_url(act_id))


def test_explicit_zan_citation_url_is_rejected(tmp_path: Path) -> None:
    text = strip_html((FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8"))
    source = zan_pdf_url(ACT_GK_SPECIAL)

    with LegalCorpus(tmp_path / "corpus.sqlite3") as corpus:
        with pytest.raises(SourceRejected, match="citation URL не соответствует акту"):
            load_act_text(
                corpus,
                ACT_GK_SPECIAL,
                text,
                source_url=source,
                citation_url=source,
                edition_date="2026-08-22",
            )


def test_adilet_and_zan_ids_cannot_cross_between_known_acts() -> None:
    assert act_url(ACT_GK_SPECIAL) != act_url(ACT_GPK)
    assert zan_pdf_url(ACT_GK_SPECIAL) != zan_pdf_url(ACT_GPK)
