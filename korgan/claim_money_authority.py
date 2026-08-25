"""Single deterministic money authority for civil claims.

The model may draft prose, but it must never be the final owner of claim price.
This module reconciles the court prayer into one monetary ledger and repairs only
one safe regression: a repair step dropped the amount from a single recovery
request while the same price is still source-grounded in the user's materials.

No legal tariff is chosen here.  State-duty routing remains in claim_state_duty;
this layer only guarantees that every downstream calculator sees one canonical
claim price derived from the final prayer or a narrowly source-grounded repair.
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


def _safe_price_fallback(case_context: str, draft: ClaimDraft) -> tuple[int, int] | None:
    """Return (request_index, amount) only for a source-grounded dropped amount.

    This does NOT infer a claim price from arbitrary case numbers.  It requires:
    - exactly one principal recovery request lost its amount;
    - draft.price_of_claim still contains one concrete amount;
    - the exact same amount exists in the user's case materials/facts.
    """
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
    """Make the final prayer ledger the single source of truth for claim price.

    Existing monetary prayer lines always win.  A stale/model-written
    ``price_of_claim`` can never override them.  The only fallback repairs a
    single amount that disappeared from a principal recovery request and is
    independently present in the user's materials.
    """
    ledger = build_claim_money_ledger(list(draft.requests or []))

    if ledger.unresolved_requests:
        draft.price_of_claim = CLAIM_PRICE_NEEDS_CALCULATION
        return ClaimMoneyAuthorityResult(
            ledger=ledger,
            price=None,
            needs_review=True,
            reason="неоднозначное денежное требование в ПРОШУ СУД",
        )

    if ledger.total > 0:
        draft.price_of_claim = format_kzt(ledger.total)
        return ClaimMoneyAuthorityResult(ledger=ledger, price=ledger.total)

    if ledger.nonproperty_money_components:
        draft.price_of_claim = NONPROPERTY_PRICE_LABEL
        return ClaimMoneyAuthorityResult(ledger=ledger, price=None)

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

    # Never leave an orphaned model price when the court prayer contains no
    # deterministically classifiable property amount.  That orphan caused the
    # month-long `price=...` / `STATE_DUTY_FINAL mode=unclassified` split.
    if parse_amount_kzt(str(draft.price_of_claim or "")) is not None:
        draft.price_of_claim = CLAIM_PRICE_NEEDS_CALCULATION
        return ClaimMoneyAuthorityResult(
            ledger=ledger,
            price=None,
            needs_review=True,
            reason="цена иска не подтверждена денежным требованием в ПРОШУ СУД",
        )

    return ClaimMoneyAuthorityResult(ledger=ledger, price=None)


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
