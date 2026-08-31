"""Раунд правки документа обязан видеть всё, что документ уже содержит.

Когда quality gate находит замечания, KORGAN отправляет модели текущий
черновик как ``current_payload`` и просит исправить перечисленное. Если
сборщик payload не кладёт туда какой-то раздел, модель этого раздела не видит
и собирает его заново — расчёт пересчитывается с нуля, признанные и
оспариваемые обстоятельства теряются, суммы между проходами расходятся.
Воспроизводимость расчёта, ради которой раздел и заводился, при этом пропадает.

Проверка структурная и не зависит от конкретных полей: она сверяет ключи
payload с обязательными полями той схемы, с которой этот payload уходит.
Поэтому она поймает и следующее добавление раздела, а не только текущее.
"""

from __future__ import annotations

import pytest

from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.pretrial import _PRETRIAL_SCHEMA, PretrialDraft
from korgan.pretrial_response import _PRETRIAL_RESPONSE_SCHEMA, PretrialResponseDraft
from korgan.response_legal import _RESPONSE_DRAFT_SCHEMA
from korgan.response_types import ResponseToClaimDraft


def _pretrial() -> PretrialDraft:
    return PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="ДОСУДЕБНАЯ ПРЕТЕНЗИЯ",
        sender=["Отправитель"],
        recipient=["Адресат"],
        facts=["Факт"],
        legal_basis=["Основание"],
        demands=["Требование"],
        deadline="10 дней",
        consequences=["Обращение в суд"],
        attachments=["Приложение"],
        verification_notes=[],
        source_urls=[],
        calculation=["Основной долг: 2 300 000 тенге; основание: договор № 12."],
    )


def _pretrial_response() -> PretrialResponseDraft:
    return PretrialResponseDraft(
        status=VerificationStatus.VERIFIED,
        title="ОТВЕТ НА ПРЕТЕНЗИЮ",
        sender=["Отправитель"],
        recipient=["Адресат"],
        reference="претензия от 05.03.2026 № 7",
        claim_summary=["Требование об оплате 2 300 000 тенге."],
        admitted_circumstances=["Договор заключён 15.01.2026."],
        disputed_circumstances=["Объём работ по акту от 20.02.2026 оспаривается."],
        position=["Признаётся 1 400 000 тенге."],
        objections=["Работы на 900 000 тенге не приняты."],
        calculation_review=["Начисление с 01.03.2026 при сроке оплаты 20.03.2026."],
        legal_basis=["Основание"],
        settlement_offer="Готовы оплатить признанную часть.",
        response_terms=["Оплата в согласованный срок."],
        attachments=["Приложение"],
        verification_notes=[],
        source_urls=[],
    )


def _response_to_claim() -> ResponseToClaimDraft:
    return ResponseToClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ОТЗЫВ НА ИСК",
        court="Суд",
        case_number="дело № 1",
        claimant=["Истец"],
        defendant=["Ответчик"],
        claim_summary=["Истец просит взыскать 2 300 000 тенге."],
        admitted_circumstances=["Договор заключён 15.01.2026."],
        disputed_circumstances=["Объём работ оспаривается."],
        position=["Иск подлежит частичному удовлетворению."],
        objections=["Работы на 900 000 тенге не приняты."],
        calculation_review=["Начисление с 01.03.2026 при сроке оплаты 20.03.2026."],
        legal_basis=["Основание"],
        requests=["Отказать в части."],
        attachments=["Приложение"],
        verification_notes=[],
        source_urls=[],
    )


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def _required(schema: dict) -> set[str]:
    return set(schema.get("required", []))


# Каждый сборщик payload вместе со схемой, в которую этот payload уходит.
def _builders():
    from korgan import response_voice_guard, universal_quality_service, universal_word_quality_guard

    return [
        (
            "universal_word_quality_guard._pretrial_payload",
            universal_word_quality_guard._pretrial_payload(_pretrial()),
            _PRETRIAL_SCHEMA,
        ),
        (
            "universal_word_quality_guard._pretrial_response_payload",
            universal_word_quality_guard._pretrial_response_payload(_pretrial_response()),
            _PRETRIAL_RESPONSE_SCHEMA,
        ),
        (
            "response_voice_guard -> pretrial_response_payload",
            response_voice_guard._pretrial_response_payload(_pretrial_response()),
            _PRETRIAL_RESPONSE_SCHEMA,
        ),
        (
            "response_voice_guard -> response_to_claim_payload",
            response_voice_guard._response_to_claim_payload(_response_to_claim()),
            _RESPONSE_DRAFT_SCHEMA,
        ),
        (
            "universal_quality_service -> response_to_claim_payload",
            universal_quality_service._response_payload(_response_to_claim()),
            _RESPONSE_DRAFT_SCHEMA,
        ),
    ]


@pytest.mark.parametrize("index", range(5))
def test_repair_payload_carries_every_required_schema_field(index: int) -> None:
    name, payload, schema = _builders()[index]
    missing = _required(schema) - set(payload)

    assert not missing, f"{name} не передаёт в раунд правки поля: {sorted(missing)}"


@pytest.mark.parametrize("index", range(5))
def test_repair_payload_does_not_lose_content(index: int) -> None:
    """Непустой раздел черновика не должен приходить в правку пустым."""
    name, payload, _schema = _builders()[index]

    for key, value in payload.items():
        if isinstance(value, list):
            assert value or key in {"verification_notes"}, f"{name}: раздел {key} потерян"
        elif isinstance(value, str):
            assert value, f"{name}: раздел {key} потерян"
