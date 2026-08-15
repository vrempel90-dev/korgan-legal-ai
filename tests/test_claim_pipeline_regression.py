"""Регрессия инцидента: «долг по расписке» больше не даёт silent-fail.

Кейс из отчёта: наличные, без банковского перевода, без письменной претензии,
единственное доказательство — расписка. Раньше FINAL QA возвращал замечания об
отсутствующем втором доказательстве и о неподтверждённой статье, оба попадали в
``blocking`` и пайплайн падал с ``CourtDocumentQualityError`` — пользователь
видел generic-отказ.

Сеть не используется: подменяется ``_structured_response``, то есть единственная
точка, через которую весь рантайм ходит в Responses API.
"""

from __future__ import annotations

import asyncio
import io

import pytest
from docx import Document

from korgan.claim_docx import QA_PRELIMINARY, build_claim_docx, missing_required_fields
from korgan.claim_failure import ClaimFailureCode, CourtDocumentQualityError
from korgan.config import Settings
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.state_duty_final_hotfix import ProductionOpenAILegalService

CASE_CONTEXT = (
    "Сообщения пользователя о фактах:\n"
    "Истец: Ахметов Руслан Маратович, ИИН 000000000101, дата рождения 14.03.1988, "
    "адрес истца: город Алматы, улица Абая, дом 12, квартира 5.\n"
    "Ответчик: Садыков Тимур Ерланович, адрес ответчика: город Алматы, "
    "микрорайон Аксай-3, дом 44, квартира 17.\n"
    "Я дал ответчику в долг 800 000 тенге наличными, банковского перевода не было.\n"
    "Ответчик написал расписку от 10.01.2026 и обязался вернуть до 10.04.2026.\n"
    "Деньги не возвращены. Письменную претензию я не направлял.\n"
    "Доказательства: расписка от 10.01.2026 — единственный документ.\n"
)

_CLEAN_CLAIM = {
    "title": "ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании суммы долга по расписке",
    "court": "[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда по месту жительства ответчика]",
    "claimant": [
        "Ахметов Руслан Маратович, ИИН 000000000101",
        "Дата рождения: 14.03.1988",
        "Адрес: город Алматы, улица Абая, дом 12, квартира 5",
    ],
    "defendant": [
        "Садыков Тимур Ерланович",
        "Адрес: город Алматы, микрорайон Аксай-3, дом 44, квартира 17",
    ],
    "price_of_claim": "800 000 тенге",
    "facts": [
        "10.01.2026 истец передал ответчику 800 000 тенге наличными, "
        "что подтверждается распиской ответчика от 10.01.2026.",
        "Ответчик обязался возвратить сумму до 10.04.2026. Сумма не возвращена.",
    ],
    "legal_basis": ["Заёмщик обязан возвратить займодавцу полученную сумму займа в срок."],
    "requests": ["Взыскать с ответчика в пользу истца 800 000 тенге основного долга."],
    "attachments": ["Копия расписки от 10.01.2026", "Копия искового заявления для ответчика"],
    "verification_notes": [],
}

RESEARCH = LegalResearch(
    status=VerificationStatus.NEEDS_VERIFICATION,
    applicable_law=["ГК РК (Особенная часть), статьи 715, 722"],
    procedural_requirements=["ГПК РК, статьи 148, 149"],
    verified_claims=[
        "Передача денег в собственность с обязанностью возврата образует заём "
        "[основание: статья 715; источник: https://adilet.zan.kz/rus/docs/K990000409_]",
        "Заёмщик обязан возвратить сумму займа в срок "
        "[основание: статья 722; источник: https://adilet.zan.kz/rus/docs/K990000409_]",
    ],
    unverified_claims=[],
    source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
    notes=[],
)


class _FakeService(ProductionOpenAILegalService):
    """Рантайм без сети: ответы Responses API задаются сценарием теста."""

    def __init__(self, *, validations: list[dict[str, list[str]]]) -> None:
        super().__init__(Settings(telegram_bot_token="test", openai_api_key="test"))
        self._validations = list(validations)
        self.schema_calls: list[str] = []

    async def _structured_response(self, *, model, instructions, content, schema_name, schema, tools=None):
        self.schema_calls.append(schema_name)

        if schema_name in {"korgan_court_ready_claim", "korgan_repaired_claim"}:
            return dict(_CLEAN_CLAIM), None

        if schema_name == "korgan_court_ready_validation":
            if self._validations:
                return dict(self._validations.pop(0)), None
            return {"critical_errors": [], "unsupported_legal_claims": [], "missing_required_fields": []}, None

        raise AssertionError(f"Неожиданный вызов схемы: {schema_name}")


