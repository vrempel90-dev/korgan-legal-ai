"""Исковая давность заявляется только из фактов дела и VERIFIED-нормы.

Дата или номер статьи внутри самого отзыва — не доказательство. Модель способна
написать и дату начала срока, и дату его окончания, и статью 178 ГК РК без
единой опоры во входящих материалах. Прежний шлюз видел эти токены и выпускал
возражение, хотя оно целиком было создано самим проверяемым документом.

Проверка разделяет три вещи: даты должны присутствовать в материалах, правило о
длительности — в source-bound VERIFIED-тексте нормы, а заявленная дата окончания
должна детерминированно совпасть с началом плюс подтверждённое число лет.
"""

from __future__ import annotations

from korgan.document_quality import assess_document_quality
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.provision_check import verified_claim_line
from korgan.response_types import ResponseObjection, ResponseToClaimDraft

ADILET = "https://adilet.zan.kz/rus/docs/K940001000_"
ARTICLE_178 = (
    "Общий срок исковой давности устанавливается в три года. Для отдельных видов "
    "требований законодательными актами могут устанавливаться специальные сроки "
    "исковой давности, сокращенные или более длительные по сравнению с общим сроком."
)
GENERAL_NORM = (
    "Обязательство должно исполняться надлежащим образом в соответствии с условиями "
    "обязательства и требованиями законодательства."
)
COURT = "Специализированный межрайонный экономический суд города Астаны"
BASE_CONTEXT = (
    "Истец: ТОО «АЛЬЯНС», БИН 180340012345.\n"
    "Ответчик: ТОО «СТРОЙ ГРУПП», БИН 200140012345.\n"
    "Срок оплаты по пункту 4.2 договора наступил 15.01.2023.\n"
    "Ответчик исходит из окончания общего трёхлетнего срока 15.01.2026.\n"
    "Иск подан 20.02.2026."
)
LIMITATION_TEXT = (
    "Срок исковой давности по требованию истёк 15.01.2026: течение началось "
    "15.01.2023 со дня наступления срока оплаты; общий срок составляет три года "
    "согласно статье 178 ГК РК."
)


def _verified_limitation() -> str:
    return verified_claim_line(
        "Общий срок исковой давности устанавливается в три года",
        "статья 178 ГК РК",
        ARTICLE_178,
        ADILET,
    )


def _research(*, limitation_verified: bool) -> LegalResearch:
    claims = []
    if limitation_verified:
        claims.append(_verified_limitation())
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=["статья 178 ГК РК"] if limitation_verified else [],
        procedural_requirements=[],
        verified_claims=claims,
        unverified_claims=[],
        notes=[f"VERIFIED_COURT: {COURT}"],
        source_urls=[ADILET],
    )


def _response(objection: str = LIMITATION_TEXT) -> ResponseToClaimDraft:
    return ResponseToClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ОТЗЫВ НА ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court=COURT,
        case_number="7199-26-00-2/1234",
        claimant=["ТОО «АЛЬЯНС», БИН 180340012345"],
        defendant=["ТОО «СТРОЙ ГРУПП», БИН 200140012345"],
        claim_summary=["Истец просит взыскать основной долг 1 200 000 тенге."],
        position=["Иск не подлежит удовлетворению."],
        objections=[ResponseObjection(text=objection)],
        calculation_review=["Основной долг 1 200 000 тенге оспаривается полностью."],
        legal_basis=[objection],
        requests=["Отказать в удовлетворении иска."],
        attachments=["Копия договора"],
        verification_notes=[],
        source_urls=[ADILET],
    )


def test_dates_and_article_written_only_by_the_draft_do_not_support_limitation() -> None:
    report = assess_document_quality(
        "response_to_claim",
        "Истец и ответчик заключили договор; иных дат материалы не содержат.",
        _research(limitation_verified=False),
        _response(),
    )

    assert report.ready is False
    assert any("исковой давности" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers


def test_dates_in_materials_without_a_source_bound_limitation_norm_are_insufficient() -> None:
    report = assess_document_quality(
        "response_to_claim", BASE_CONTEXT, _research(limitation_verified=False), _response()
    )

    assert report.ready is False
    assert any("verified" in blocker.lower() and "исковой давности" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers


def test_source_bound_norm_without_the_dates_in_materials_is_insufficient() -> None:
    report = assess_document_quality(
        "response_to_claim",
        "Истец и ответчик заключили договор; срок оплаты в материалах не указан.",
        _research(limitation_verified=True),
        _response(),
    )

    assert report.ready is False
    assert any("даты" in blocker.lower() and "исковой давности" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers


def test_wrong_expiry_date_is_blocked_even_when_start_and_norm_are_verified() -> None:
    wrong = LIMITATION_TEXT.replace("истёк 15.01.2026", "истёк 15.01.2025")
    context = BASE_CONTEXT.replace(
        "Ответчик исходит из окончания общего трёхлетнего срока 15.01.2026.",
        "В переписке от 15.01.2025 стороны обсуждали исполнение договора.",
    )

    report = assess_document_quality(
        "response_to_claim", context, _research(limitation_verified=True), _response(wrong)
    )

    assert report.ready is False
    assert any("расчёт срока" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers


def test_supported_limitation_objection_passes_the_special_guard() -> None:
    report = assess_document_quality(
        "response_to_claim", BASE_CONTEXT, _research(limitation_verified=True), _response()
    )

    assert not any("исковой давности" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers


def test_structured_objection_uses_anchors_from_its_subclauses_and_prose() -> None:
    structured = ResponseObjection(
        text="Истечение срока исковой давности",
        subclauses=[
            "Течение срока началось 15.01.2023 со дня наступления срока оплаты.",
            "Срок истёк 15.01.2026; иск подан 20.02.2026.",
        ],
        prose=["Общий срок составляет три года согласно статье 178 ГК РК."],
    )
    draft = _response()
    draft.objections = [structured]
    draft.legal_basis = ["\n".join(structured.body_lines())]

    report = assess_document_quality(
        "response_to_claim", BASE_CONTEXT, _research(limitation_verified=True), draft
    )

    assert not any("исковой давности" in blocker.lower() for blocker in report.hard_blockers), report.hard_blockers
