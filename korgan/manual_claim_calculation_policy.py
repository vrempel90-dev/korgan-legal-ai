from __future__ import annotations

import logging
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

from korgan.legal_types import ClaimDraft, VerificationStatus

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_MANUAL_MODE: ContextVar[bool] = ContextVar("korgan_manual_claim_calculations", default=False)

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
_PENALTY_TERM = (
    r"(?:неустойк\w*|пен[яию]\b|штраф\w*|тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*|"
    r"(?:ст\.?|стать\w*)\s*353\b)"
)
_PENALTY_RE = re.compile(rf"(?i){_PENALTY_TERM}")
_NON_PENALTY_MONEY_RE = re.compile(
    r"(?i)(?:основн\w*\s+долг\w*|задолженн\w*|берешек\w*|қарыз\w*|"
    r"убытк\w*|ущерб\w*|залал\w*|моральн\w*\s+вред\w*|моральдық\s+зиян\w*|"
    r"возврат\w*|вернут\w*|қайтар\w*)"
)
_PENALTY_AMOUNT_AFTER_RE = re.compile(
    rf"(?i){_PENALTY_TERM}[^\n.;:]{{0,80}}?(?P<amount>{_MONEY_TOKEN})"
)
_PENALTY_AMOUNT_BEFORE_RE = re.compile(
    rf"(?i)(?P<amount>{_MONEY_TOKEN})\s*(?:в\s+размере\s+)?{_PENALTY_TERM}"
)
_AUTO_CALC_NOTE_RE = re.compile(
    r"(?i)(?:расч[её]т\w*\s+(?:госпошлин|неустойк)|госпошлин\w*\s+требует\s+расч|"
    r"базов\w*\s+ставк\w*.*неустойк|неустойк\w*.*не\s+рассчит)"
)
_MINIAPP_CONTEXT_MARKERS = (
    "Факты, сообщённые пользователем:\n",
    "Материалы дела:\n",
    "Дополнительные факты, сообщённые пользователем в консультации:\n",
    "ИСТОЧНИК МАТЕРИАЛА:",
)
_VERIFIED_EXEMPTION_RE = re.compile(
    r"(?i)^\s*0\s*(?:тенге|теңге|тг\b|₸|kzt)\s*\([^\n)]*освобожд[^\n)]*государственн[^\n)]*пошлин"
)
_VERIFIED_DEFERRAL_RE = re.compile(
    rf"(?i)^\s*{_MONEY_TOKEN}\s*\([^\n)]*уплата\s+отсрочена[^\n)]*\)\s*$"
)


@dataclass(frozen=True, slots=True)
class ManualPenalty:
    amount: str
    line: str


@contextmanager
def manual_claim_calculation_mode() -> Iterator[None]:
    """Explicitly enable button-only amounts for one claim-generation coroutine.

    ContextVar keeps concurrent consultations/documents isolated. Production MiniApp
    contexts are also recognized by the stable headings emitted by
    ``miniapp_api_v2._case_context`` so the policy applies to direct HTTP and
    persisted generation-job execution without changing the progress-job lifecycle.
    """
    token = _MANUAL_MODE.set(True)
    try:
        yield
    finally:
        _MANUAL_MODE.reset(token)


def _is_miniapp_claim_context(case_context: str) -> bool:
    text = str(case_context or "")
    if calculator_state_duty(text) is not None or calculator_penalty(text) is not None:
        return True
    return any(marker in text for marker in _MINIAPP_CONTEXT_MARKERS)


def manual_claim_calculation_mode_enabled(case_context: str | None = None) -> bool:
    if _MANUAL_MODE.get():
        return True
    if case_context is None:
        return False
    return _is_miniapp_claim_context(case_context)


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


