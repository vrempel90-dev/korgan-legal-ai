from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from korgan.legal_types import ClaimDraft, VerificationStatus

LOGGER = logging.getLogger(__name__)
_INSTALLED = False

_MONEY_TOKEN = r"\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:тенге|теңге|тг\b|₸|kzt)"
_DUTY_LINE_RE = re.compile(
    rf"(?im)^(?:Рассчитанная\s+госпошлина\s+для\s+иска|"
    rf"Талап\s+үшін\s+есептелген\s+мемлекеттік\s+баж):\s*(?P<amount>{_MONEY_TOKEN})\s*\.?$"
)
_PENALTY_LINE_RE = re.compile(
    rf"(?im)^(?P<line>(?:Рассчитанная\s+неустойка\s+по\s+статье\s+353\s+ГК\s+РК|"
    rf"ҚР\s+АК\s+353-бабы\s+бойынша\s+есептелген\s+тұрақсыздық\s+айыбы):\s*"
    rf"(?P<amount>{_MONEY_TOKEN})[^\n]*)$"
)
_STATE_DUTY_RE = re.compile(
    r"(?i)(?:\bгоспошлин\w*\b|\bгосударственн\w*\s+пошлин\w*\b|мемлекеттік\s+баж)"
)
_PENALTY_RE = re.compile(
    r"(?i)(?:неустойк\w*|пен[яию]\b|штраф\w*|тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*|"
    r"(?:ст\.?|стать\w*)\s*353\b)"
)
_NON_PENALTY_MONEY_RE = re.compile(
    r"(?i)(?:основн\w*\s+долг\w*|задолженн\w*|берешек\w*|қарыз\w*|"
    r"убытк\w*|ущерб\w*|залал\w*|моральн\w*\s+вред\w*|моральдық\s+зиян\w*|"
    r"возврат\w*|вернут\w*|қайтар\w*)"
)
_AUTO_CALC_NOTE_RE = re.compile(
    r"(?i)(?:расч[её]т\w*\s+(?:госпошлин|неустойк)|госпошлин\w*\s+требует\s+расч|"
    r"базов\w*\s+ставк\w*.*неустойк|неустойк\w*.*не\s+рассчит)"
)


@dataclass(frozen=True, slots=True)
class ManualPenalty:
    amount: str
    line: str


def _amount_key(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def calculator_state_duty(case_context: str) -> str | None:
    """Return only a state-duty amount explicitly inserted by the Mini App calculator."""
    match = _DUTY_LINE_RE.search(case_context or "")
    return " ".join(match.group("amount").split()) if match else None


def calculator_penalty(case_context: str) -> ManualPenalty | None:
    """Return only the exact Article 353 result inserted by the calculator button."""
    match = _PENALTY_LINE_RE.search(case_context or "")
    if not match:
        return None
    return ManualPenalty(
        amount=" ".join(match.group("amount").split()),
        line=" ".join(match.group("line").split()),
    )


def _is_manual_penalty_requested(case_context: str) -> bool:
    return calculator_penalty(case_context) is not None


def _duty_request(amount: str, language: str) -> str:
    if language == "kk":
        return f"Жауапкерден талап қоюшының пайдасына мемлекеттік баж бойынша {amount} мөлшеріндегі шығыстарды өндіріп алу."
    return f"Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины в размере {amount}."


def _penalty_request(amount: str, language: str) -> str:
    if language == "kk":
        return f"Жауапкерден талап қоюшының пайдасына ҚР АК 353-бабы бойынша тұрақсыздық айыбын {amount} мөлшерінде өндіріп алу."
    return f"Взыскать с ответчика в пользу истца неустойку по статье 353 ГК РК в размере {amount}."


def _strip_state_duty_requests(draft: ClaimDraft) -> None:
    draft.requests = [item for item in draft.requests if not _STATE_DUTY_RE.search(str(item))]


def _strip_or_validate_penalty_requests(
    draft: ClaimDraft,
    manual: ManualPenalty | None,
) -> bool:
    """Remove model/legacy penalty amounts while preserving a grounded combined request.

    If a request combines another monetary remedy with the penalty, it is kept only
    when it already contains the exact calculator amount. This prevents a legacy
    calculated number from surviving in a mixed prayer line. An unsafe mixed line is
    dropped and the draft is marked for review rather than publishing contradictory
    arithmetic.
    """
    expected = _amount_key(manual.amount) if manual else ""
    cleaned: list[str] = []
    grounded_combined = False
    unsafe_combined = False

    for raw in list(draft.requests or []):
        request = str(raw)
        if not _PENALTY_RE.search(request):
            cleaned.append(request)
            continue

        combined = bool(_NON_PENALTY_MONEY_RE.search(request))
        if combined and manual is not None and expected and expected in _amount_key(request):
            cleaned.append(request)
            grounded_combined = True
            continue
        if combined:
            unsafe_combined = True
        # Penalty-only lines are always rebuilt from the calculator value below.

    draft.requests = cleaned
    if unsafe_combined:
        note = (
            "Комбинированное денежное требование содержало неустойку, не совпадающую с результатом "
            "калькулятора, поэтому оно исключено из просительной части и требует проверки юристом."
        )
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)
        draft.status = VerificationStatus.NEEDS_VERIFICATION
    return grounded_combined


