from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from korgan.document_sanitization import sanitize_document_draft
from korgan.legal_types import ClaimDraft, LegalResearch

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
_DATE_TOKEN = r"\d{1,2}[./-]\d{1,2}[./-]\d{4}"
_DATE_RANGE_RE = re.compile(
    rf"(?is)\bс\s+(?P<start>{_DATE_TOKEN})\s+по\s+(?P<end>{_DATE_TOKEN})(?:\s+включительно)?"
)
_DELAY_START_RE = re.compile(
    rf"(?is)(?:просроч\w*\s+(?:начал\w*|начина\w*)\s*(?:с\s*)?|дата\s+начала\s+просроч\w*\s*[:\-]?\s*)"
    rf"(?P<start>{_DATE_TOKEN})"
)
_AS_OF_RE = re.compile(
    rf"(?is)(?:по\s+состоянию\s+на|рассчит\w*\s+(?:по|на)\s+дат\w*|на\s+дату)\s*(?P<end>{_DATE_TOKEN})"
)


def parse_money_exact(raw: str) -> int:
    """Parse a KZT amount without binary-float precision loss."""
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
    values = amount_occurrences_exact(text)
    return values[0][0] if values else None


def calc_state_duty_exact(amount: int, is_individual: bool) -> int:
    """Calculate ordinary civil property-claim state duty with the correct party cap."""
    from korgan import legal_calc

    if amount < 0:
        raise ValueError("Сумма иска не может быть отрицательной")

    if is_individual:
        rate = Decimal(str(legal_calc.RATE_INDIVIDUAL))
        cap_mrp = legal_calc.CAP_MRP_INDIVIDUAL
    else:
        rate = Decimal(str(legal_calc.RATE_LEGAL_ENTITY))
        cap_mrp = legal_calc.CAP_MRP_LEGAL_ENTITY

    duty = int((Decimal(amount) * rate).quantize(_ONE_TENGE, rounding=ROUND_HALF_UP))
    statutory_cap = int(Decimal(cap_mrp) * Decimal(legal_calc.MRP_2026))
    return min(duty, statutory_cap)


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
    """Return an explicitly source-grounded penalty amount that is not principal debt."""
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
        candidates.append((score, explicit, -distance, amount))

    if not candidates:
        return None
    score, _explicit, _distance, amount = max(candidates, key=lambda item: item[:3])
    return amount if score > 0 else None


def _parse_date_token(value: str) -> date | None:
    raw = str(value or "").strip().replace("/", ".").replace("-", ".")
    try:
        return datetime.strptime(raw, "%d.%m.%Y").date()
    except ValueError:
        return None


def contractual_penalty_period_from_source(case_context: str) -> tuple[date, date] | None:
    """Read only an explicit delay/penalty period; never infer dates from unrelated events."""
    text = case_context or ""
    for match in _DATE_RANGE_RE.finditer(text):
        around = text[max(0, match.start() - 180): min(len(text), match.end() + 80)].casefold()
        if not any(token in around for token in ("просроч", "неустой", "пен", "тұрақсыз", "өсімпұл")):
            continue
        start = _parse_date_token(match.group("start"))
        end = _parse_date_token(match.group("end"))
        if start and end and end >= start:
            return start, end

    start_match = _DELAY_START_RE.search(text)
    if not start_match:
        return None
    start = _parse_date_token(start_match.group("start"))
    if start is None:
        return None
    end_match = _AS_OF_RE.search(text, pos=start_match.end())
    if not end_match:
        return None
    end = _parse_date_token(end_match.group("end"))
    if end is None or end < start:
        return None
    return start, end


def _principal_from_prayer(draft: ClaimDraft) -> int | None:
    from korgan.claim_money_ledger import build_claim_money_ledger

    ledger = build_claim_money_ledger(list(draft.requests or []))
    if ledger.unresolved_requests:
        return None
    principal = [item.amount for item in ledger.components if item.kind == "principal"]
    if len(principal) == 1 and principal[0] > 0:
        return principal[0]
    if len(ledger.components) == 1 and ledger.components[0].amount > 0:
        return ledger.components[0].amount
    return None


def calculated_contractual_penalty_from_source(case_context: str, draft: ClaimDraft):
    """Calculate a demanded contractual penalty only when rate, principal and dates are unambiguous."""
    from korgan import universal_word_quality_guard as guard
    from korgan.contractual_penalty import calc_contractual_penalty, parse_contractual_penalty_terms

    if not guard._source_penalty_demand_segments(case_context):
        return None
    principal = _principal_from_prayer(draft)
    period = contractual_penalty_period_from_source(case_context)
    terms = parse_contractual_penalty_terms(case_context)
    if principal is None or period is None or terms is None:
        return None
    start, end = period
    return calc_contractual_penalty(principal, start, end, terms)