def _penalty_amount_key_from_request(request: str) -> str:
    """Bind the compared amount to the penalty phrase, never to another claim sum."""
    after = _PENALTY_AMOUNT_AFTER_RE.search(request or "")
    if after:
        return _amount_key(after.group("amount"))
    before = _PENALTY_AMOUNT_BEFORE_RE.search(request or "")
    if before:
        return _amount_key(before.group("amount"))
    return ""


def _strip_or_validate_penalty_requests(
    draft: ClaimDraft,
    manual: ManualPenalty | None,
) -> bool:
    """Remove legacy/model penalty amounts while preserving an exact grounded combined line."""
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
        actual_penalty = _penalty_amount_key_from_request(request)
        if combined and manual is not None and expected and actual_penalty == expected:
            cleaned.append(request)
            grounded_combined = True
            continue
        if combined:
            unsafe_combined = True
        # Penalty-only lines are rebuilt below exclusively from the calculator value.

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


def _existing_duty_status(line: str) -> tuple[str, str]:
    """Keep only deterministic exemption/deferral semantics, not an inferred amount."""
    text = " ".join(str(line or "").split()).strip()
    if _VERIFIED_EXEMPTION_RE.search(text):
        return "exempt", text
    if _VERIFIED_DEFERRAL_RE.search(text):
        lower = text.lower()
        marker = "уплата отсрочена"
        start = lower.find(marker)
        if start >= 0:
            status = text[start:].rstrip(" )").strip()
            if status:
                return "deferred", status[0].upper() + status[1:] + ("" if status.endswith(".") else ".")
    return "", ""


def apply_manual_state_duty(
    case_context: str,
    draft: ClaimDraft,
    language: str = "ru",
) -> None:
    """State-duty money comes exclusively from «Добавить в иск».

    A verified statutory exemption or deferral is a legal status rather than an
    inferred payable amount, so that status survives. A deferral never preserves
    the previously auto-calculated number; if the client added a calculator amount,
    the amount is paired with the verified deferral status.
    """
    amount = calculator_state_duty(case_context)
    duty_status, duty_status_line = _existing_duty_status(draft.state_duty)
    _strip_state_duty_requests(draft)

    if duty_status == "exempt":
        draft.state_duty = duty_status_line
        return

    if duty_status == "deferred":
        draft.state_duty = f"{amount} ({duty_status_line})" if amount else duty_status_line
        return

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
    """Direct regression helper for the same final invariant used in MiniApp release."""
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


def _replace_loaded_aliases(original: Any, replacement: Any) -> None:
    """Replace import-by-value aliases already captured by loaded KORGAN layers."""
    for module_name, module in tuple(sys.modules.items()):
        if module is None or not module_name.startswith("korgan."):
            continue
        namespace = vars(module)
        for attribute, value in tuple(namespace.items()):
            if value is original:
                setattr(module, attribute, replacement)