def _validation(**overrides) -> dict[str, list[str]]:
    base = {"critical_errors": [], "unsupported_legal_claims": [], "missing_required_fields": []}
    base.update(overrides)
    return base


def _draft_claim(service: _FakeService):
    return asyncio.run(service.draft_claim(CASE_CONTEXT, RESEARCH, language="ru"))


def test_receipt_only_case_produces_a_document_instead_of_a_refusal() -> None:
    """Главный сценарий инцидента: нет второго доказательства и нет претензии."""
    service = _FakeService(
        validations=[
            _validation(
                critical_errors=[
                    "Факт передачи денег утверждается как доказанный, "
                    "но кроме расписки иных доказательств не приложено",
                    "Претензия ответчику не направлялась, досудебный порядок не подтверждён",
                ],
                unsupported_legal_claims=[
                    "Ссылка на письменную форму займа по статье 716 ГК РК отсутствует в VERIFIED",
                ],
            )
        ]
    )

    draft = _draft_claim(service)

    # Документ выдан, а не отклонён.
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert missing_required_fields(draft) == []

    # Ремонтного прохода не было: ни одно из замечаний не является блокирующим.
    assert service.schema_calls.count("korgan_repaired_claim") == 0

    notes = "\n".join(draft.verification_notes)
    assert "расписки иных доказательств" in notes
    assert "Претензия ответчику не направлялась" in notes
    assert "716" in notes

    payload = build_claim_docx(draft)
    header = Document(io.BytesIO(payload)).paragraphs[0].text
    assert QA_PRELIMINARY in header
    assert payload.startswith(b"PK")


def test_receipt_stays_in_the_document_body() -> None:
    """Расписка — допустимое доказательство и не должна вычищаться из иска."""
    service = _FakeService(validations=[_validation()])

    draft = _draft_claim(service)
    body = "\n".join([*draft.facts, *draft.attachments]).lower()

    assert "расписк" in body
    # Служебные фразы в судебный текст не попали.
    assert "needs_verification" not in body


def test_state_duty_is_calculated_and_requested_once() -> None:
    """Расчёт госпошлины не затронут: 1% от 800 000 тенге, ровно одна просьба."""
    service = _FakeService(validations=[_validation()])

    draft = _draft_claim(service)
    duty_requests = [item for item in draft.requests if "пошлин" in item.lower()]

    assert draft.state_duty.startswith("8 000 тенге")
    assert len(duty_requests) == 1


def test_fabricated_fact_still_blocks_with_a_machine_readable_reason() -> None:
    """Fail-closed сохранён там, где он и должен быть: выдуманный факт."""
    fabrication = _validation(
        critical_errors=["Сумма 1 200 000 тенге выдумана и отсутствует в материалах дела"]
    )
    service = _FakeService(validations=[fabrication, fabrication])

    with pytest.raises(CourtDocumentQualityError) as raised:
        _draft_claim(service)

    failure = raised.value.failure
    assert failure.code is ClaimFailureCode.QA_BLOCKED
    assert any("выдумана" in issue for issue in failure.issues)
    # Причина попадает в лог одной структурированной строкой.
    assert "CLAIM_FAIL stage=qa code=QA_BLOCKED" in failure.log_line()
    # Блокировка наступает только после ремонтной попытки.
    assert service.schema_calls.count("korgan_repaired_claim") == 1


def test_repairable_defect_is_fixed_and_document_is_released() -> None:
    service = _FakeService(
        validations=[
            _validation(critical_errors=["Перепутаны роли сторон в просительной части"]),
            _validation(),
        ]
    )

    draft = _draft_claim(service)

    assert service.schema_calls.count("korgan_repaired_claim") == 1
    assert build_claim_docx(draft).startswith(b"PK")
