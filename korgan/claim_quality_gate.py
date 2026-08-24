from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from korgan.legal_basis_fit import enforce_legal_basis_fit
from korgan.legal_calc import parse_all_amounts_kzt, parse_amount_kzt
from korgan.legal_types import ClaimDraft, LegalResearch

LOGGER = logging.getLogger(__name__)
MIN_READY_SCORE = 8.5

_ENTITY_RE = re.compile(r"\b(?:ТОО|АО|РГП|РГУ|КГУ|КГП|ИП|ЖК|КСК|ОО)\b|\bБИН\b", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*\d+")
_PLACEHOLDER_RE = re.compile(r"\[(?:ТРЕБУЕТ УТОЧНЕНИЯ|ТРЕБУЕТ ПРОВЕРКИ|ТРЕБУЕТ РАСЧ[ЕЁ]ТА|ТРЕБУЕТ ДОБАВИТЬ)[^\]]*\]", re.IGNORECASE)
_MONEY_RE = re.compile(r"(?<!\d)\d[\d\s\u00a0.,]{2,}\s*(?:тенге|теңге|тг\b|₸|kzt)", re.IGNORECASE)
_PENALTY_RE = re.compile(
    r"(?:неустойк\w*|пен[яиюь]\w*|штраф\w*|процент\w*\s+(?:по\s+денежн\w*|за\s+просроч\w*)|"
    r"тұрақсыздық\s+айыб\w*|өсімпұл\w*)",
    re.IGNORECASE,
)
_TITLE_PENALTY_RE = re.compile(
    r"(?:неустойк\w*|пен[яиюь]\w*|процент\w*|тұрақсыздық\s+айыб\w*|өсімпұл\w*)",
    re.IGNORECASE,
)
_NON_PROPERTY_REQUEST_RE = re.compile(
    r"(?:государственн\w*\s+пошлин\w*|госпошлин\w*|судебн\w*\s+(?:расход\w*|издерж\w*)|"
    r"расход\w*\s+на\s+(?:оплат\w*\s+)?представител\w*|мемлекеттік\s+баж|сот\s+шығын\w*)",
    re.IGNORECASE,
)
_PROPERTY_REQUEST_RE = re.compile(
    r"(?:взыск\w*|вернут\w*|возврат\w*|долг\w*|задолженн\w*|неустойк\w*|пен[яиюь]\w*|штраф\w*|"
    r"убыт\w*|ущерб\w*|компенсац\w*|өндір\w*|қайтар\w*)",
    re.IGNORECASE,
)
_AWARDED_AMOUNT_RE = re.compile(
    r"(?:в\s+размере|в\s+сумме|сумм\w*|мөлшерінде)\s*"
    r"(?P<amount>\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:тенге|теңге|тг\b|₸|kzt))",
    re.IGNORECASE,
)
_SOURCE_LINE_EXEMPT_RE = re.compile(
    r"(?:государственн\w*\s+пошлин\w*|госпошлин\w*|судебн\w*\s+(?:расход\w*|издерж\w*)|"
    r"расход\w*\s+на\s+(?:оплат\w*\s+)?представител\w*|мемлекеттік\s+баж|сот\s+шығын\w*|"
    r"стоимост\w*\s+отдельн\w*\s+позиц\w*|цен\w*\s+(?:за\s+)?единиц\w*)",
    re.IGNORECASE,
)
_CLAIM_AMOUNT_CONTEXT_RE = re.compile(
    r"(?:задолженн\w*|основн\w*\s+долг\w*|неустойк\w*|пен[яиюь]\w*|штраф\w*|"
    r"к\s+взыскан\w*|взыск\w*|итого\s+ко\s+взыскан\w*|берешек\w*|негізгі\s+қарыз\w*|"
    r"тұрақсыздық\s+айыб\w*|өсімпұл\w*|өндір\w*)",
    re.IGNORECASE,
)
_NONCLAIMED_AMOUNT_CONTEXT_RE = re.compile(
    r"(?:частичн\w*\s+оплат\w*|оплатил\w*|оплачено|уплачено|погашено|внесено|"
    r"зач[её]т\w*|зачтено|цена\s+договор\w*|стоимост\w*\s+договор\w*|"
    r"общ\w*\s+стоимост\w*|аванс\w*\s+(?:уплачен\w*|внес[её]н\w*)|"
    r"ішінара\s+төлен\w*|төленді|есепке\s+жатқыз\w*|шарт\w*\s+бағас\w*)",
    re.IGNORECASE,
)
_UNRESOLVED_AMOUNT_RE = re.compile(r"\[ТРЕБУЕТ\s+(?:ПРОВЕРКИ|РАСЧ[ЕЁ]ТА)[^\]]*\]", re.IGNORECASE)
_CLAUSE_DELIMITER_RE = re.compile(r"[;\n.!?]")


@dataclass(slots=True)
class ClaimQualityReport:
    score: float
    issues: list[str] = field(default_factory=list)
    category_scores: dict[str, float] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        if any(str(issue).startswith("AMOUNT_MISMATCH:") for issue in self.issues):
            return False
        return self.score >= MIN_READY_SCORE


def _text(draft: ClaimDraft) -> str:
    return "\n".join([
        draft.title, draft.court, *draft.claimant, *draft.defendant,
        draft.price_of_claim, draft.state_duty, *draft.facts,
        *draft.legal_basis, *draft.requests, *draft.attachments,
    ])


def _party_text(lines: list[str]) -> str:
    return "\n".join(str(x) for x in lines or [])


def _awarded_amount(request: str) -> int | None:
    match = _AWARDED_AMOUNT_RE.search(request or "")
    if match:
        return parse_amount_kzt(match.group("amount"))
    amounts = parse_all_amounts_kzt(request or "")
    if not amounts:
        return None
    if _PENALTY_RE.search(request or "") and len(amounts) > 1:
        return amounts[-1]
    return amounts[0]


def _nearest_cue_distance(pattern: re.Pattern[str], text: str, start: int, end: int) -> int | None:
    """Return distance from one money token to the nearest semantic cue."""
    left_start = max(0, start - 100)
    left = text[left_start:start]
    right = text[end:min(len(text), end + 55)]
    distances: list[int] = []
    for match in pattern.finditer(left):
        distances.append(start - (left_start + match.end()))
    for match in pattern.finditer(right):
        distances.append(match.start())
    return min(distances) if distances else None


def _money_clause(text: str, start: int, end: int) -> tuple[str, int, int]:
    """Bind one amount to its semicolon/sentence clause before cue comparison."""
    left = 0
    for match in _CLAUSE_DELIMITER_RE.finditer(text, 0, start):
        left = match.end()
    right = len(text)
    match = _CLAUSE_DELIMITER_RE.search(text, end)
    if match:
        right = match.start()
    return text[left:right], start - left, end - left


def _source_amount_is_exempt(text: str, start: int, end: int) -> bool:
    """Whitelist only clearly non-claimed factual amounts around one money token.

    Cues are compared only inside the amount's factual clause. This prevents a
    neighboring judicial-cost/payment clause from hiding a contradictory debt
    amount, while still exempting historical payments, contract price, set-offs
    and non-property costs from the claim-price reconciliation.
    """
    clause, local_start, local_end = _money_clause(text, start, end)
    distances = [
        value
        for value in (
            _nearest_cue_distance(_NONCLAIMED_AMOUNT_CONTEXT_RE, clause, local_start, local_end),
            _nearest_cue_distance(_SOURCE_LINE_EXEMPT_RE, clause, local_start, local_end),
        )
        if value is not None
    ]
    if not distances:
        return False
    nonclaimed_distance = min(distances)
    claim_distance = _nearest_cue_distance(_CLAIM_AMOUNT_CONTEXT_RE, clause, local_start, local_end)
    return claim_distance is None or nonclaimed_distance < claim_distance


def check_amount_consistency(draft: ClaimDraft) -> list[str]:
    """Return blocking monetary contradictions between reasoning and prayer.

    A deliberately unresolved preliminary demand marked ``ТРЕБУЕТ ПРОВЕРКИ``
    is not a silent mismatch. In every other case, amounts presented as claimed
    debt/sanctions must survive into the prayer and the claim-price arithmetic.
    Historical payments, contract price and set-offs are checked per money token
    and are exempt only when their local wording clearly says they are not a
    separate amount sought from the court.
    """
    errors: list[str] = []
    target_amounts: set[int] = set()
    for request in draft.requests or []:
        target_amounts.update(parse_all_amounts_kzt(str(request)))
    target_amounts.update(parse_all_amounts_kzt(draft.price_of_claim or ""))

    title = str(draft.title or "")
    if (_PROPERTY_REQUEST_RE.search(title) or _TITLE_PENALTY_RE.search(title)) and not _UNRESOLVED_AMOUNT_RE.search(title):
        for amount in parse_all_amounts_kzt(title):
            if amount not in target_amounts:
                errors.append(
                    f"Сумма {amount:,} тенге из title отсутствует одновременно в петитуме и цене иска."
                    .replace(",", " ")
                )

    for field_name, values in (("facts", draft.facts), ("attachments", draft.attachments)):
        for line in values or []:
            text = str(line)
            for match in _MONEY_RE.finditer(text):
                amount = parse_amount_kzt(match.group(0))
                if amount is None or _source_amount_is_exempt(text, match.start(), match.end()):
                    continue
                if amount not in target_amounts:
                    errors.append(
                        f"Сумма {amount:,} тенге из {field_name} отсутствует одновременно в петитуме и цене иска."
                        .replace(",", " ")
                    )

    property_total = 0
    has_property_amount = False
    unresolved_property = False
    for request in draft.requests or []:
        text = str(request)
        if _NON_PROPERTY_REQUEST_RE.search(text) or not _PROPERTY_REQUEST_RE.search(text):
            continue
        if _UNRESOLVED_AMOUNT_RE.search(text):
            unresolved_property = True
            continue
        amount = _awarded_amount(text)
        if amount is None:
            errors.append("В петитуме есть имущественное требование без конкретной денежной суммы или проверяемого расчёта.")
            continue
        property_total += amount
        has_property_amount = True

    price = parse_amount_kzt(draft.price_of_claim or "")
    price_unresolved = bool(_UNRESOLVED_AMOUNT_RE.search(draft.price_of_claim or ""))
    if has_property_amount and not unresolved_property:
        if price is None and not price_unresolved:
            errors.append("Цена иска не содержит конкретной суммы при определённых имущественных требованиях.")
        elif price is not None and price != property_total:
            errors.append(
                f"Цена иска {price:,} тенге не равна сумме имущественных требований петитума {property_total:,} тенге."
                .replace(",", " ")
            )

    title_has_penalty = bool(_TITLE_PENALTY_RE.search(draft.title or ""))
    prayer_has_penalty = any(_PENALTY_RE.search(str(item)) for item in draft.requests or [])
    if title_has_penalty and not prayer_has_penalty:
        errors.append("Заголовок иска содержит неустойку/пеню/проценты, но соответствующее требование отсутствует в петитуме.")

    errors = list(dict.fromkeys(errors))
    if errors:
        LOGGER.error("CLAIM_FAIL code=AMOUNT_MISMATCH issues=%s", errors)
    return errors


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
    amount_errors = check_amount_consistency(draft)
    if amount_errors:
        score = 0.0
        issues.extend(f"AMOUNT_MISMATCH: {item}" for item in amount_errors)
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