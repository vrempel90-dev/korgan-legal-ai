from __future__ import annotations

import re

from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.production_legal import (
    COURT_NOTE,
    ProductionOpenAILegalService as _BaseProductionOpenAILegalService,
)


_CLAIMANT_ROLE_MARKERS = (
    "истец",
    "истца",
    "истцу",
    "займодав",
    "кредитор",
)

_DEFENDANT_ROLE_MARKERS = (
    "ответчик",
    "ответчика",
    "ответчику",
    "заемщик",
    "заёмщик",
    "должник",
)

_OPTIONAL_CONTACT_MARKERS = (
    "телефон",
    "сотов",
    "мобильн",
    "e-mail",
    "email",
    "электронн",
)

_DOB_MARKERS = (
    "дата рождения",
    "дата рожд.",
    "родился",
    "родилась",
)

_DOB_PLACEHOLDER = "Дата рождения: [ТРЕБУЕТ УТОЧНЕНИЯ: дата рождения истца]"
_DOB_NOTE = (
    "Не установлена дата рождения физического лица-истца — требуется уточнить обязательный реквизит иска перед подачей."
)

_STATE_DUTY_ATTACHMENT = (
    "[ТРЕБУЕТ ДОБАВИТЬ: документ, подтверждающий уплату государственной пошлины, "
    "либо ходатайство об отсрочке по уплате государственной пошлины]"
)
_STATE_DUTY_ATTACHMENT_NOTE = (
    "В материалах нет документа, подтверждающего уплату государственной пошлины, либо ходатайства об отсрочке; "
    "его необходимо добавить к иску перед подачей."
)


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", value.lower())


def _party_for_prefix(prefix: str) -> str | None:
    lowered = prefix.lower()
    if any(marker in lowered for marker in _CLAIMANT_ROLE_MARKERS):
        return "claimant"
    if any(marker in lowered for marker in _DEFENDANT_ROLE_MARKERS):
        return "defendant"
    return None


def _append_if_missing(target: list[str], label: str, value: str) -> None:
    clean = value.strip()
    if not clean or clean.lower() == "не установлено":
        return
    normalized_existing = _normalize("\n".join(target))
    if _normalize(clean) in normalized_existing:
        return
    target.append(f"{label}: {clean}")


def _restore_role_bound_bucket(
    case_context: str,
    draft: ClaimDraft,
    bucket: str,
    label: str,
) -> None:
    for line in case_context.splitlines():
        if not line.startswith(bucket):
            continue
        raw = line.split(":", 1)[1].strip()
        if not raw or raw.lower() == "не установлено":
            continue

        for value in raw.split(";"):
            candidate = value.strip()
            if ":" not in candidate:
                continue
            prefix, remainder = candidate.split(":", 1)
            party = _party_for_prefix(prefix)
            if party == "claimant":
                _append_if_missing(draft.claimant, label, remainder)
            elif party == "defendant":
                _append_if_missing(draft.defendant, label, remainder)


def _remove_unsupported_conditionals(draft: ClaimDraft) -> None:
    """Drop optional court-text items that the model itself marked as conditional."""
    for field_name in ("facts", "legal_basis", "requests", "attachments"):
        values = list(getattr(draft, field_name))
        cleaned = [item for item in values if "при наличии" not in item.lower()]
        setattr(draft, field_name, cleaned)


def _is_placeholder(value: str) -> bool:
    upper = value.upper()
    return "[ТРЕБУЕТ УТОЧНЕНИЯ" in upper or "[ТРЕБУЕТ ДОБАВИТЬ" in upper


def _drop_optional_unknown_contacts(draft: ClaimDraft) -> None:
    """Unknown phone/e-mail are optional, so do not render them as filing blockers."""
    for field_name in ("claimant", "defendant"):
        values = list(getattr(draft, field_name))
        cleaned: list[str] = []
        for item in values:
            lowered = item.lower()
            if _is_placeholder(item) and any(marker in lowered for marker in _OPTIONAL_CONTACT_MARKERS):
                continue
            cleaned.append(item)
        setattr(draft, field_name, cleaned)


def _claimant_is_natural_person(draft: ClaimDraft) -> bool:
    text = "\n".join(draft.claimant).lower()
    return "иин" in text and "бин" not in text and bool(re.search(r"(?<!\d)\d{12}(?!\d)", text))


def _restore_claimant_dob(case_context: str, draft: ClaimDraft) -> None:
    claimant_text = "\n".join(draft.claimant).lower()
    if any(marker in claimant_text for marker in _DOB_MARKERS):
        return

    for line in case_context.splitlines():
        for segment in line.split(";"):
            lowered = segment.lower()
            if "дата рождения" not in lowered:
                continue
            if not any(marker in lowered for marker in _CLAIMANT_ROLE_MARKERS):
                continue
            match = re.search(r"(\d{2}[./-]\d{2}[./-]\d{4}|\d{4}[./-]\d{2}[./-]\d{2})", segment)
            if match:
                draft.claimant.append(f"Дата рождения: {match.group(1)}")
                return


