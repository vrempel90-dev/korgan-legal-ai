from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date

from korgan.legal_types import ClaimDraft

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_ONE_TENGE = Decimal("1")
_ONE_HUNDRED = Decimal("100")

_MONEY_RE = re.compile(
    r"(?<!\d)(\d[\d\s\u00a0]*(?:[.,]\d{1,2})?)\s*(?:тенге|теңге|тг\b|₸)",
    re.IGNORECASE,
)
_PRINCIPAL_AMOUNT_CONTEXT_RE = re.compile(
    r"(?i)(?:сумм\w*\s+(?:основн\w*\s+)?долг\w*|основн\w*\s+долг\w*|"
    r"негізгі\s+борыш\w*|борыш\w*\s+сомас\w*)"
)


def parse_money_exact(raw: str) -> int:
    """Parse a KZT amount without binary-float precision loss.

    Filing calculations round fractional tenge to the nearest whole tenge with
    ROUND_HALF_UP. Integer values, including values above 2**53, remain exact.
    """
    value = re.sub(r"[\s\u00a0]", "", str(raw or "")).replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", value):
        return 0
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return 0
    if not amount.is_finite() or amount < 0:
        return 0
    return int(amount.quantize(_ONE_TENGE, rounding=ROUND_HALF_UP))


def amount_occurrences_exact(text: str) -> list[tuple[int, int, int]]:
    result: list[tuple[int, int, int]] = []
    for match in _MONEY_RE.finditer(text or ""):
        amount = parse_money_exact(match.group(1))
        if amount > 0:
            result.append((amount, match.start(), match.end()))
    return result


def parse_amount_kzt_exact(text: str) -> int | None:
    """Parse the first KZT amount exactly, supporting both RU and KK currency forms."""
    values = amount_occurrences_exact(text)
    return values[0][0] if values else None


def calc_state_duty_exact(amount: int, is_individual: bool) -> int:
    """Calculate court state duty using Decimal and the configured statutory cap."""
    from korgan import legal_calc

    if amount < 0:
        raise ValueError("Сумма иска не может быть отрицательной")
    rate = Decimal("0.01") if is_individual else Decimal("0.03")
    duty = int((Decimal(amount) * rate).quantize(_ONE_TENGE, rounding=ROUND_HALF_UP))
    return min(duty, legal_calc.CAP_MRP * legal_calc.MRP_2026)


def calc_late_payment_penalty_exact(
    principal: int,
    start: date,
    end: date,
    *,
    rate_date: date,
):
    """Calculate Article 353 amount without float multiplication drift."""
    from korgan import legal_calc

    if principal <= 0:
        raise ValueError("Сумма основного долга должна быть положительной")
    if end < start:
        raise ValueError("Дата окончания периода просрочки раньше её начала")
    rate = legal_calc.base_rate_on(rate_date)
    if rate is None:
        return None
    days = (end - start).days + 1
    amount = int(
        (
            Decimal(principal)
            * Decimal(str(rate))
            / _ONE_HUNDRED
            * Decimal(days)
            / Decimal(legal_calc.DAYS_IN_YEAR)
        ).quantize(_ONE_TENGE, rounding=ROUND_HALF_UP)
    )
    return legal_calc.LatePaymentPenalty(
        principal,
        start,
        end,
        rate_date,
        days,
        rate,
        amount,
    )


def _already_claimed_amounts(draft: ClaimDraft) -> set[int]:
    amounts: set[int] = set()
    for text in [draft.price_of_claim, *draft.requests]:
        for amount, _start, _end in amount_occurrences_exact(str(text)):
            amounts.add(amount)
    return amounts


