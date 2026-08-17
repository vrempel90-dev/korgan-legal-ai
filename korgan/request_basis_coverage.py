"""Deterministic coverage gate: every substantive claim request needs its own law.

A document can cite perfectly real statutes and still be legally incomplete when
those statutes support only one of several remedies.  This module checks common
Kazakhstan litigation remedies independently and opportunistically restores a
matching filing-facing basis from source-bound VERIFIED research.  It never
invents an article: if research contains no matching verified proposition the
request remains a release blocker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

_VERIFIED_RE = re.compile(
    r"^(?P<statement>.*?)\s*\[основание:\s*(?P<article>.*?);\s*текст\s+нормы:",
    re.IGNORECASE | re.DOTALL,
)
_ARTICLE_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*\d+(?:-\d+)?")
_PROCEDURAL_COST_RE = re.compile(
    r"(?i)госпошлин|государственн\w*\s+пошлин|судебн\w*\s+расход|"
    r"расход\w*\s+на\s+представител|почтов\w*\s+расход"
)


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{part})" for part in parts), re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class RemedyRule:
    code: str
    label: str
    request: re.Pattern[str]
    context: re.Pattern[str] | None
    basis: re.Pattern[str]


_RULES: tuple[RemedyRule, ...] = (
    RemedyRule(
        "salary",
        "взыскание заработной платы",
        _rx(r"заработн\w*\s+плат", r"зарплат\w*", r"еңбекақ\w*", r"жалақ\w*"),
        None,
        _rx(r"заработн\w*\s+плат", r"зарплат\w*", r"еңбекақ\w*", r"жалақ\w*", r"оплат\w*\s+труд"),
    ),
    RemedyRule(
        "leave_compensation",
        "компенсация за неиспользованный отпуск",
        _rx(r"неиспользован\w*\s+отпуск", r"компенсац\w*.{0,60}отпуск", r"демалыс.{0,60}өтемақ", r"өтемақ.{0,60}демалыс"),
        None,
        _rx(r"неиспользован\w*\s+отпуск", r"компенсац\w*.{0,80}отпуск", r"демалыс", r"өтемақ"),
    ),
    RemedyRule(
        "immediate_execution",
        "немедленное исполнение",
        _rx(r"немедленн\w*\s+исполн", r"дереу\s+орында"),
        None,
        _rx(r"немедленн\w*\s+исполн", r"дереу\s+орында", r"не\s+свыше\s+чем\s+за\s+три\s+месяц"),
    ),
    RemedyRule(
        "loan_debt",
        "взыскание долга по займу",
        _rx(r"взыска\w*.{0,80}(?:долг|задолженн)", r"вернут\w*.{0,80}(?:долг|сумм)", r"қарыз\w*.{0,80}өндір"),
        _rx(r"за[её]м\w*", r"займ\w*", r"расписк\w*", r"в\s+долг\b", r"қарыз"),
        _rx(r"за[её]мщик\w*.{0,100}возврат", r"за[её]м\w*.{0,100}возврат", r"обязан\w*.{0,80}вернут", r"қарыз.{0,100}қайтар"),
    ),
    RemedyRule(
        "prepayment_refund",
        "возврат предоплаты/аванса",
        _rx(r"взыска\w*.{0,100}(?:предоплат|аванс|предварительн\w*\s+оплат)", r"вернут\w*.{0,100}(?:предоплат|аванс|оплат)"),
        _rx(r"подряд\w*", r"ремонт\w*", r"работ\w*", r"товар\w*", r"поставк\w*", r"услуг\w*"),
        _rx(r"отказ\w*.{0,80}договор", r"возврат\w*.{0,100}(?:предоплат|аванс|оплат)", r"неосновательн\w*\s+обогащ", r"неисполнени\w*\s+обязательств"),
    ),
    RemedyRule(
        "penalty",
        "неустойка/пеня/проценты за просрочку",
        _rx(r"неустойк\w*", r"пен[яию]\b", r"процент\w*.{0,80}просроч", r"стать(?:я|и)\s*353", r"353\s*гк"),
        None,
        _rx(r"неустойк\w*", r"пен[яию]\b", r"процент\w*", r"просроч\w*", r"неправомерн\w*\s+пользован\w*\s+чуж"),
    ),
    RemedyRule(
        "damages",
        "возмещение убытков/ущерба",
        _rx(r"взыска\w*.{0,60}убытк", r"возмест\w*.{0,60}(?:ущерб|вред)", r"материальн\w*\s+ущерб"),
        None,
        _rx(r"убытк\w*", r"реальн\w*\s+ущерб", r"возмещени\w*.{0,60}вред", r"причинн\w*\s+связ"),
    ),
    RemedyRule(
        "moral_damage",
        "компенсация морального вреда",
        _rx(r"моральн\w*\s+вред", r"моральдық\s+зиян"),
        None,
        _rx(r"моральн\w*\s+вред", r"нравственн\w*\s+страдан", r"моральдық\s+зиян"),
    ),
    RemedyRule(
        "termination",
        "расторжение/прекращение договора",
        _rx(r"расторг\w*\s+договор", r"прекрат\w*\s+договор", r"договор\w*\s+прекращ", r"шарт\w*.{0,60}бұз"),
        None,
        _rx(r"расторж\w*", r"отказ\w*.{0,60}договор", r"прекращени\w*\s+договор", r"существенн\w*\s+наруш"),
    ),
    RemedyRule(
        "alimony",
        "взыскание алиментов",
        _rx(r"алимент\w*"),
        None,
        _rx(r"алимент\w*", r"содержани\w*.{0,80}ребен", r"баланы\s+асыра"),
    ),
    RemedyRule(
        "housing_eviction",
        "выселение/вселение по жилищному спору",
        _rx(r"высел\w*", r"вселен\w*", r"тұрғын\s+үйден\s+шығар"),
        None,
        _rx(r"высел\w*", r"вселен\w*", r"жилищн\w*\s+отношен", r"прав\w*\s+пользован\w*\s+жилищ"),
    ),
    RemedyRule(
        "ownership",
        "признание права собственности",
        _rx(r"признат\w*.{0,60}прав\w*\s+собственност", r"меншік\s+құқығ\w*.{0,60}тан"),
        None,
        _rx(r"прав\w*\s+собственност", r"приобретени\w*\s+прав", r"меншік\s+құқы"),
    ),
)


def _render_verified(line: str) -> str | None:
    match = _VERIFIED_RE.search(str(line or ""))
    if not match:
        return None
    statement = " ".join(match.group("statement").split()).strip(" .")
    article = " ".join(match.group("article").split()).strip(" .")
    if not statement or not article or not _ARTICLE_RE.search(article):
        return None
    return f"{statement}. Правовое основание: {article}."


def _rule_applies(rule: RemedyRule, request: str, case_context: str) -> bool:
    if not rule.request.search(request):
        return False
    return rule.context is None or bool(rule.context.search(case_context or ""))


def _basis_has(rule: RemedyRule, lines: list[str]) -> bool:
    return any(rule.basis.search(str(line or "")) and _ARTICLE_RE.search(str(line or "")) for line in lines)


def ensure_request_basis_coverage(
    case_context: str,
    draft: ClaimDraft,
    research: LegalResearch,
) -> list[str]:
    """Restore matching VERIFIED basis where possible and return uncovered remedies."""
    basis = list(draft.legal_basis)
    missing: list[str] = []

    for request in draft.requests:
        request_text = str(request or "").strip()
        if not request_text or _PROCEDURAL_COST_RE.search(request_text):
            continue
        for rule in _RULES:
            if not _rule_applies(rule, request_text, case_context):
                continue
            if not _basis_has(rule, basis):
                for verified in research.verified_claims:
                    if not rule.basis.search(str(verified or "")):
                        continue
                    rendered = _render_verified(str(verified))
                    if rendered and rendered not in basis:
                        basis.append(rendered)
                if not _basis_has(rule, basis):
                    missing.append(rule.label)

    draft.legal_basis = basis
    missing = list(dict.fromkeys(missing))
    if missing:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        note = "Нет отдельной VERIFIED правовой опоры для требований: " + "; ".join(missing)
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)
    return missing
