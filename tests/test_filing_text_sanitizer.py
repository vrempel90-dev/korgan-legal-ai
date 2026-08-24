from korgan.filing_text_sanitizer import sanitize_claim_filing_text
from korgan.legal_types import ClaimDraft, VerificationStatus


def test_claim_sanitizer_removes_internal_fields_glued_indexes_and_meta_attachment() -> None:
    draft = ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление",
        court="Суд",
        claimant=["ТОО «Истец»"],
        defendant=["ТОО «Ответчик»"],
        price_of_claim="3 560 000 тенге",
        state_duty="",
        late_interest="",
        facts=[
            "2. Имеется подтверждение отправки. claim_amount: 360 000 тенге2",
        ],
        legal_basis=[],
        requests=[
            "1. Взыскать основной долг 3 200 000 тенге.",
            "2. Взыскать неустойку 360 000 тенге.",
        ],
        attachments=[
            "Договор поставки № 10",
            "Уточнение к ранее описанному юридическому документу: дополнительные сведения пользователя",
        ],
        verification_notes=[],
        source_urls=[],
    )

    sanitize_claim_filing_text(draft)

    assert draft.facts == ["Имеется подтверждение отправки. 360 000 тенге"]
    assert draft.requests == [
        "Взыскать основной долг 3 200 000 тенге.",
        "Взыскать неустойку 360 000 тенге.",
    ]
    assert draft.attachments == ["Договор поставки № 10"]
    assert "claim_amount" not in "\n".join(draft.facts)
