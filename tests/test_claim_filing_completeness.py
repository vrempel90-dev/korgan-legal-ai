from korgan.claim_filing_accuracy import FILING_ACTION_PREFIX
from korgan.claim_filing_completeness import enforce_article148_party_completeness
from korgan.legal_types import ClaimDraft, VerificationStatus


def _draft(*, claimant: list[str], defendant: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Иск о взыскании задолженности",
        court="Алмалинский районный суд",
        claimant=claimant,
        defendant=defendant,
        price_of_claim="1 000 000 тенге",
        state_duty="10 000 тенге",
        facts=["Обязательство не исполнено."],
        legal_basis=["Проверенное основание."],
        requests=["Взыскать задолженность 1 000 000 тенге."],
        attachments=["Договор"],
        verification_notes=[],
        source_urls=[],
    )


def test_complete_physical_claimant_and_defendant_pass():
    draft = _draft(
        claimant=[
            "Иванов Иван Иванович, дата рождения 01.01.1990, ИИН 900101300001, "
            "адрес: г. Алматы, ул. Абая, д. 10"
        ],
        defendant=["Петров Петр Петрович, адрес: г. Алматы, ул. Толе би, д. 20"],
    )

    assert enforce_article148_party_completeness(draft) == []
    assert draft.verification_notes == []


def test_missing_physical_claimant_required_fields_blocks_filing_ready():
    draft = _draft(
        claimant=["Иванов Иван Иванович"],
        defendant=["Петров Петр Петрович, адрес: г. Алматы, ул. Толе би, д. 20"],
    )

    issues = enforce_article148_party_completeness(draft)

    assert any("дату рождения" in issue for issue in issues)
    assert any("место жительства" in issue for issue in issues)
    assert any("ИИН" in issue for issue in issues)
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert all(note.startswith(FILING_ACTION_PREFIX) for note in draft.verification_notes)


def test_legal_entity_claimant_requires_bin_location_and_bank_details():
    draft = _draft(
        claimant=["ТОО «Истец»"],
        defendant=["ТОО «Ответчик», адрес: г. Алматы, ул. Жандосова, д. 5"],
    )

    issues = enforce_article148_party_completeness(draft)

    assert any("БИН" in issue for issue in issues)
    assert any("место нахождения" in issue for issue in issues)
    assert any("банковские реквизиты" in issue for issue in issues)


def test_defendant_iin_bin_and_bank_are_not_hard_required_when_unknown():
    draft = _draft(
        claimant=[
            "Иванов Иван Иванович, дата рождения 01.01.1990, ИИН 900101300001, "
            "адрес: г. Алматы, ул. Абая, д. 10"
        ],
        defendant=["ТОО «Ответчик», адрес: г. Алматы, ул. Жандосова, д. 5"],
    )

    issues = enforce_article148_party_completeness(draft)

    assert issues == []


def test_individual_entrepreneur_is_not_treated_as_legal_entity():
    draft = _draft(
        claimant=[
            "ИП Иванов Иван Иванович, дата рождения 01.01.1990, ИИН 900101300001, "
            "адрес: г. Алматы, ул. Абая, д. 10"
        ],
        defendant=["ТОО «Ответчик», адрес: г. Алматы, ул. Жандосова, д. 5"],
    )

    issues = enforce_article148_party_completeness(draft)

    assert issues == []
