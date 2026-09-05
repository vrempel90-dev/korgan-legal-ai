"""Тип документа определяется выбором пользователя, а не фабулой дела.

Боевой дефект: клиент выбрал «Досудебная претензия», а получил
``KORGAN_otvet_na_pretenziyu.docx`` с заголовком «ОТВЕТ НА ПРЕТЕНЗИЮ» и
перевёрнутыми ролями — должник значился отправителем, кредитор адресатом.
Причина: тип документа выводился из свободного текста, а фабула обычной
претензии почти всегда содержит слова «ответа на претензию не поступило».
"""

from __future__ import annotations

import asyncio

import pytest

from korgan import document_type_routing as routing
from korgan import miniapp_api_v2 as core
from korgan.pretrial import is_pretrial_request
from korgan.pretrial_response import is_pretrial_response_request
from korgan.pretrial_role_guard import (
    enforce_pretrial_response_roles,
    enforce_pretrial_roles,
)
from korgan.legal_types import VerificationStatus

PRETRIAL_CASE = (
    "Прошу подготовить досудебную претензию. "
    "Кредитор ТОО «Альфа Трейд», БИН 123456789012, г. Алматы, ул. Абая, 10. "
    "Должник ТОО «Бета Снаб», БИН 210987654321, г. Алматы, ул. Толе би, 20. "
    "10.01.2026 заключён договор поставки №12, 15.01.2026 поставлен товар на 4 500 000 тенге. "
    "Срок оплаты — 15 календарных дней после поставки, оплата не произведена. "
    "Ответа на претензию не поступило."
)
RESPONSE_CASE = (
    "Прошу подготовить ответ на претензию от 15.02.2026. "
    "Претензию направило ТОО «Альфа Трейд», получатель — ТОО «Бета Снаб». "
    "Требуют оплатить 4 500 000 тенге по договору поставки №12."
)


def test_pretrial_request_never_routes_to_pretrial_response() -> None:
    assert routing.resolve_document_type(None, PRETRIAL_CASE) == "pretrial"
    assert is_pretrial_request(PRETRIAL_CASE) is True
    assert is_pretrial_response_request(PRETRIAL_CASE) is False


def test_pretrial_response_request_routes_to_pretrial_response() -> None:
    assert routing.resolve_document_type(None, RESPONSE_CASE) == "pretrial_response"
    assert is_pretrial_response_request(RESPONSE_CASE) is True
    assert is_pretrial_request(RESPONSE_CASE) is False


@pytest.mark.parametrize(
    "selected",
    ["claim", "contract", "response", "pretrial", "pretrial_response"],
)
def test_explicit_selection_survives_any_case_text(selected: str) -> None:
    """Выбор карточки документа не уточняется текстом дела ни для одного типа."""
    for text in (PRETRIAL_CASE, RESPONSE_CASE, "Подготовьте договор поставки и исковое заявление"):
        assert routing.resolve_document_type(selected, text) == selected


def test_all_five_document_types_keep_their_own_pipeline() -> None:
    """Каждый тип ведёт к своей ветке конвейера и своему имени файла."""
    expected = {
        "claim": ("research_case", "draft_claim", "KORGAN_iskovoe_zayavlenie.docx"),
        "contract": ("research_contract", "draft_contract", "KORGAN_dogovor.docx"),
        "response": ("research_response_to_claim", "draft_response_to_claim", "KORGAN_otzyv_na_isk.docx"),
        "pretrial": ("research_pretrial", "draft_pretrial", "KORGAN_dosudebnaya_pretenziya.docx"),
        "pretrial_response": (
            "research_pretrial_response",
            "draft_pretrial_response",
            "KORGAN_otvet_na_pretenziyu.docx",
        ),
    }
    assert set(core._PIPELINE) == routing.DOCUMENT_TYPES
    for document_type, (research, draft, filename) in expected.items():
        pipeline = core._PIPELINE[document_type]
        assert (pipeline.research, pipeline.draft, pipeline.filename) == (research, draft, filename)


def test_unknown_document_type_is_refused_instead_of_guessed() -> None:
    assert routing.resolve_document_type("pretrail", PRETRIAL_CASE) is None
    assert routing.resolve_document_type("", "прогноз погоды") is None


def test_active_section_blocks_switching_by_case_text() -> None:
    """Заявка, открытая кнопкой, не переходит в другой раздел по словам дела."""
    active_pretrial = {"request_id": "req-1", "request_kind": "pretrial"}
    assert routing.intent_may_switch(active_pretrial, "pretrial") is True
    assert routing.intent_may_switch(active_pretrial, "pretrial_response") is False
    assert routing.intent_may_switch(active_pretrial, "claim") is False
    # Без открытой заявки интент по тексту работает как раньше.
    assert routing.intent_may_switch({}, "pretrial_response") is True


def test_pretrial_intent_filter_respects_selected_section() -> None:
    from korgan import pretrial_response_runtime

    class _State:
        def __init__(self, data: dict) -> None:
            self._data = data

        async def get_data(self) -> dict:
            return self._data

    class _Message:
        text = "Составьте документ: ответа на претензию от должника не поступило"

    intent = pretrial_response_runtime._Intent()
    inside_pretrial = _State({"mode": "main", "request_id": "r", "request_kind": "pretrial"})
    assert asyncio.run(intent(_Message(), inside_pretrial)) is False


def test_role_matrix_is_mirrored_between_the_two_documents() -> None:
    assert routing.expected_roles("pretrial") == {"sender": "creditor", "recipient": "debtor"}
    assert routing.expected_roles("pretrial_response") == {"sender": "debtor", "recipient": "creditor"}


class _Draft:
    def __init__(self, **values: object) -> None:
        self.status = VerificationStatus.VERIFIED
        self.verification_notes: list[str] = []
        self.title = ""
        self.facts: list[str] = []
        self.demands: list[str] = []
        self.consequences: list[str] = []
        self.position: list[str] = []
        self.objections: list[str] = []
        self.response_terms: list[str] = []
        for key, value in values.items():
            setattr(self, key, value)


def test_pretrial_with_reversed_roles_is_not_released() -> None:
    draft = _Draft(
        title="ОТВЕТ НА ПРЕТЕНЗИЮ",
        demands=["Задолженность не оспариваем и готовы обсудить погашение."],
    )
    issues = enforce_pretrial_roles(draft)
    assert issues, "перевёрнутые роли обязаны блокировать выпуск претензии"
    assert draft.status is VerificationStatus.NEEDS_VERIFICATION
    assert any("не той стороны" in note for note in draft.verification_notes)


def test_ordinary_pretrial_passes_the_role_guard() -> None:
    draft = _Draft(
        title="ДОСУДЕБНАЯ ПРЕТЕНЗИЯ",
        demands=["Требуем оплатить задолженность в размере 4 500 000 тенге."],
    )
    assert enforce_pretrial_roles(draft) == []
    assert draft.status is VerificationStatus.VERIFIED


def test_pretrial_response_titled_as_a_demand_is_not_released() -> None:
    draft = _Draft(
        title="ДОСУДЕБНАЯ ПРЕТЕНЗИЯ",
        position=["Требуем оплатить 4 500 000 тенге."],
    )
    issues = enforce_pretrial_response_roles(draft)
    assert issues
    assert draft.status is VerificationStatus.NEEDS_VERIFICATION


def test_ordinary_pretrial_response_passes_the_role_guard() -> None:
    draft = _Draft(
        title="ОТВЕТ НА ПРЕТЕНЗИЮ",
        position=["Изложенные в претензии требования не признаём."],
    )
    assert enforce_pretrial_response_roles(draft) == []
