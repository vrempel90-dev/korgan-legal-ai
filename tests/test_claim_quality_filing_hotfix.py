from korgan.claim_quality_hotfix import (
    FILING_ACTION_PREFIX,
    _patched_assess_document_quality,
    polish_claim_before_quality,
)
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            "Обязательства должны исполняться надлежащим образом "
            "[основание: статья 272 ГК РК; текст нормы: «Обязательства должны исполняться надлежащим образом в соответствии с условиями обязательства и требованиями законодательства.»; источник: https://adilet.zan.kz/rus/docs/K940001000_]"
        ],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K940001000_"],
        notes=[],
    )


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании денежных средств",
        court="Суд общей юрисдикции города Алматы по месту нахождения ответчика",
        claimant=["Иванов Иван, ИИН 900101300001, адрес: г. Алматы"],
        defendant=["ТОО «Ответчик», БИН 150640012233, адрес: г. Алматы"],
        price_of_claim="1 000 000 тенге",
        state_duty="10 000 тенге",
        facts=[
            "Между сторонами заключен договор.",
            "Истец перечислил 1 000 000 тенге.",
            "Ответчик обязательство не исполнил.",
        ],
        legal_basis=["Обязательства должны исполняться надлежащим образом."],
        requests=["Взыскать 1 000 000 тенге."],
        attachments=["Договор", "Платежный документ"],
        verification_notes=["Точное наименование суда подлежит проверке перед подачей."],
        source_urls=[],
    )


def test_verified_article_is_carried_into_legal_basis() -> None:
    draft = _draft()
    polish_claim_before_quality("Истец перечислил 1 000 000 тенге по договору.", _research(), draft)
    assert any("статья 272" in item.lower() for item in draft.legal_basis)
    assert not any("https://" in item for item in draft.legal_basis)


def test_invented_subjective_harm_is_removed() -> None:
    draft = _draft()
    draft.facts.append("Нарушение вызвало переживания и неудобства истца.")
    polish_claim_before_quality("Пользователь описал только договор и невозврат денег.", _research(), draft)
    assert not any("пережив" in item.lower() or "неудобств" in item.lower() for item in draft.facts)


def test_unknown_exact_court_is_filing_action_not_substantive_hard_blocker() -> None:
    draft = _draft()
    report = _patched_assess_document_quality(
        "claim",
        "Истец перечислил 1 000 000 тенге по договору. Ответчик ТОО, адрес: г. Алматы.",
        _research(),
        draft,
    )
    assert not any("наименование суда" in item.lower() for item in report.hard_blockers)
    assert any(str(item).startswith(FILING_ACTION_PREFIX) for item in report.issues)
    assert report.score >= 8.5
