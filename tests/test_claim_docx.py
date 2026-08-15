from korgan.claim_docx import build_claim_docx
from korgan.legal_types import ClaimDraft, VerificationStatus


def test_claim_docx_is_valid_zip_container() -> None:
    draft = ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="",
        claimant=[],
        defendant=[],
        price_of_claim="",
        facts=["Факт из материалов дела"],
        legal_basis=["Подтвержденная правовая основа"],
        requests=["Удовлетворить заявленное требование"],
        attachments=["Копия документа"],
        verification_notes=["Уточнить подсудность"],
        source_urls=["https://adilet.zan.kz/rus/docs/K1500000377"],
    )

    payload = build_claim_docx(draft)

    assert payload.startswith(b"PK")
    assert len(payload) > 1000
