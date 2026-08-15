from datetime import date

from korgan_legal_ai.domain.models import (
    DocumentType,
    DraftDocument,
    Fact,
    LockedCase,
    Party,
    PartyRole,
    ReadinessStatus,
    ResearchCitation,
    VerificationStatus,
)
from korgan_legal_ai.qa.service import FinalLegalQA


def make_case():
    return LockedCase(
        raw_text="x",
        parties=[
            Party(name="Истец", role=PartyRole.CLAIMANT),
            Party(name="Ответчик", role=PartyRole.DEFENDANT),
        ],
        facts=[Fact(statement="Есть долг")],
    )


def make_verified_citation(locator: str) -> ResearchCitation:
    return ResearchCitation(
        source_url="https://adilet.zan.kz/rus/docs/test",
        source_title="Проверенная норма",
        law_name="Тестовый кодекс",
        article=locator,
        text_excerpt="Проверенный текст нормы.",
        effective_from=date(2026, 1, 1),
        status=VerificationStatus.VERIFIED,
    )


def test_unverified_article_blocks_output():
    document = DraftDocument(
        document_type=DocumentType.CLAIM,
        text="Истец просит взыскать долг с Ответчик на основании статья 123.",
        readiness=ReadinessStatus.LAWYER_REVIEW_DRAFT,
        summary="x",
    )
    result = FinalLegalQA().check(make_case(), document, [])
    assert result.passed is False
    assert any(v.code == "UNVERIFIED_EXACT_CITATION" for v in result.violations)


def test_no_exact_article_can_pass():
    document = DraftDocument(
        document_type=DocumentType.CLAIM,
        text=(
            "Истец: Истец\nОтветчик: Ответчик\n"
            "Истец просит взыскать долг. Точные нормы требуют проверки."
        ),
        readiness=ReadinessStatus.LAWYER_REVIEW_DRAFT,
        summary="x",
    )
    assert FinalLegalQA().check(make_case(), document, []).passed is True


def test_exact_verified_article_part_point_passes():
    document = DraftDocument(
        document_type=DocumentType.CLAIM,
        text=(
            "Истец: Истец\nОтветчик: Ответчик\n"
            "Основание: статья 665, часть 1, пункт 1."
        ),
        readiness=ReadinessStatus.LAWYER_REVIEW_DRAFT,
        summary="x",
    )
    citation = make_verified_citation("665, часть 1, пункт 1")
    assert FinalLegalQA().check(make_case(), document, [citation]).passed is True


def test_article_only_does_not_pass_when_only_part_point_was_verified():
    document = DraftDocument(
        document_type=DocumentType.CLAIM,
        text="Истец: Истец\nОтветчик: Ответчик\nОснование: статья 665.",
        readiness=ReadinessStatus.LAWYER_REVIEW_DRAFT,
        summary="x",
    )
    citation = make_verified_citation("665, часть 1, пункт 1")
    result = FinalLegalQA().check(make_case(), document, [citation])
    assert result.passed is False
    assert any(v.code == "UNVERIFIED_EXACT_CITATION" for v in result.violations)
