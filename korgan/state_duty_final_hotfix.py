from __future__ import annotations

import re

from korgan.robust_production_legal import ProductionOpenAILegalService as _BaseProductionOpenAILegalService


_STATE_DUTY_RE = re.compile(
    r"(?:\bгоспошлин\w*\b|\bгосударственн\w*\s+пошлин\w*\b)",
    re.IGNORECASE,
)


def _is_state_duty_request(text: str) -> bool:
    return bool(_STATE_DUTY_RE.search(text or ""))


def _enforce_single_state_duty_request(draft) -> None:
    """State duty is deterministic and may appear at most once in the prayer.

    The model may phrase it as either «госпошлина» or «государственная пошлина».
    Remove every model-generated variant and re-add exactly one canonical request
    from draft.state_duty, which was already calculated by deterministic code.
    """
    draft.requests = [
        request for request in list(draft.requests)
        if not _is_state_duty_request(request)
    ]

    duty = (getattr(draft, "state_duty", "") or "").strip()
    if not duty or duty.startswith("[ТРЕБУЕТ"):
        return

    amount = duty.split("(", 1)[0].strip()
    if not amount:
        return

    draft.requests.append(
        f"Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины в размере {amount}."
    )


class ProductionOpenAILegalService(_BaseProductionOpenAILegalService):
    """Final guard: state-duty wording cannot create a false QA block."""

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
