"""Разделы, которые требует схема отзыва, обязаны доехать до драфта.

Схема ``_RESPONSE_DRAFT_SCHEMA`` перечисляет ``admitted_circumstances``,
``disputed_circumstances`` и ``calculation_review`` в ``required``, промпт
подробно объясняет модели, как их заполнять, — но конструктор
``ResponseToClaimDraft`` в ``draft_response_to_claim`` перечислял поля вручную
и эти три пропускал. Модель возвращала содержимое, а драфт получал пустые
списки: разделение признанного и оспариваемого и разбор расчёта истца
никогда не попадали в первичный боевой отзыв.

Молча: ``_score_response`` этих разделов не требует, поэтому документ
не уходил и на раунд правки — он просто выходил без них.

Здесь подменяется только вызов модели. Сборка драфта, фильтрация правового
обоснования и простановка статуса остаются боевыми.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.response_legal import _RESPONSE_DRAFT_SCHEMA, ProductionOpenAILegalService

GK_GENERAL_URL = "https://adilet.zan.kz/rus/docs/K940001000_"

MODEL_PAYLOAD: dict[str, object] = {
    "title": "ОТЗЫВ НА ИСКОВОЕ ЗАЯВЛЕНИЕ",
    "court": "Медеуский районный суд города Алматы",
    "case_number": "2-1234/2026",
    "claimant": ["Ахметов Руслан Маратович, ИИН 900101300123"],
    "defendant": ['ТОО «Компания», БИН 210987654321'],
    "claim_summary": ["Истец просит взыскать 2 300 000 тенге."],
    "admitted_circumstances": ["Факт заключения договора № 12 от 15.01.2026 не оспаривается."],
    "disputed_circumstances": ["Оспаривается объём принятых работ по акту от 20.02.2026."],
    "position": ["Иск подлежит частичному удовлетворению в размере 1 400 000 тенге."],
    "calculation_review": [
        "Начисление произведено с 01.03.2026 при сроке оплаты 20.03.2026 по пункту 4.2 договора.",
    ],
    "objections": [
        {
            "text": "Работы на сумму 900 000 тенге не приняты: акт от 20.02.2026 подписан с замечаниями.",
            "subclauses": [],
            "prose": [],
        }
    ],
    "legal_basis": [],
    "requests": ["Отказать в удовлетворении исковых требований в части 900 000 тенге."],
    "attachments": ["Копия акта от 20.02.2026"],
    "verification_notes": [],
}


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[GK_GENERAL_URL],
        notes=[],
    )


def _drafted() -> object:
    """Боевой сборщик драфта поверх зафиксированного ответа модели."""
    service = ProductionOpenAILegalService.__new__(ProductionOpenAILegalService)
    service.settings = SimpleNamespace(max_case_text_chars=20_000, openai_model="test-model")

    async def fake_structured(**_kwargs):
        return dict(MODEL_PAYLOAD), None

    service._response_structured = fake_structured
    return asyncio.run(service.draft_response_to_claim("Материалы дела.", _research()))


def test_schema_requires_the_three_adversarial_sections() -> None:
    """Иначе тест ниже проверял бы поля, которых модель не обязана возвращать."""
    required = set(_RESPONSE_DRAFT_SCHEMA["required"])
    assert {"admitted_circumstances", "disputed_circumstances", "calculation_review"} <= required


def test_admitted_circumstances_survive_drafting() -> None:
    assert _drafted().admitted_circumstances == MODEL_PAYLOAD["admitted_circumstances"]


def test_disputed_circumstances_survive_drafting() -> None:
    assert _drafted().disputed_circumstances == MODEL_PAYLOAD["disputed_circumstances"]


def test_calculation_review_survives_drafting() -> None:
    assert _drafted().calculation_review == MODEL_PAYLOAD["calculation_review"]


def test_new_sections_reach_the_document_body() -> None:
    """Проверка на выходе, а не только на поле: разделы должны печататься."""
    body = "\n".join(_drafted().body_lines())

    assert "Факт заключения договора № 12 от 15.01.2026 не оспаривается." in body
    assert "Оспаривается объём принятых работ по акту от 20.02.2026." in body
    assert "Начисление произведено с 01.03.2026" in body


def test_existing_fields_are_not_disturbed() -> None:
    draft = _drafted()

    assert draft.court == MODEL_PAYLOAD["court"]
    assert draft.case_number == MODEL_PAYLOAD["case_number"]
    assert draft.claim_summary == MODEL_PAYLOAD["claim_summary"]
    assert draft.position == MODEL_PAYLOAD["position"]
    assert draft.requests == MODEL_PAYLOAD["requests"]
    assert draft.attachments == MODEL_PAYLOAD["attachments"]


def test_empty_sections_stay_empty_and_are_not_invented() -> None:
    """Пустое признание — допустимый результат, выдумывать его нельзя."""
    service = ProductionOpenAILegalService.__new__(ProductionOpenAILegalService)
    service.settings = SimpleNamespace(max_case_text_chars=20_000, openai_model="test-model")

    async def fake_structured(**_kwargs):
        payload = dict(MODEL_PAYLOAD)
        payload["admitted_circumstances"] = []
        payload["disputed_circumstances"] = []
        payload["calculation_review"] = []
        return payload, None

    service._response_structured = fake_structured
    draft = asyncio.run(service.draft_response_to_claim("Материалы дела.", _research()))

    assert draft.admitted_circumstances == []
    assert draft.disputed_circumstances == []
    assert draft.calculation_review == []