def _enforce_claimant_dob(case_context: str, draft: ClaimDraft) -> None:
    if not _claimant_is_natural_person(draft):
        return
    _restore_claimant_dob(case_context, draft)
    if any(marker in "\n".join(draft.claimant).lower() for marker in _DOB_MARKERS):
        return
    if _DOB_PLACEHOLDER not in draft.claimant:
        draft.claimant.append(_DOB_PLACEHOLDER)
    if _DOB_NOTE not in draft.verification_notes:
        draft.verification_notes.append(_DOB_NOTE)


def _has_state_duty_payment_proof(case_context: str) -> bool:
    lowered = case_context.lower()
    if "госпошлин" not in lowered and "государственн" not in lowered:
        return False
    payment_markers = (
        "квитанц",
        "чек",
        "платежн",
        "платёжн",
        "оплачен",
        "оплачена",
        "уплачен",
        "уплачена",
    )
    return any(marker in lowered for marker in payment_markers)


def _enforce_state_duty_attachment(case_context: str, draft: ClaimDraft) -> None:
    if _has_state_duty_payment_proof(case_context):
        draft.verification_notes[:] = [
            note for note in draft.verification_notes if note != _STATE_DUTY_ATTACHMENT_NOTE
        ]
        draft.attachments[:] = [
            item for item in draft.attachments if item != _STATE_DUTY_ATTACHMENT
        ]
        return

    if _STATE_DUTY_ATTACHMENT not in draft.attachments:
        draft.attachments.append(_STATE_DUTY_ATTACHMENT)
    if _STATE_DUTY_ATTACHMENT_NOTE not in draft.verification_notes:
        draft.verification_notes.append(_STATE_DUTY_ATTACHMENT_NOTE)


def _drop_nonstandard_party_summons(draft: ClaimDraft) -> None:
    cleaned: list[str] = []
    for request in draft.requests:
        lowered = request.lower()
        if (
            "вызвать" in lowered
            and "судеб" in lowered
            and "истц" in lowered
            and "ответчик" in lowered
            and "объяснен" in lowered
        ):
            continue
        cleaned.append(request)
    draft.requests = cleaned


def _prepare_draft_for_validation(case_context: str, draft: ClaimDraft) -> None:
    _remove_unsupported_conditionals(draft)
    _drop_optional_unknown_contacts(draft)
    _drop_nonstandard_party_summons(draft)

    # Restore only requisites that the extractor explicitly bound to one party.
    _restore_role_bound_bucket(case_context, draft, "Адреса:", "Адрес")
    _restore_role_bound_bucket(case_context, draft, "Идентификаторы:", "ИИН/БИН")
    _restore_role_bound_bucket(case_context, draft, "Контакты:", "Контакт")

    _enforce_claimant_dob(case_context, draft)
    _enforce_state_duty_attachment(case_context, draft)


def _restore_verified_court(research: LegalResearch, draft: ClaimDraft) -> None:
    """Replace the generic court placeholder only with a source-bound verified court."""
    court = ""
    for note in research.notes:
        if note.startswith("VERIFIED_COURT:"):
            court = note.split(":", 1)[1].strip()
            break
    if not court:
        return

    normalized = _normalize(court)
    if not normalized or not any(normalized in _normalize(claim) for claim in research.verified_claims):
        return

    draft.court = court
    draft.verification_notes[:] = [note for note in draft.verification_notes if note != COURT_NOTE]


def _sync_state_duty_request(draft: ClaimDraft) -> None:
    """Use the deterministic duty amount in the prayer for relief instead of a vague future amount."""
    duty = draft.state_duty.strip()
    if not duty or duty.startswith("[ТРЕБУЕТ"):
        return

    amount = duty.split("(", 1)[0].strip()
    if not amount:
        return

    # Remove only vague generic expense requests. Specific proven expenses stay intact.
    cleaned: list[str] = []
    for request in draft.requests:
        lowered = request.lower()
        vague = (
            "судебн" in lowered
            and "расход" in lowered
            and (
                "который будет подтверж" in lowered
                or "которые будут подтверж" in lowered
                or "документально подтверж" in lowered
            )
            and "госпошлин" not in lowered
        )
        if vague:
            continue
        cleaned.append(request)
    draft.requests = cleaned

    if not any("госпошлин" in request.lower() for request in draft.requests):
        draft.requests.append(
            f"Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины в размере {amount}."
        )


class ProductionOpenAILegalService(_BaseProductionOpenAILegalService):
    """Production service with deterministic pre-QA repair and the original hard gate."""

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)

        # The base service refuses to guess a court. Restore it only when the
        # source-bound research produced VERIFIED_COURT from an official page.
        _restore_verified_court(research, draft)

        # The base service calculates the duty after model QA. Now reuse that
        # deterministic amount in the prayer for relief and keep the filing
        # attachment requirement explicit.
        _sync_state_duty_request(draft)
        _prepare_draft_for_validation(case_context, draft)

        if research.unverified_claims or draft.verification_notes:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
        else:
            draft.status = research.status
        return draft

    async def validate_claim(
        self,
        case_context: str,
        research: LegalResearch,
        draft: ClaimDraft,
    ) -> dict[str, list[str]]:
        _prepare_draft_for_validation(case_context, draft)
        return await super().validate_claim(case_context, research, draft)
