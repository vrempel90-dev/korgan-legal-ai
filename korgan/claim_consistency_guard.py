from __future__ import annotations

import re

import korgan.senior_claim_preflight as senior_claim_preflight
from korgan.legal_types import ClaimDraft, LegalResearch

_PENALTY_TERM = r"(?:неустойк\w*|пен[яию]\b|штраф\w*)"
_COST_TERM = r"(?:судебн\w*\s+расход\w*|расход\w*\s+на\s+представител\w*|расход\w*\s+по\s+делу)"
_PENALTY_INTENT_RE = re.compile(
    rf"(?:прошу|требую|хочу|нужно|необходимо|взыска\w*)[^\n]{{0,220}}{_PENALTY_TERM}|"
    rf"взыска\w*[^\n]{{0,120}}{_PENALTY_TERM}",
    re.IGNORECASE,
)
_COST_INTENT_RE = re.compile(
    rf"(?:прошу|требую|хочу|нужно|необходимо|взыска\w*)[^\n]{{0,220}}{_COST_TERM}|"
    rf"взыска\w*[^\n]{{0,120}}{_COST_TERM}",
    re.IGNORECASE,
)
_PENALTY_REQUEST_RE = re.compile(_PENALTY_TERM, re.IGNORECASE)
_COST_REQUEST_RE = re.compile(_COST_TERM, re.IGNORECASE)
_AMOUNT_RE = re.compile(r"(?<!\d)\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:тенге|тг\b|₸)", re.IGNORECASE)

_PAID_IN_FULL_RE = re.compile(
    r"(?:оплат\w*|уплат\w*|внес\w*)[^\n]{0,90}(?:полностью|в\s+полном\s+объ[её]ме|всю\s+сумм\w*)|"
    r"(?:полностью|в\s+полном\s+объ[её]ме)[^\n]{0,70}(?:оплат\w*|уплат\w*)",
    re.IGNORECASE,
)
_COUNTERPARTY_NONPERFORMANCE_RE = re.compile(
    r"(?:ответчик|исполнитель|подрядчик|продавец|изготовитель)[^\n]{0,140}"
    r"(?:не\s+исполнил|не\s+выполнил|не\s+изготовил|не\s+установил|не\s+передал|просроч\w*)",
    re.IGNORECASE,
)
_BUYER_NONPAYMENT_BASIS_RE = re.compile(
    r"неоплат\w*\s+покупател\w*|"
    r"неисполнени\w*\s+покупател\w*[^\n]{0,140}предварительн\w*\s+оплат\w*|"
    r"покупател\w*[^\n]{0,140}не\s+исполн\w*[^\n]{0,90}предварительн\w*\s+оплат\w*",
    re.IGNORECASE,
)
_WORKS_CONTEXT_RE = re.compile(
    r"работ\w*|услуг\w*|подряд\w*|ремонт\w*|монтаж\w*|изготовлен\w*|установк\w*|установил\w*",
    re.IGNORECASE,
)
_WORK_DELAY_RE = re.compile(
    r"срок\w*[^\n]{0,120}(?:работ\w*|услуг\w*|изготовлен\w*|установк\w*)|"
    r"(?:работ\w*|услуг\w*|изготовлен\w*|установк\w*)[^\n]{0,120}(?:срок\w*|просроч\w*)",
    re.IGNORECASE,
)
_GOODS_RETURN_PENALTY_BASIS_RE = re.compile(
    r"(?:обмен\w*|возврат\w*)[^\n]{0,140}товар\w*|"
    r"товар\w*[^\n]{0,180}(?:ненадлежащ\w*\s+качеств\w*|надлежащ\w*\s+качеств\w*)",
    re.IGNORECASE,
)
_WORK_DELAY_PENALTY_BASIS_RE = re.compile(
    r"нарушен\w*\s+срок\w*[^\n]{0,160}(?:начал\w*|окончан\w*|выполнени\w*)[^\n]{0,120}(?:работ\w*|услуг\w*)|"
    r"(?:работ\w*|услуг\w*)[^\n]{0,180}неустойк\w*[^\n]{0,120}(?:кажд\w*\s+день|просроч\w*)",
    re.IGNORECASE,
)