def _append_contractual_penalty_calculation(draft: ClaimDraft, result, language: str) -> None:
    from korgan.legal_calc import format_kzt

    principal = format_kzt(result.principal)
    amount = format_kzt(result.amount)
    if language == "kk":
        principal = principal.replace(" тенге", " теңге")
        amount = amount.replace(" тенге", " теңге")
        line = (
            f"Шарттық тұрақсыздық айыбын есептеу: {principal} × {result.rate_percent:g}% × "
            f"{result.days} күн = {amount}."
        )
    else:
        line = (
            f"Расчёт договорной неустойки: {principal} × {result.rate_percent:g}% × "
            f"{result.days} календарных дней = {amount}."
        )
    if result.cap_amount is not None:
        cap = format_kzt(result.cap_amount)
        if language == "kk":
            cap = cap.replace(" тенге", " теңге")
        line += f" Договорный предел {result.cap_percent:g}% составляет {cap}; к взысканию — {amount}."
    if not any("неустойк" in str(item).casefold() and str(result.amount) in re.sub(r"\D", "", str(item)) for item in draft.facts):
        draft.facts.append(line)


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
    result = None
    if amount is None:
        result = calculated_contractual_penalty_from_source(case_context, draft)
        amount = result.amount if result is not None else None
    if amount is None:
        return False

    draft.requests.append(guard._render_penalty_request(amount, language))
    if result is not None:
        _append_contractual_penalty_calculation(draft, result, language)
    LOGGER.info(
        "UNIVERSAL_WORD_MONEY restored_contractual_penalty amount=%s deterministic=%s language=%s",
        amount,
        result is not None,
        language,
    )
    return True


def install_universal_word_final_hardening() -> None:
    """Make filing arithmetic exact and make professional state duty the final owner."""
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import legal_calc
    from korgan import professional_claim_finalizer as finalizer
    from korgan import universal_word_quality_guard as guard
    from korgan.claim_state_duty import apply_professional_state_duty
    from korgan.stable_legal_release import StableLegalProductionService

    guard._MONEY_RE = _MONEY_RE
    guard._parse_money = parse_money_exact
    guard._amount_occurrences = amount_occurrences_exact
    guard._penalty_amount = penalty_amount_from_source
    guard.complete_claim_relief_from_materials = complete_claim_relief_from_materials_exact

    # Keep all existing quality flows, but make their final client-facing cleanup
    # remove renderer-owned labels and official-site editorial metadata.
    current_sanitizer = guard.sanitize_draft_instructions

    def professional_document_sanitizer(draft) -> None:
        current_sanitizer(draft)
        sanitize_document_draft(draft)

    guard.sanitize_draft_instructions = professional_document_sanitizer

    finalizer._MONEY_RE = _MONEY_RE
    finalizer._parse_amount = parse_money_exact

    legal_calc.parse_amount_kzt = parse_amount_kzt_exact
    legal_calc.calc_gosposhlina_claim = calc_state_duty_exact
    legal_calc.calc_late_payment_penalty = calc_late_payment_penalty_exact

    legacy_guard_duty = guard.apply_state_duty_from_draft

    def defer_guard_state_duty(
        case_context: str,
        draft: ClaimDraft,
        language: str = "ru",
    ) -> None:
        current = str(draft.state_duty or "").strip()
        if current and not current.startswith("["):
            guard._localize_state_duty_request(draft, language)
            return
        legacy_guard_duty(case_context, draft, language=language)

    guard.apply_state_duty_from_draft = defer_guard_state_duty

    current_claim = StableLegalProductionService.draft_claim

    async def claim_with_final_state_duty(
        self: StableLegalProductionService,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await current_claim(self, case_context, research, language=language)
        sanitize_document_draft(draft)

        restored = complete_claim_relief_from_materials_exact(
            case_context,
            draft,
            language=language,
        )
        if restored:
            finalizer._recalculate_price(draft)

        decision = apply_professional_state_duty(case_context, research, draft)
        LOGGER.info(
            "STATE_DUTY_RELEASE_FINAL mode=%s amount=%s deferred=%s exempt=%s needs_review=%s price=%r restored_penalty=%s",
            decision.mode,
            decision.amount,
            decision.deferred,
            decision.exempt,
            decision.needs_review,
            draft.price_of_claim,
            restored,
        )
        return draft

    StableLegalProductionService.draft_claim = claim_with_final_state_duty  # type: ignore[assignment]

    _INSTALLED = True
    LOGGER.info(
        "Installed universal Word final hardening: client document sanitation + Decimal KZT arithmetic + separate state-duty caps + deterministic contractual penalty + canonical final duty owner + exact Article 353"
    )
