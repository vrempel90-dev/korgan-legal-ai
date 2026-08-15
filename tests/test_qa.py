from korgan_legal_ai.domain.models import (
    DocumentType,
    DraftDocument,
    Fact,
    LockedCase,
    Party,
    PartyRole,
    ReadinessStatus,
)
from korgan_legal_ai.qa.service import FinalLegalQA


def make_case():
    return LockedCase(
        raw_text="x",
        parties=[Party(name="Истец", role=PartyRole.CLAIMANT), Party(name="Ответчик", role=PartyRole.DEFENDANT)],
        facts=[Fact(statement="Есть долг")],
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
        text="Истец: Истец\nОтветчик: Ответчик\nИстец просит взыскать долг. Точные нормы требуют проверки.",
        readiness=ReadinessStatus.LAWYER_REVIEW_DRAFT,
        summary="x",
    )
    assert FinalLegalQA().check(make_case(), document, []).passed is True