def penalty_amount_from_source(case_context: str, draft: ClaimDraft) -> int | None:
    """Return only a source-grounded penalty amount that is not principal debt.

    The source must explicitly demand a penalty. Amounts already present in the
    claim price or prayer are excluded, and only the amount nearest to a penalty
    term within each source segment is eligible. If that nearest amount is
    labelled as principal debt, the segment is rejected instead of guessing.
    """
    from korgan import universal_word_quality_guard as guard

    explicit_segments = guard._source_penalty_demand_segments(case_context)
    if not explicit_segments:
        return None

    already_claimed = _already_claimed_amounts(draft)
    segments = [
        segment.strip()
        for segment in re.split(r"(?<=[.!?])\s+|\n+", case_context or "")
        if segment.strip()
    ]
    candidates: list[tuple[int, int, int, int]] = []

    for segment in segments:
        terms = list(guard._PENALTY_RE.finditer(segment))
        if not terms:
            continue
        eligible = [
            (amount, start, end)
            for amount, start, end in amount_occurrences_exact(segment)
            if amount not in already_claimed
        ]
        if not eligible:
            continue

        nearest = min(
            (
                (min(abs(start - term.start()) for term in terms), start, amount, end)
                for amount, start, end in eligible
            ),
            key=lambda item: (item[0], item[1]),
        )
        distance, start, amount, _end = nearest
        # Bind a principal-debt label only to the amount immediately following
        # it. A wider window would wrongly reject the later phrase
        # «...долг 12 000 000 и неустойка составила 996 000».
        local_prefix = segment[max(0, start - 30):start]
        if _PRINCIPAL_AMOUNT_CONTEXT_RE.search(local_prefix):
            LOGGER.warning(
                "UNIVERSAL_WORD_MONEY ambiguous_penalty_segment rejected amount=%s segment=%r",
                amount,
                segment[:240],
            )
            continue

        score = max(0, 8 - distance // 20)
        explicit = int(segment in explicit_segments)
        if explicit:
            score += 8
        if guard._PENALTY_AMOUNT_SIGNAL_RE.search(segment):
            score += 4
        if "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА:" in segment:
            score += 7
        if guard._PENALTY_CAP_RE.search(segment):
            score -= 12

        # Higher score wins; explicit source demand wins ties; then the nearest
        # textual amount wins. Amount magnitude is deliberately not a tie-breaker.
        candidates.append((score, explicit, -distance, amount))

    if not candidates:
        return None
    score, _explicit, _distance, amount = max(candidates, key=lambda item: item[:3])
    return amount if score > 0 else None


def complete_claim_relief_from_materials_exact(
    case_context: str,
    draft: ClaimDraft,
    *,
    language: str = "ru",
) -> bool:
    from korgan import universal_word_quality_guard as guard

    if not guard._penalty_should_be_in_prayer(case_context, draft):
        return False
    amount = penalty_amount_from_source(case_context, draft)
    if amount is None:
        return False
    draft.requests.append(guard._render_penalty_request(amount, language))
    LOGGER.info(
        "UNIVERSAL_WORD_MONEY restored_penalty_exact amount=%s language=%s",
        amount,
        language,
    )
    return True


def install_universal_word_final_hardening() -> None:
    """Make filing arithmetic exact and penalty restoration source-safe."""
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import legal_calc
    from korgan import professional_claim_finalizer as finalizer
    from korgan import universal_word_quality_guard as guard

    # These functions are resolved through module globals at runtime, so the
    # replacement protects every existing claim finalization path without adding
    # another model call or changing Word delivery behavior.
    guard._MONEY_RE = _MONEY_RE
    guard._parse_money = parse_money_exact
    guard._amount_occurrences = amount_occurrences_exact
    guard._penalty_amount = penalty_amount_from_source
    guard.complete_claim_relief_from_materials = complete_claim_relief_from_materials_exact

    finalizer._MONEY_RE = _MONEY_RE
    finalizer._parse_amount = parse_money_exact

    # legal_calc.gosposhlina_line resolves these names dynamically inside its
    # module, so replacing them also hardens the already-imported release helper.
    legal_calc.parse_amount_kzt = parse_amount_kzt_exact
    legal_calc.calc_gosposhlina_claim = calc_state_duty_exact
    legal_calc.calc_late_payment_penalty = calc_late_payment_penalty_exact

    _INSTALLED = True
    LOGGER.info(
        "Installed universal Word final hardening: Decimal KZT arithmetic + exact state duty/Article 353 + source-safe penalty extraction"
    )
