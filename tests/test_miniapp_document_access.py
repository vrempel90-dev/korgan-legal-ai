from __future__ import annotations

import io

import pytest
from docx import Document
from fastapi import HTTPException

from korgan.miniapp_document_access import _make_token, _read_token, _render_docx_html


def test_document_access_token_roundtrip_and_expiry() -> None:
    token = _make_token("12345", "KOR-ABC123", 1_000, "test-secret")
    assert _read_token(token, "test-secret", now=900) == ("12345", "KOR-ABC123")

    with pytest.raises(HTTPException) as expired:
        _read_token(token, "test-secret", now=1_001)
    assert expired.value.status_code == 403


def test_document_access_token_rejects_tampering() -> None:
    token = _make_token("12345", "KOR-ABC123", 1_000, "test-secret")
    payload, signature = token.split(".", 1)
    tampered = f"{payload[:-1]}A.{signature}"
    with pytest.raises(HTTPException) as invalid:
        _read_token(tampered, "test-secret", now=900)
    assert invalid.value.status_code == 403


def test_document_preview_is_first_party_html_and_escapes_text() -> None:
    document = Document()
    document.add_heading("Исковое заявление", level=1)
    document.add_paragraph("Факт <не должен> превращаться в HTML & script")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Истец"
    table.cell(0, 1).text = "ТОО <Альфа>"
    buffer = io.BytesIO()
    document.save(buffer)

    rendered = _render_docx_html(buffer.getvalue(), "KORGAN <preview>")

    assert "Исковое заявление" in rendered
    assert "&lt;не должен&gt;" in rendered
    assert "ТОО &lt;Альфа&gt;" in rendered
    assert "KORGAN &lt;preview&gt;" in rendered
    assert "<script" not in rendered.lower()