def apply_manual_state_duty(
    case_context: str,
    draft: ClaimDraft,
    language: str = "ru",
) -> None:
    """State duty comes exclusively from «Добавить в иск», never from claim inference."""
    amount = calculator_state_duty(case_context)
    _strip_state_duty_requests(draft)
    draft.state_duty = amount or ""

    if amount:
        draft.requests.append(_duty_request(amount, language))
        draft.verification_notes = [
            note for note in draft.verification_notes if not _AUTO_CALC_NOTE_RE.search(str(note))
        ]


def apply_manual_penalty(
    case_context: str,
    research: Any,
    draft: ClaimDraft,
    *,
    filing_date: Any = None,
    language: str = "ru",
) -> None:
    """Penalty arithmetic comes exclusively from the Mini App calculator result."""
    del research, filing_date
    manual = calculator_penalty(case_context)
    grounded_combined = _strip_or_validate_penalty_requests(draft, manual)

    draft.late_interest = ""
    draft.calculation = [
        str(line) for line in list(draft.calculation or [])
        if not (_PENALTY_RE.search(str(line)) or _STATE_DUTY_RE.search(str(line)))
    ]

    if manual is None:
        return

    draft.late_interest = manual.line
    if not grounded_combined:
        draft.requests.append(_penalty_request(manual.amount, language))
    draft.verification_notes = [
        note for note in draft.verification_notes if not _AUTO_CALC_NOTE_RE.search(str(note))
    ]


def finalize_manual_claim_calculations(
    case_context: str,
    draft: ClaimDraft,
    *,
    language: str = "ru",
) -> None:
    """Final fail-safe: no legacy/model calculation can survive Word release."""
    from korgan import universal_word_quality_guard as guard
    from korgan.professional_claim_finalizer import _recalculate_price

    guard.sanitize_draft_instructions(draft)
    apply_manual_penalty(case_context, None, draft, language=language)
    _recalculate_price(draft)
    apply_manual_state_duty(case_context, draft, language=language)
    guard._strip_internal_score_notes(draft)


def _complete_manual_penalty(
    case_context: str,
    draft: ClaimDraft,
    *,
    language: str = "ru",
) -> bool:
    before = tuple(draft.requests)
    apply_manual_penalty(case_context, None, draft, language=language)
    return tuple(draft.requests) != before


def install_manual_claim_calculation_policy() -> None:
    """Make the claim-form calculator the sole authority for duty/penalty amounts.

    The legal-workspace endpoints themselves are intentionally untouched; they remain
    the calculator behind the Mini App button. Only automatic inference/recalculation
    inside the document pipeline is disabled.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import fast_v2_production_legal as fast_v2
    from korgan import late_interest_hotfix as late
    from korgan import production_legal
    from korgan import universal_word_quality_guard as guard

    # Stop the legacy state-duty calculators at their common production call sites.
    production_legal._apply_state_duty = apply_manual_state_duty
    fast_v2._apply_state_duty = apply_manual_state_duty
    guard.apply_state_duty_from_draft = apply_manual_state_duty

    # A mention such as «рассчитать неустойку» no longer starts automatic Article
    # 353 calculation/research. Only the exact line inserted by the calculator is
    # treated as a calculated penalty, and its amount is copied without recomputing.
    late._explicit_penalty_requested = _is_manual_penalty_requested
    late._apply_verified_penalty = apply_manual_penalty
    late._apply_verified_article_353 = apply_manual_penalty

    # Universal release runs after all older hotfix layers, so this is the final
    # invariant immediately before quality assessment/Word rendering.
    guard.complete_claim_relief_from_materials = _complete_manual_penalty
    guard.finalize_claim_for_release = finalize_manual_claim_calculations

    _INSTALLED = True
    LOGGER.info(
        "Installed manual claim calculation policy: Mini App calculator is sole source for state duty and penalty amounts"
    )
