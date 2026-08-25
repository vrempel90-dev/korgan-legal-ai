"""Single deterministic money authority for civil claims.

The model may draft prose, but it must never be the final owner of claim price.
This module reconciles the court prayer into one monetary ledger.  Goal-v2 also
closes the production hole where an explicit debt/contractual-penalty amount was
present in the client input but a drafting pass dropped the money before the
ledger ever saw it.

No legal tariff is chosen here. State-duty routing remains in claim_state_duty.
Every source repair below is fail-closed: only an unambiguous debt amount and an
explicit recovery intent may seed the prayer; contractual penalty is calculated
by the existing deterministic contractual_penalty engine.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from korgan.claim_money_ledger import ClaimMoneyLedger, build_claim_money_ledger
from korgan.legal_calc import format_kzt, parse_all_amounts_kzt, parse_amount_kzt
from korgan.legal_types import ClaimDraft

LOGGER = logging.getLogger(__name__)

CLAIM_PRICE_NEEDS_CALCULATION = "[ТРЕБУЕТ РАСЧЁТА ЦЕНЫ ИСКА]"
NONPROPERTY_PRICE_LABEL = "не определяется (требование неимущественного характера)"

_AMOUNT_RE = re.compile(
    r"(?<!\d)\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:тенге|теңге|тг\b|₸|kzt)",
    re.IGNORECASE,
)
_RECOVERY_RE = re.compile(
    r"(?:\bвзыска\w*\b|\bвернут\w*\b|\bвозврат\w*\b|\bқайтар\w*\b|\bөндір\w*\b)",
    re.IGNORECASE,
)
_PRINCIPAL_RE = re.compile(
    r"(?:основн\w*\s+долг\w*|задолженн\w*|долг\w*|предоплат\w*|аванс\w*|"
    r"стоимост\w*\s+(?:работ|услуг|товар)|оплат\w*\s+(?:работ|услуг|товар)|"
    r"берешек\w*|борыш\w*|алдын\s+ала\s+төлем\w*)",
    re.IGNORECASE,
)
_EXPLICIT_DEBT_RE = re.compile(
    r"(?:основн\w*\s+долг\w*|задолженн\w*|сумм\w*\s+долг\w*|долг\w*\s+(?:состав|в\s+размер)|"
    r"берешек\w*|негізгі\s+борыш\w*)",
    re.IGNORECASE,
)
_NON_DEBT_PRICE_RE = re.compile(
    r"(?:цена\s+договор\w*|стоимост\w*\s+договор\w*|общ\w*\s+стоимост\w*|"
    r"шарт\w*\s+бағас\w*)",
    re.IGNORECASE,
)
_PENALTY_RE = re.compile(
    r"(?:неустойк\w*|пен(?:я|и|ю|ей|е)\b|штраф\w*|процент\w*|"
    r"тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*)",
    re.IGNORECASE,
)
_COST_RE = re.compile(
    r"(?:госпошлин\w*|государственн\w*\s+пошлин\w*|судебн\w*\s+расход\w*|"
    r"представител\w*\s+расход\w*|мемлекеттік\s+баж|сот\s+шығын\w*)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ClaimMoneyAuthorityResult:
    ledger: ClaimMoneyLedger
    price: int | None
    repaired_request: bool = False
    needs_review: bool = False
    reason: str = ""


def _source_amounts(case_context: str, draft: ClaimDraft) -> set[int]:
    source = "\n".join([case_context or "", *[str(x) for x in draft.facts or []]])
    return set(parse_all_amounts_kzt(source))


def _principal_request_without_amount(request: str) -> bool:
    text = str(request or "").strip()
    if not text or _AMOUNT_RE.search(text) or _COST_RE.search(text):
        return False
    if not _RECOVERY_RE.search(text):
        return False
    if _PENALTY_RE.search(text):
        return False
    return bool(_PRINCIPAL_RE.search(text))


def _append_amount(request: str, amount: int) -> str:
    text = " ".join(str(request or "").split()).strip()
    if not text:
        return text
    punctuation = "." if text.endswith(".") else ""
    core = text[:-1].rstrip() if punctuation else text
    return f"{core} в размере {format_kzt(amount)}{punctuation or '.'}"


def _source_principal_amount(case_context: str) -> int | None:
    """Return one explicit claimed debt amount, never a merely contractual price."""
    candidates: list[int] = []
    for segment in re.split(r"(?<=[.!?])\s+|\n+", str(case_context or "")):
        text = " ".join(segment.split()).strip()
        if not text or not _EXPLICIT_DEBT_RE.search(text):
            continue
        # A clause that says only "contract price" is not proof of outstanding
        # debt.  If the same clause explicitly says задолженность/долг, the debt
        # cue wins and the amount is eligible.
        if _NON_DEBT_PRICE_RE.search(text) and not re.search(r"(?i)(?:задолженн|основн\w*\s+долг|сумм\w*\s+долг|берешек)", text):
            continue
        values = parse_all_amounts_kzt(text)
        if len(set(values)) == 1 and values[0] > 0:
            candidates.append(values[0])
    unique = list(dict.fromkeys(candidates))
    return unique[0] if len(unique) == 1 else None


def _source_demands_principal(case_context: str) -> bool:
    text = str(case_context or "")
    if not _RECOVERY_RE.search(text):
        return False
    return bool(_EXPLICIT_DEBT_RE.search(text) or _PRINCIPAL_RE.search(text))


def _seed_principal_from_source(case_context: str, draft: ClaimDraft) -> tuple[bool, int | None]:
    """Restore money that was dropped before the ledger, without inventing relief."""
    existing = build_claim_money_ledger(list(draft.requests or []))
    if any(item.kind == "principal" and item.amount > 0 for item in existing.components):
        principal = next(item.amount for item in existing.components if item.kind == "principal" and item.amount > 0)
        return False, principal
    if not _source_demands_principal(case_context):
        return False, None
    amount = _source_principal_amount(case_context)
    if amount is None:
        return False, None

    candidates = [
        index for index, request in enumerate(draft.requests or [])
        if _principal_request_without_amount(str(request))
    ]
    if len(candidates) == 1:
        draft.requests[candidates[0]] = _append_amount(str(draft.requests[candidates[0]]), amount)
    elif not candidates:
        draft.requests.append(
            f"Взыскать с ответчика в пользу истца основной долг в размере {format_kzt(amount)}."
        )
    else:
        return False, None
    LOGGER.warning(
        "CLAIM_MONEY_AUTHORITY source_seed principal=%s reason=explicit_debt_dropped_before_ledger",
        amount,
    )
    return True, amount


def _seed_contractual_penalty_from_source(case_context: str, draft: ClaimDraft) -> tuple[bool, object | None]:
    """Use the existing deterministic cap-aware calculator after principal seed."""
    prayer = "\n".join(str(x) for x in draft.requests or [])
    if _PENALTY_RE.search(prayer):
        return False, None
    try:
        from korgan import universal_word_quality_guard as guard
        from korgan.universal_word_final_hardening import (
            _append_contractual_penalty_calculation,
            calculated_contractual_penalty_from_source,
        )
        if not guard._source_penalty_demand_segments(case_context):
            return False, None
        result = calculated_contractual_penalty_from_source(case_context, draft)
        if result is None:
            return False, None
        draft.requests.append(guard._render_penalty_request(result.amount, "ru"))
        _append_contractual_penalty_calculation(draft, result, "ru")
        LOGGER.warning(
            "CLAIM_MONEY_AUTHORITY source_seed penalty=%s days=%s capped=%s cap_amount=%s cap_reached_on=%s",
            result.amount,
            result.days,
            result.capped,
            result.cap_amount,
            result.cap_reached_on.isoformat() if result.cap_reached_on else None,
        )
        return True, result
    except Exception:
        LOGGER.exception("CLAIM_MONEY_AUTHORITY source penalty calculation failed closed")
        return False, None


def seed_claim_money_from_source(case_context: str, draft: ClaimDraft) -> bool:
    """Goal-v2 I5: explicit monetary input must reach the ledger."""
    monetary_input = bool(parse_all_amounts_kzt(str(case_context or "")))
    principal_changed, principal = _seed_principal_from_source(case_context, draft)
    penalty_changed, penalty = _seed_contractual_penalty_from_source(case_context, draft)
    ledger = build_claim_money_ledger(list(draft.requests or []))
    LOGGER.info(
        "PIPELINE_INVARIANT I5 monetary_input=%s source_principal=%s ledger_total=%s unresolved=%s result=%s",
        monetary_input,
        principal,
        ledger.total,
        len(ledger.unresolved_requests),
        "PASS" if (not monetary_input or ledger.total > 0) else "FAIL",
    )
    if penalty is not None and getattr(penalty, "cap_reached_on", None) is not None:
        LOGGER.info(
            "PIPELINE_INVARIANT I5 penalty_cap amount=%s reached_on=%s",
            getattr(penalty, "amount", None),
            penalty.cap_reached_on.isoformat(),
        )
    return principal_changed or penalty_changed


def _safe_price_fallback(case_context: str, draft: ClaimDraft) -> tuple[int, int] | None:
    """Return (request_index, amount) only for a source-grounded dropped amount."""
    amount = parse_amount_kzt(str(draft.price_of_claim or ""))
    if amount is None or amount <= 0:
        return None
    if amount not in _source_amounts(case_context, draft):
        return None

    candidates = [
        index
        for index, request in enumerate(draft.requests or [])
        if _principal_request_without_amount(str(request))
    ]
    if len(candidates) != 1:
        return None
    return candidates[0], amount


def reconcile_claim_money(case_context: str, draft: ClaimDraft) -> ClaimMoneyAuthorityResult:
    """Make the final prayer ledger the single source of truth for claim price."""
    source_repaired = seed_claim_money_from_source(case_context, draft)
    ledger = build_claim_money_ledger(list(draft.requests or []))

    if ledger.unresolved_requests:
        draft.price_of_claim = CLAIM_PRICE_NEEDS_CALCULATION
        return ClaimMoneyAuthorityResult(
            ledger=ledger,
            price=None,
            repaired_request=source_repaired,
            needs_review=True,
            reason="неоднозначное денежное требование в ПРОШУ СУД",
        )

    if ledger.total > 0:
        draft.price_of_claim = format_kzt(ledger.total)
        return ClaimMoneyAuthorityResult(ledger=ledger, price=ledger.total, repaired_request=source_repaired)

    if ledger.nonproperty_money_components:
        draft.price_of_claim = NONPROPERTY_PRICE_LABEL
        return ClaimMoneyAuthorityResult(ledger=ledger, price=None, repaired_request=source_repaired)

    fallback = _safe_price_fallback(case_context, draft)
    if fallback is not None:
        index, amount = fallback
        draft.requests[index] = _append_amount(str(draft.requests[index]), amount)
        repaired = build_claim_money_ledger(list(draft.requests or []))
        if not repaired.unresolved_requests and repaired.total == amount:
            draft.price_of_claim = format_kzt(amount)
            LOGGER.info(
                "CLAIM_MONEY_AUTHORITY restored_dropped_principal_amount amount=%s request_index=%s",
                amount,
                index,
            )
            return ClaimMoneyAuthorityResult(
                ledger=repaired,
                price=amount,
                repaired_request=True,
            )

    if parse_amount_kzt(str(draft.price_of_claim or "")) is not None:
        draft.price_of_claim = CLAIM_PRICE_NEEDS_CALCULATION
        return ClaimMoneyAuthorityResult(
            ledger=ledger,
            price=None,
            repaired_request=source_repaired,
            needs_review=True,
            reason="цена иска не подтверждена денежным требованием в ПРОШУ СУД",
        )

    return ClaimMoneyAuthorityResult(ledger=ledger, price=None, repaired_request=source_repaired)


_INSTALLED = False


def install_claim_money_authority() -> None:
    """Install reconciliation immediately before every professional duty route."""
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import claim_state_duty

    current = claim_state_duty.decide_state_duty
    if getattr(current, "_korgan_claim_money_authority", False):
        _INSTALLED = True
        return

    def decide_with_authority(case_context, research, draft):
        result = reconcile_claim_money(case_context, draft)
        LOGGER.info(
            "CLAIM_MONEY_AUTHORITY price=%s repaired=%s review=%s ledger_total=%s unresolved=%s",
            result.price,
            result.repaired_request,
            result.needs_review,
            result.ledger.total,
            len(result.ledger.unresolved_requests),
        )
        return current(case_context, research, draft)

    decide_with_authority._korgan_claim_money_authority = True  # type: ignore[attr-defined]
    claim_state_duty.decide_state_duty = decide_with_authority
    _INSTALLED = True
