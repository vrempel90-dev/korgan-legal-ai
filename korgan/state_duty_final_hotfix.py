from __future__ import annotations

from korgan.civil_claim_hotfix import ProductionOpenAILegalService as _BaseProductionOpenAILegalService
from korgan.fast_v2_production_legal import _STATE_DUTY_RE, _is_state_duty_request
from korgan.legal.calc import Rates, load_rates
from korgan.legal_calc import NEEDS_CALCULATION_MARKER, gosposhlina_line
from korgan.legal_types import VerificationStatus
from korgan.production_legal import STATE_DUTY_NOTE
from korgan.repaired_production_legal import (
    _STATE_DUTY_ATTACHMENT,
    _STATE_DUTY_ATTACHMENT_NOTE,
    _has_state_duty_payment_proof,
)

__all__ = ["ProductionOpenAILegalService", "_STATE_DUTY_RE", "_is_state_duty_request"]


_DUTY_NOT_PAID_MARKERS = ("уплата отсрочена", "0 тенге (освобождение")
_DUTY_RECEIPT_NOTE = (
    "До подачи иска необходимо приложить документ, подтверждающий уплату государственной пошлины, "
    "либо подтвержденное законом основание освобождения/отсрочки."
)
_DUTY_RECHECK_NOTE = (
    "Категория иска, статус плательщика либо применимая льгота не позволяют безопасно рассчитать "
    "государственную пошлину автоматически — требуется проверка по действующей статье 665/668 НК РК."
)
_STALE_DUTY_NOTES = {
    STATE_DUTY_NOTE,
    _STATE_DUTY_ATTACHMENT_NOTE,
    _DUTY_RECEIPT_NOTE,
    _DUTY_RECHECK_NOTE,
}


def _enforce_single_state_duty_request(draft) -> None:
    """Keep one recovery request only for a duty the claimant actually pays."""
    draft.requests = [
        request for request in list(draft.requests)
        if not _is_state_duty_request(request)
    ]

    duty = (getattr(draft, "state_duty", "") or "").strip()
    lowered = duty.lower()
    if not duty or duty.startswith("[ТРЕБУЕТ"):
        return
    if any(marker in lowered for marker in _DUTY_NOT_PAID_MARKERS):
        return

    amount = duty.split("(", 1)[0].strip()
    if not amount:
        return

    draft.requests.append(
        f"Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины в размере {amount}."
    )


def _clear_legacy_duty_artifacts(draft) -> None:
    draft.verification_notes = [
        note for note in list(draft.verification_notes)
        if note not in _STALE_DUTY_NOTES
    ]
    draft.attachments = [
        item for item in list(draft.attachments)
        if item != _STATE_DUTY_ATTACHMENT
    ]


def _refresh_duty_notes(case_context: str, draft) -> None:
    """Rebuild duty-related notes/attachments from the final calculation only."""
    duty = (getattr(draft, "state_duty", "") or "").strip()
    _clear_legacy_duty_artifacts(draft)

    if duty == NEEDS_CALCULATION_MARKER:
        draft.verification_notes.append(_DUTY_RECHECK_NOTE)
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        return

    lowered = duty.lower()
    if any(marker in lowered for marker in _DUTY_NOT_PAID_MARKERS):
        # Statutory deferral/exemption means there is no paid-duty receipt to
        # demand from the claimant.  Do not leave the superclass placeholder.
        return

    if not _has_state_duty_payment_proof(case_context):
        draft.attachments.append(_STATE_DUTY_ATTACHMENT)
        draft.verification_notes.append(_DUTY_RECEIPT_NOTE)
        draft.status = VerificationStatus.NEEDS_VERIFICATION


class ProductionOpenAILegalService(_BaseProductionOpenAILegalService):
    """Final court-claim runtime guard for current state-duty rules."""

    def __init__(self, *args, legal_rates: Rates | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._legal_rates = legal_rates or load_rates()

    async def draft_claim(self, case_context, research, language="ru"):
        draft = await super().draft_claim(case_context, research, language=language)

        # Recalculate after the final structured prayer exists.  This is the
        # first point where mixed/non-property relief can be classified safely.
        draft.state_duty = gosposhlina_line(
            case_context,
            draft.price_of_claim,
            title=draft.title,
            requests=draft.requests,
            rates=self._legal_rates,
        )
        _enforce_single_state_duty_request(draft)
        _refresh_duty_notes(case_context, draft)

        # Superclasses may have set NEEDS_VERIFICATION solely because their
        # earlier price-only duty pass could not classify the case. Once those
        # stale notes are removed, restore VERIFIED only when legal research is
        # itself verified and no other document-level verification note remains.
        if draft.verification_notes:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
        elif research.status == VerificationStatus.VERIFIED:
            draft.status = VerificationStatus.VERIFIED
        return draft

    async def validate_claim(self, case_context, research, draft):
        _enforce_single_state_duty_request(draft)
        result = await super().validate_claim(case_context, research, draft)

        duty_count = sum(_is_state_duty_request(x) for x in draft.requests)
        if duty_count <= 1:
            result["critical_errors"] = [
                item for item in result.get("critical_errors", [])
                if not ("дубли" in item.lower() and "пошлин" in item.lower())
            ]
            result["unsupported_legal_claims"] = [
                item for item in result.get("unsupported_legal_claims", [])
                if not ("дубли" in item.lower() and "пошлин" in item.lower())
            ]
        return result
