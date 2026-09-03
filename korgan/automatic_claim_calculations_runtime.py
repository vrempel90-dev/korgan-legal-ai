from __future__ import annotations

"""Automatic monetary calculations for production claims.

The client describes the facts. KORGAN decides whether a civil/commercial money
claim appears overdue, verifies the legal basis in the *existing* source-bound
research pass, then lets deterministic calculators own the numbers.

A calculation uncertainty never blocks the whole Word document. The uncertain
penalty is excluded from the claim price and prayer, while the document contains
an explicit human-readable clarification note. State duty is then recalculated
from the monetary claims that are actually included.
"""

import re

from korgan import fast_professional_litigation as fast
from korgan import finalized_litigation as finalized
from korgan import late_interest_hotfix as late
from korgan.legal_types import ClaimDraft

_INSTALLED = False
_ORIGINAL_RESEARCH_PROMPT = fast._professional_research_prompt
_ORIGINAL_EXPLICIT = late._explicit_penalty_requested

_CIVIL_MONEY_RE = re.compile(
    r"(?i)(?:договор\w*|поставк\w*|подряд\w*|услуг\w*|аренд\w*|займ\w*|за[её]м\w*|"
    r"расписк\w*|аванс\w*|предоплат\w*|товар\w*|долг\w*|задолженн\w*|"
    r"возврат\w*\s+денег|вернут\w*\s+денег|берешек\w*|қарыз\w*|шарт\w*)"
)
_BREACH_RE = re.compile(
    r"(?i)(?:не\s+(?:вернул\w*|возвратил\w*|оплатил\w*|погасил\w*|исполнил\w*)|"
    r"не\s+возвращ\w*|не\s+оплач\w*|просроч\w*|срок\w*\s+(?:ист[её]к|наруш\w*)|"
    r"должен\w*\s+был\w*|мерзім\w*\s+өт\w*|төлем\w*\s+жасалма\w*|қайтарма\w*)"
)


def automatic_penalty_candidate(case_context: str) -> bool:
    """Whether KORGAN should assess penalty without making the client ask for it.

    Explicit requests keep their old behaviour. Automatic mode is deliberately
    limited to a fact pattern that looks like an overdue civil/commercial money
    obligation: a money amount, a civil obligation marker and a breach marker.
    The legal research still decides whether Article 353 is actually applicable.
    """
    text = str(case_context or "")
    if _ORIGINAL_EXPLICIT(text):
        return True
    if late.parse_contractual_penalty_terms(text) is not None:
        return True
    return bool(late._MONEY_TOKEN_RE.search(text) and _CIVIL_MONEY_RE.search(text) and _BREACH_RE.search(text))


def _clarification_reason(reason: str) -> str:
    value = " ".join(str(reason or "").split()).strip().rstrip(".")
    if value == late.DUE_DATE_MISSING_NOTE.rstrip(".") or value == late.CONTRACT_DUE_DATE_MISSING_NOTE.rstrip("."):
        return "не удалось однозначно установить дату начала просрочки"
    if value == late.PARTIAL_PAYMENT_UNCLEAR_NOTE.rstrip("."):
        return "упоминается частичная оплата, но её дату и сумму нельзя однозначно установить"
    if value == late.PARTIAL_PAYMENT_NOTE.rstrip("."):
        return "есть частичные оплаты, для которых требуется уточнить даты и суммы по периодам"
    if value == late.CONTRACT_TERMS_MISSING_NOTE.rstrip("."):
        return "не удалось подтвердить применимое основание и ставку неустойки"
    if value == late.ARTICLE_353_MISSING_NOTE.rstrip("."):
        return "статья 353 ГК РК не подтверждена source-bound исследованием для этого требования"
    if value.startswith(late.RATE_MISSING_NOTE.rstrip(".")):
        return value[:1].lower() + value[1:]
    return value[:1].lower() + value[1:] if value else "нужны дополнительные исходные данные для точного расчёта"


def soft_penalty_clarification(
    draft: ClaimDraft,
    reason: str,
    *,
    case_context: str,
    detail: str = "",
) -> None:
    """Do not turn one uncertain monetary component into a blocked Word file.

    The questionable penalty is removed from the prayer and deterministic total.
    The clarification remains visible in the document but is intentionally not a
    verification_note and does not change the draft's overall verification status.
    """
    draft.requests = [
        str(item) for item in list(draft.requests or [])
        if not late._PENALTY_LINE_RE.search(str(item))
    ]
    draft.legal_basis = [
        str(item) for item in list(draft.legal_basis or [])
        if not late._ARTICLE_353_LINE_RE.search(str(item))
    ]
    late._drop_penalty_calculation(draft)
    clarification = _clarification_reason(reason)
    draft.late_interest = (
        "Неустойка в цену иска и просительную часть не включена. "
        f"Требует уточнения: {clarification}."
    )
    # `detail` is deliberately not copied into filing-facing text: it can contain
    # internal comparison diagnostics. The client needs the missing fact, not QA internals.


def _research_prompt(case_context: str, *, max_chars: int, checked_on: str, **kwargs: object) -> str:
    base = _ORIGINAL_RESEARCH_PROMPT(
        case_context,
        max_chars=max_chars,
        checked_on=checked_on,
        **kwargs,
    )
    if not automatic_penalty_candidate(case_context):
        return base
    return base + (
        "\n\nАВТОМАТИЧЕСКИЙ РАСЧЁТ ДЕНЕЖНЫХ ТРЕБОВАНИЙ:\n"
        "26. Пользователь не обязан знать термин 'неустойка' и отдельно просить её. "
        "Если из материалов следует просроченное денежное обязательство, в ЭТОМ ЖЕ source-bound проходе проверь право на неустойку автоматически.\n"
        "27. Сначала проверь договор: если в материалах есть договорная пеня/неустойка, не подменяй её статьёй 353 ГК РК. "
        "Если договорной ставки нет или она неприменима, проверь, применимы ли пункты 1 и 2 статьи 353 ГК РК к установленным фактам.\n"
        "28. Не включай статью 353 только потому, что есть долг. Верни её как VERIFIED лишь когда действующая официальная норма и характер обязательства действительно позволяют этот способ взыскания.\n"
        "29. Если правовое основание есть, но для точного расчёта не хватает срока исполнения, даты частичной оплаты или другого исходного факта, отрази это как NEEDS_FACTS в remedies. Не придумывай дату или ставку.\n"
        "30. Госпошлину и арифметику не считай моделью: после drafting их вычисляет детерминированный код KORGAN."
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Both the fast service and the finalizer imported the function by value, so
    # patch all three references. The function itself resolves these module
    # globals at call time, which lets the existing well-tested calculators stay
    # authoritative instead of duplicating their formulas here.
    late._explicit_penalty_requested = automatic_penalty_candidate
    late._mark_penalty_for_verification = soft_penalty_clarification
    fast._apply_verified_article_353 = late._apply_verified_penalty
    finalized._apply_verified_article_353 = late._apply_verified_penalty
    fast._professional_research_prompt = _research_prompt
    _INSTALLED = True


install()
