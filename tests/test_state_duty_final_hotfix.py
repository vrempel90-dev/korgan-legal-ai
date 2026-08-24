from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.production_legal import STATE_DUTY_NOTE
from korgan.repaired_production_legal import _STATE_DUTY_ATTACHMENT, _STATE_DUTY_ATTACHMENT_NOTE
from korgan.state_duty_final_hotfix import (
    _enforce_single_state_duty_request,
    _refresh_duty_notes,
)


def _draft(requests: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: суд]",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="800 000 тенге",
        facts=[],
        legal_basis=[],
        requests=requests,
        attachments=[],
        verification_notes=[],
        source_urls=[],
        state_duty="8 000 тенге (1% от цены иска)",
    )


def test_state_duty_variants_collapse_to_one_request() -> None:
    draft = _draft([
        "Взыскать долг 800 000 тенге.",
        "Взыскать госпошлину 8 000 тенге.",
        "Взыскать расходы по уплате государственной пошлины в размере 8 000 тенге.",
    ])

    _enforce_single_state_duty_request(draft)

    duty_requests = [x for x in draft.requests if "пошлин" in x.lower()]
    assert len(duty_requests) == 1
    assert duty_requests[0].endswith("8 000 тенге.")
    assert draft.requests[0] == "Взыскать долг 800 000 тенге."


def test_deferred_consumer_duty_is_not_claimed_as_already_paid_expense() -> None:
    draft = _draft([
        "Взыскать долг 800 000 тенге.",
        "Взыскать госпошлину 8 000 тенге.",
    ])
    draft.state_duty = (
        "Уплата отсрочена до принятия решения судом; расчетная сумма 8 000 тенге "
        "(часть 3 статьи 106 ГПК РК)"
    )

    _enforce_single_state_duty_request(draft)

    assert all("пошлин" not in item.lower() for item in draft.requests)


def test_exempt_duty_is_not_claimed_as_paid_expense() -> None:
    draft = _draft(["Взыскать задолженность по заработной плате 800 000 тенге."])
    draft.state_duty = "0 тенге (освобождение от уплаты: трудовое требование; статья 668 НК РК)"

    _enforce_single_state_duty_request(draft)

    assert all("пошлин" not in item.lower() for item in draft.requests)


def test_deferred_duty_removes_legacy_receipt_placeholder_and_note() -> None:
    draft = _draft(["Взыскать 800 000 тенге."])
    draft.state_duty = "Уплата отсрочена до принятия решения судом; расчетная сумма 8 000 тенге"
    draft.attachments.append(_STATE_DUTY_ATTACHMENT)
    draft.verification_notes.extend([_STATE_DUTY_ATTACHMENT_NOTE, STATE_DUTY_NOTE])

    _refresh_duty_notes("Истец: Иванов Иван, ИИН 000000000101", draft)

    assert _STATE_DUTY_ATTACHMENT not in draft.attachments
    assert _STATE_DUTY_ATTACHMENT_NOTE not in draft.verification_notes
    assert STATE_DUTY_NOTE not in draft.verification_notes


def test_resolved_nonproperty_duty_replaces_legacy_not_calculated_note() -> None:
    draft = _draft(["Обязать ответчика устранить нарушение."])
    draft.state_duty = "2 163 тенге (0,5 МРП за иск неимущественного характера)"
    draft.verification_notes.append(STATE_DUTY_NOTE)

    _refresh_duty_notes("Истец: Иванов Иван, ИИН 000000000101", draft)

    assert STATE_DUTY_NOTE not in draft.verification_notes
    assert any("уплату государственной пошлины" in item for item in draft.attachments)
