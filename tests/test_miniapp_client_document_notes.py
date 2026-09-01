"""Экран готового документа показывает задачи клиенту, а не протокол проверок.

Описание готового документа отдавало клиенту `verification_notes` и
`quality_issues` — списки, которые ведут внутренние гейты для самих себя. Там
живут служебный префикс `FILING_ACTION:` и привязка к источнику вида
«[основание: статья …; текст нормы: …; источник: https://…]». Мини-апп
показывает эти списки на экране выпуска сплошной строкой, поэтому оплативший
клиент читал внутреннюю разметку и ссылки вместо понятного перечня того, что
нужно дослать перед подачей.

Список, написанный для клиента, давно существует: `humanize()` переводит
замечания гейтов в задачи человеку, и помеченный черновик его уже составляет.
До экрана он не доходил — описание документа его не отдавало.
"""

from __future__ import annotations

from korgan import miniapp_generation_api as api

_SOURCE_BOUND_NOTE = (
    "Обязательство должно исполняться надлежащим образом "
    "[основание: статья 272 ГК РК; текст нормы: тест; "
    "источник: https://adilet.zan.kz/rus/docs/K940001000_]"
)


def _preliminary_case() -> dict[str, object]:
    return {
        "status": "document_ready",
        "document_base64": "ZmlsZQ==",
        "filename": "KORGAN_iskovoe_zayavlenie.docx",
        "title": "Исковое заявление",
        "verification_status": "needs_verification",
        "verification_notes": [
            _SOURCE_BOUND_NOTE,
            "не определена госпошлина или подтвержденная льгота",
        ],
        "quality_score": 8.4,
        "quality_issues": ["FILING_ACTION: указать банковские реквизиты истца"],
        "filing_ready": False,
        "release_status": "preliminary",
    }


def test_document_payload_carries_the_list_written_for_the_client() -> None:
    payload = api._document_payload("KOR-1", _preliminary_case())

    todo = payload["todo_before_filing"]
    assert "указать банковские реквизиты истца" in todo
    assert any("пошлин" in item for item in todo), todo


def test_document_payload_never_hands_the_client_gate_markup() -> None:
    payload = api._document_payload("KOR-1", _preliminary_case())

    for item in payload["todo_before_filing"]:
        assert "FILING_ACTION" not in item
        assert "источник:" not in item
        assert "http" not in item


def test_stored_client_list_is_not_recomputed() -> None:
    """Помеченный черновик уже составил перечень — он и доходит до клиента."""
    case = _preliminary_case()
    case["todo_before_filing"] = ["приложить акт сверки"]

    payload = api._document_payload("KOR-1", case)

    assert payload["todo_before_filing"] == ["приложить акт сверки"]


def test_verified_document_has_nothing_to_do_before_filing() -> None:
    payload = api._document_payload(
        "KOR-1",
        {
            "status": "document_ready",
            "document_base64": "ZmlsZQ==",
            "filename": "KORGAN_iskovoe_zayavlenie.docx",
            "title": "Исковое заявление",
            "verification_status": "verified",
            "verification_notes": [],
            "quality_issues": [],
            "filing_ready": True,
            "release_status": "verified",
        },
    )

    assert payload["todo_before_filing"] == []