def _text(values: list[str]) -> str:
    return "\n".join(str(value) for value in values or [] if str(value).strip())


def claim_consistency_errors(case_context: str, draft: ClaimDraft) -> list[str]:
    """Return deterministic claim contradictions that must survive model repair."""
    context = case_context or ""
    requests = _text(draft.requests)
    legal_basis = _text(draft.legal_basis)
    facts = _text(draft.facts)
    factual_record = f"{context}\n{facts}"

    errors: list[str] = []

    penalty_requested = bool(_PENALTY_INTENT_RE.search(context))
    costs_requested = bool(_COST_INTENT_RE.search(context))
    penalty_in_prayer = bool(_PENALTY_REQUEST_RE.search(requests))
    costs_in_prayer = bool(_COST_REQUEST_RE.search(requests))

    if penalty_requested and not penalty_in_prayer:
        errors.append(
            "Пользователь прямо просил взыскать неустойку/пеню, но это требование исчезло из раздела «ПРОШУ СУД». "
            "Нельзя молча терять заявленный способ защиты: включите исполнимое требование по VERIFIED-норме и расчету либо явно оставьте документ preliminary с указанием, каких данных не хватает."
        )

    if costs_requested and not costs_in_prayer:
        errors.append(
            "Пользователь прямо просил взыскать судебные расходы, но соответствующего требования нет в разделе «ПРОШУ СУД». "
            "Добавьте процессуально корректное требование о судебных расходах либо явно объясните, почему оно не может быть заявлено по текущим материалам."
        )

    if penalty_in_prayer and not _AMOUNT_RE.search(requests):
        errors.append(
            "В разделе «ПРОШУ СУД» заявлена денежная неустойка/пеня без конкретного размера или проверяемого расчета. "
            "До статуса filing-ready размер должен быть рассчитан по VERIFIED-норме и фактам дела либо документ должен остаться preliminary."
        )

    if (
        _PAID_IN_FULL_RE.search(factual_record)
        and _COUNTERPARTY_NONPERFORMANCE_RE.search(factual_record)
        and _BUYER_NONPAYMENT_BASIS_RE.search(legal_basis)
    ):
        errors.append(
            "Правовое обоснование использует норму о неисполнении покупателем обязанности по предварительной оплате, "
            "хотя по материалам истец оплатил полностью, а нарушение допущено ответчиком. Такая норма направлена против другой фактической ситуации и должна быть исключена или заменена только на VERIFIED-норму, поддерживающую требование истца."
        )

    works_delay_case = bool(_WORKS_CONTEXT_RE.search(factual_record) and _WORK_DELAY_RE.search(factual_record))
    penalty_relevant = penalty_requested or penalty_in_prayer
    if (
        works_delay_case
        and penalty_relevant
        and _GOODS_RETURN_PENALTY_BASIS_RE.search(legal_basis)
        and not _WORK_DELAY_PENALTY_BASIS_RE.search(legal_basis)
    ):
        errors.append(
            "Неустойка по спору о просрочке выполнения работы/услуги обоснована нормой о возврате/качестве товара. "
            "Для filing-ready проекта требуется VERIFIED-норма именно о нарушении сроков начала/окончания выполнения работы (услуги) и соответствующий расчет."
        )

    return list(dict.fromkeys(errors))


def install_claim_consistency_guard() -> None:
    """Extend the existing senior preflight without replacing its protections."""
    current = senior_claim_preflight.deterministic_claim_preflight
    if getattr(current, "_korgan_claim_consistency_guard", False):
        return

    def guarded(case_context: str, research: LegalResearch, draft: ClaimDraft) -> list[str]:
        base = current(case_context, research, draft)
        extra = claim_consistency_errors(case_context, draft)
        return list(dict.fromkeys([*base, *extra]))

    guarded._korgan_claim_consistency_guard = True  # type: ignore[attr-defined]
    senior_claim_preflight.deterministic_claim_preflight = guarded