def install_manual_claim_calculation_policy() -> None:
    """Make the MiniApp claim-form calculator the sole monetary authority.

    Wrappers delegate to existing deterministic calculators everywhere else.
    MiniApp v2 contexts are recognized by the stable factual/source headings produced
    by its context builder. This keeps Telegram and standalone calculator behavior
    unchanged while the MiniApp claim flow uses only «Добавить в иск» amounts.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import claim_state_duty
    from korgan import fast_v2_production_legal as fast_v2
    from korgan import late_interest_hotfix as late
    from korgan import production_legal
    from korgan import universal_word_quality_guard as guard

    original_production_duty = production_legal._apply_state_duty
    original_fast_v2_duty = fast_v2._apply_state_duty
    original_guard_duty = guard.apply_state_duty_from_draft
    original_professional_duty = claim_state_duty.apply_professional_state_duty
    original_explicit_penalty = late._explicit_penalty_requested
    original_apply_penalty = late._apply_verified_penalty
    original_apply_article_353 = late._apply_verified_article_353
    original_complete_relief = guard.complete_claim_relief_from_materials

    def production_duty(case_context: str, draft: ClaimDraft) -> None:
        if manual_claim_calculation_mode_enabled(case_context):
            apply_manual_state_duty(case_context, draft)
        else:
            original_production_duty(case_context, draft)

    def fast_v2_duty(case_context: str, draft: ClaimDraft) -> None:
        if manual_claim_calculation_mode_enabled(case_context):
            apply_manual_state_duty(case_context, draft)
        else:
            original_fast_v2_duty(case_context, draft)

    def guard_duty(case_context: str, draft: ClaimDraft, language: str = "ru") -> None:
        if manual_claim_calculation_mode_enabled(case_context):
            apply_manual_state_duty(case_context, draft, language=language)
        else:
            original_guard_duty(case_context, draft, language=language)

    def professional_duty(case_context: str, research: Any, draft: ClaimDraft) -> Any:
        if not manual_claim_calculation_mode_enabled(case_context):
            return original_professional_duty(case_context, research, draft)
        # Preserve verified exemption/deferral handling, then immediately remove
        # its inferred monetary amount and replace it only with calculator input.
        decision = original_professional_duty(case_context, research, draft)
        apply_manual_state_duty(case_context, draft)
        return decision

    def explicit_penalty(case_context: str) -> bool:
        if manual_claim_calculation_mode_enabled(case_context):
            return _is_manual_penalty_requested(case_context)
        return original_explicit_penalty(case_context)

    def apply_penalty(
        case_context: str,
        research: Any,
        draft: ClaimDraft,
        *,
        filing_date: Any = None,
    ) -> None:
        if manual_claim_calculation_mode_enabled(case_context):
            apply_manual_penalty(case_context, research, draft, filing_date=filing_date)
        else:
            original_apply_penalty(case_context, research, draft, filing_date=filing_date)

    def apply_article_353(
        case_context: str,
        research: Any,
        draft: ClaimDraft,
        *,
        filing_date: Any = None,
    ) -> None:
        if manual_claim_calculation_mode_enabled(case_context):
            apply_manual_penalty(case_context, research, draft, filing_date=filing_date)
        else:
            original_apply_article_353(case_context, research, draft, filing_date=filing_date)

    def complete_relief(
        case_context: str,
        draft: ClaimDraft,
        *,
        language: str = "ru",
    ) -> bool:
        if manual_claim_calculation_mode_enabled(case_context):
            return _complete_manual_penalty(case_context, draft, language=language)
        return original_complete_relief(case_context, draft, language=language)

    production_legal._apply_state_duty = production_duty
    fast_v2._apply_state_duty = fast_v2_duty
    guard.apply_state_duty_from_draft = guard_duty
    claim_state_duty.apply_professional_state_duty = professional_duty
    late._explicit_penalty_requested = explicit_penalty
    late._apply_verified_penalty = apply_penalty
    late._apply_verified_article_353 = apply_article_353
    guard.complete_claim_relief_from_materials = complete_relief

    # strict_bot loads several claim-service layers before this installer. Those
    # modules imported the old functions by value; replacing only the source
    # module would leave their captured aliases live. Patch only aliases whose
    # identity is exactly the function being replaced, then future imports pick
    # up the wrapper from the source module normally.
    _replace_loaded_aliases(original_production_duty, production_duty)
    _replace_loaded_aliases(original_fast_v2_duty, fast_v2_duty)
    _replace_loaded_aliases(original_guard_duty, guard_duty)
    _replace_loaded_aliases(original_professional_duty, professional_duty)
    _replace_loaded_aliases(original_explicit_penalty, explicit_penalty)
    _replace_loaded_aliases(original_apply_penalty, apply_penalty)
    _replace_loaded_aliases(original_apply_article_353, apply_article_353)
    _replace_loaded_aliases(original_complete_relief, complete_relief)

    _INSTALLED = True
    LOGGER.info(
        "Installed scoped manual claim calculation policy: MiniApp claim generation uses calculator-button amounts only"
    )
