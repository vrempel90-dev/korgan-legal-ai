from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.production_legal import _known_party_data_issues


def test_inflected_claimant_and_defendant_address_labels_are_role_bound() -> None:
    context = (
        "Адреса: Адрес проживания истца: г. Алматы, Медеуский район, ул. Тестовая, д. 15, кв. 21; "
        "Адрес регистрации и проживания ответчика: г. Алматы, Алмалинский район, ул. Условная, д. 44, кв. 12"
    )
    draft = ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление",
        court="Суд",
        claimant=["Ахметов Руслан Маратович", "Адрес: г. Алматы, Медеуский район, ул. Тестовая, д. 15, кв. 21"],
        defendant=["Садыков Тимур Ерланович", "Адрес: г. Алматы, Алмалинский район, ул. Условная, д. 44, кв. 12"],
        price_of_claim="2 400 000 тенге",
        facts=[],
        legal_basis=[],
        requests=[],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )

    assert _known_party_data_issues(context, draft) == []
