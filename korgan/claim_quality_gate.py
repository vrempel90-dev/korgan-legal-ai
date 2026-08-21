from __future__ import annotations

import re
from dataclasses import dataclass, field

from korgan.legal_basis_fit import enforce_legal_basis_fit
from korgan.legal_types import ClaimDraft, LegalResearch

MIN_READY_SCORE = 8.5

_ENTITY_RE = re.compile(r"\b(?:ТОО|АО|РГП|РГУ|КГУ|КГП|ИП|ЖК|КСК|ОО)\b|\bБИН\b", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*\d+")
_PLACEHOLDER_RE = re.compile(r"\[(?:ТРЕБУЕТ УТОЧНЕНИЯ|ТРЕБУЕТ ПРОВЕРКИ|ТРЕБУЕТ РАСЧ[ЕЁ]ТА|ТРЕБУЕТ ДОБАВИТЬ)[^\]]*\]", re.IGNORECASE)
_MONEY_RE = re.compile(r"(?<!\d)\d[\d\s\u00a0.,]{2,}\s*(?:тенге|тг\b|₸|kzt)", re.IGNORECASE)


@dataclass(slots=True)
class ClaimQualityReport:
    score: float
    issues: list[str] = field(default_factory=list)
    category_scores: dict[str, float] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.score >= MIN_READY_SCORE


def _text(draft: ClaimDraft) -> str:
    return "\n".join([
        draft.title, draft.court, *draft.claimant, *draft.defendant,
        draft.price_of_claim, draft.state_duty, *draft.facts,
        *draft.legal_basis, *draft.requests, *draft.attachments,
    ])


def _party_text(lines: list[str]) -> str:
    return "\n".join(str(x) for x in lines or [])


def normalize_party_placeholders(draft: ClaimDraft) -> None:
    defendant = _party_text(draft.defendant)
    if _ENTITY_RE.search(defendant):
        draft.defendant = [
            line for line in draft.defendant
            if not ("требует уточнения" in line.lower() and "фио ответчика" in line.lower())
        ]
    claimant = _party_text(draft.claimant)
    if not _ENTITY_RE.search(claimant):
        draft.claimant = [
            line for line in draft.claimant
            if not ("требует уточнения" in line.lower() and "банковск" in line.lower())
        ]


def _score_parties(case_context: str, draft: ClaimDraft, issues: list[str]) -> float:
    score = 1.5
    claimant = _party_text(draft.claimant)
    defendant = _party_text(draft.defendant)
    if not claimant.strip():
        score -= 0.75; issues.append("не заполнены данные истца")
    if not defendant.strip():
        score -= 0.75; issues.append("не заполнены данные ответчика")
    for identifier in set(re.findall(r"(?<!\d)\d{12}(?!\d)", case_context)):
        if identifier not in claimant and identifier not in defendant:
            score -= 0.35; issues.append(f"потерян известный ИИН/БИН {identifier}")
    if _ENTITY_RE.search(defendant) and re.search(r"ТРЕБУЕТ УТОЧНЕНИЯ[^\]]*ФИО ответчика", defendant, re.IGNORECASE):
        score -= 0.75; issues.append("у юридического лица ошибочно запрошено ФИО ответчика")
    if not _ENTITY_RE.search(claimant) and re.search(r"ТРЕБУЕТ УТОЧНЕНИЯ[^\]]*банковск", claimant, re.IGNORECASE):
        score -= 0.35; issues.append("у истца-физлица ошибочно запрошены банковские реквизиты как обязательные")
    return max(0.0, score)


def _score_facts_and_amount(case_context: str, draft: ClaimDraft, issues: list[str]) -> float:
    score = 1.5
    if len([x for x in draft.facts if str(x).strip()]) < 3:
        score -= 0.5; issues.append("фактическая часть слишком короткая для судебного иска")
    if _MONEY_RE.search(case_context) and not _MONEY_RE.search(draft.price_of_claim or ""):
        score -= 0.5; issues.append("цена иска не отражает известную денежную сумму")
    if not draft.requests:
        score -= 0.5; issues.append("отсутствует просительная часть")
    return max(0.0, score)


def _score_legal_basis(research: LegalResearch, draft: ClaimDraft, issues: list[str]) -> float:
    score = 2.0
    basis = "\n".join(draft.legal_basis)
    if not draft.legal_basis:
        score -= 1.5; issues.append("отсутствует правовое обоснование")
        return max(0.0, score)
    if research.verified_claims and not _ARTICLE_RE.search(basis):
        score -= 0.9; issues.append("есть VERIFIED-нормы, но в правовом обосновании нет конкретных статей")
    fit = enforce_legal_basis_fit(draft)
    if fit:
        score -= min(1.0, 0.5 + 0.2 * len(fit))
        issues.extend(f"правовое основание не поддерживает требование: {x}" for x in fit[:3])
    if not research.verified_claims:
        score -= 0.7; issues.append("нет подтвержденной материально-правовой основы")
    return max(0.0, score)


def _score_relief_coherence(case_context: str, draft: ClaimDraft, issues: list[str]) -> float:
    score = 1.5
    text = (case_context + "\n" + _text(draft)).lower()
    requests = "\n".join(draft.requests).lower()
    prepayment = any(x in text for x in ("предоплат", "аванс", "предварительн"))
    works = any(x in text for x in ("подряд", "ремонт", "работ"))
    not_started = any(x in text for x in ("не приступ", "не начал", "не выполнил", "не выполн"))
    return_money = any(x in requests for x in ("взыск", "вернут", "возврат"))
    # Include all common grammatical forms: отказ, расторжение, прекращение,
    # and an explicit request «прекратить договорные отношения».
    termination = any(x in text for x in ("отказ от договор", "расторг", "прекрат", "прекращ"))
    if prepayment and works and not_started and return_money and not termination:
        score -= 0.75; issues.append("возврат предоплаты заявлен без ясной конструкции отказа/прекращения договора")
    if "неосновательн" in "\n".join(draft.legal_basis).lower() and not termination:
        score -= 0.35; issues.append("неосновательное обогащение указано без объяснения отпадения договорного основания")
    return max(0.0, score)


def _score_procedure(draft: ClaimDraft, issues: list[str]) -> float:
    score = 1.5
    court = (draft.court or "").strip()
    if not court:
        score -= 0.75; issues.append("не указан суд")
    elif "ТРЕБУЕТ УТОЧНЕНИЯ" in court.upper():
        score -= 0.45; issues.append("точный суд не определен")
    duty = (draft.state_duty or "").upper()
    if not duty or "ТРЕБУЕТ" in duty:
        score -= 0.45; issues.append("госпошлина не определена либо не обосновано освобождение")
    return max(0.0, score)


def _score_evidence(case_context: str, draft: ClaimDraft, issues: list[str]) -> float:
    score = 1.0
    attachments = "\n".join(draft.attachments).lower()
    for source_marker, attachment_marker in (("договор","договор"),("квитанц","квитанц"),("претензи","претензи"),("расписк","расписк"),("акт","акт")):
        if source_marker in case_context.lower() and attachment_marker not in attachments:
            score -= 0.2; issues.append(f"в приложениях потеряно известное доказательство: {source_marker}")
    return max(0.0, score)


def _score_hygiene(draft: ClaimDraft, issues: list[str]) -> float:
    score = 1.0
    body = _text(draft)
    forbidden = ("http://", "https://", "###", "**", "могу доработать", "если нужно")
    if any(token in body.lower() for token in forbidden):
        score -= 0.6; issues.append("в судебном тексте остался служебный/чатовый текст")
    placeholders = _PLACEHOLDER_RE.findall(body)
    if len(placeholders) >= 4:
        score -= 0.4; issues.append("в документе слишком много незаполненных служебных полей")
    elif placeholders:
        score -= min(0.25, 0.08 * len(placeholders))
    return max(0.0, score)


def assess_claim_quality(case_context: str, research: LegalResearch, draft: ClaimDraft) -> ClaimQualityReport:
    issues: list[str] = []
    normalize_party_placeholders(draft)
    categories = {
        "parties": _score_parties(case_context, draft, issues),
        "facts_amount": _score_facts_and_amount(case_context, draft, issues),
        "legal_basis": _score_legal_basis(research, draft, issues),
        "relief": _score_relief_coherence(case_context, draft, issues),
        "procedure": _score_procedure(draft, issues),
        "evidence": _score_evidence(case_context, draft, issues),
        "hygiene": _score_hygiene(draft, issues),
    }
    return ClaimQualityReport(
        score=round(sum(categories.values()), 1),
        issues=list(dict.fromkeys(issues)),
        category_scores=categories,
    )
