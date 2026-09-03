from __future__ import annotations

import base64
import inspect
import io
import zipfile

import pytest
from fastapi import HTTPException

from korgan import miniapp_document_consultation as document_consultation
from korgan import miniapp_telegram_delivery


def _docx_bytes(text: str) -> bytes:
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>'
        + text
        + '</w:t></w:r></w:p></w:body></w:document>'
    ).encode("utf-8")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return stream.getvalue()


def _case(text: str = "Прошу взыскать 100 000 тенге.") -> dict[str, object]:
    data = _docx_bytes(text)
    return {
        "id": "KOR-TEST",
        "document_type": "claim",
        "title": "Исковое заявление о взыскании долга",
        "filename": "KORGAN_iskovoe_zayavlenie.docx",
        "document_base64": base64.b64encode(data).decode("ascii"),
        "description": "Истец передал ответчику денежные средства.",
        "materials": [],
        "conversation": [],
    }


def test_extracts_exact_generated_docx_text() -> None:
    text = "Прошу взыскать 100 000 тенге и судебные расходы."
    assert document_consultation._extract_docx_text(_docx_bytes(text)) == text


def test_matching_revision_pins_consultation_to_exact_document() -> None:
    case = _case("Требование этой конкретной версии документа.")
    revision = document_consultation._case_document_revision(case)

    context, pinned = document_consultation._document_context(case, revision)

    assert pinned == revision
    assert f"Версия SHA-256: {revision}" in context
    assert "Требование этой конкретной версии документа." in context
    assert "КОНСУЛЬТАЦИЯ ПО КОНКРЕТНОЙ СГЕНЕРИРОВАННОЙ ВЕРСИИ" in context


def test_regenerated_document_cannot_be_silently_substituted() -> None:
    case = _case("Новая версия документа")
    with pytest.raises(HTTPException) as exc_info:
        document_consultation._document_context(case, "0" * 64)

    assert exc_info.value.status_code == 409
    assert "Документ был обновлён" in str(exc_info.value.detail)


def test_public_case_exposes_document_revision_but_not_docx_body() -> None:
    case = _case()
    public = document_consultation.core._public_case(case)

    assert public["document_revision"] == document_consultation._case_document_revision(case)
    assert "document_base64" not in public


def test_only_one_production_consultation_route_owns_post() -> None:
    routes = [
        route
        for route in document_consultation.app.router.routes
        if getattr(route, "path", "") == "/miniapp/consultation"
        and "POST" in (getattr(route, "methods", set()) or set())
    ]
    assert len(routes) == 1
    assert routes[0].endpoint is document_consultation.consultation


def test_telegram_document_delivery_is_fail_closed_and_has_no_bot_api_call() -> None:
    source = inspect.getsource(miniapp_telegram_delivery)
    assert "sendDocument" not in source
    assert "api.telegram.org" not in source
    assert "status_code=410" in source
    assert "Отправка документов через Telegram отключена" in source
