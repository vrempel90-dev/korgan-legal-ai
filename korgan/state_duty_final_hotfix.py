from __future__ import annotations

# Наследоваться нужно от civil_claim_hotfix, а не от robust_production_legal:
# иначе изоляция стейл-налоговых норм (_sanitize_civil_research) и послабление
# по статье 716 для займа (_core_profile_supported) выпадают из рантайма, хотя
# README описывает их как действующие.
from korgan.civil_claim_hotfix import ProductionOpenAILegalService as _BaseProductionOpenAILegalService

# Критерий «это просьба о госпошлине» один на весь пайплайн: он же используется
# в korgan.fast_v2_production_legal при детерминированной нормализации.
from korgan.fast_v2_production_legal import _STATE_DUTY_RE, _is_state_duty_request
from korgan.legal_calc import NEEDS_CALCULATION_MARKER, gosposhlina_line
from korgan.legal_types import VerificationStatus
from korgan.repaired_production_legal import _has_state_duty_payment_proof

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


def _enforce_single_state_duty_request(draft) -> None:
    """State duty is deterministic and may appear at most once in the prayer.

    The model may phrase it as either «госпошлина» or «государственная пошлина».
    Remove every model-generated variant and re-add exactly one canonical request
    only when the claimant actually pays the duty and can seek recovery of that
    court expense.  Deferred/exempt duty must not be disguised as an expense the
    claimant already incurred.
    """
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


def _refresh_duty_notes(case_context: str, draft) -> None:
    duty = (getattr(draft, "state_duty", "") or "").strip()
    draft.verification_notes = [
        note for note in list(draft.verification_notes)
        if note not in {_DUTY_RECEIPT_NOTE, _DUTY_RECHECK_NOTE}
    ]

    if duty == NEEDS_CALCULATION_MARKER:
        draft.verification_notes.append(_DUTY_RECHECK_NOTE)
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        return

    lowered = duty.lower()
    if any(marker in lowered for marker in _DUTY_NOT_PAID_MARKERS):
        return

    if not _has_state_duty_payment_proof(case_context):
        draft.verification_notes.append(_DUTY_RECEIPT_NOTE)
        draft.status = VerificationStatus.NEEDS_VERIFICATION


class ProductionOpenAILegalService(_BaseProductionOpenAILegalService):
    """Final court-claim runtime guard for current state-duty rules."""

    async def draft_claim(self, case_context, research, language="ru"):
        draft = await super().draft_claim(case_context, research, language=language)

        # Earlier production layers intentionally compute a basic amount before
        # QA.  Recompute once, after the final structured claim exists, because
        # only now can we see whether the prayer combines property and an
        # independent non-property demand (art. 665(4)), consumer deferral, etc.
        draft.state_duty = gosposhlina_line(
            case_context,
            draft.price_of_claim,
            title=draft.title,
            requests=draft.requests,
        )
        _enforce_single_state_duty_request(draft)
        _refresh_duty_notes(case_context, draft)
        return draft

    async def validate_claim(self, case_context, research, draft):
        _enforce_single_state_duty_request(draft)
        result = await super().validate_claim(case_context, research, draft)

        # If deterministic normalization left at most one duty request, any
        # residual model complaint about a duplicate duty is a validator false
        # positive and must not trigger an expensive repair/refusal.
        duty_count = sum(_is_state_duty_request(x) for x in draft.requests)
        if duty_count <= 1:
            result["critical_errors"] = [
                item for item in result.get("critical_errors", [])
                if not (
                    "дубли" in item.lower()
                    and "пошлин" in item.lower()
                )
            ]
            result["unsupported_legal_claims"] = [
                item for item in result.get("unsupported_legal_claims", [])
                if not (
                    "дубли" in item.lower()
                    and "пошлин" in item.lower()
                )
            ]
        return result
