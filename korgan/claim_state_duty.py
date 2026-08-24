"""Professional state-duty routing for civil claims in Kazakhstan.

The model never chooses a tariff or amount.  This layer classifies the final
court-facing relief after deterministic claim cleanup and applies only rules
that can be established safely from the final draft and VERIFIED research.
Unclear or special categories fail closed instead of receiving a convenient
1%/3% calculation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from korgan.claim_filing_accuracy import FILING_ACTION_PREFIX
from korgan.claim_money_ledger import ClaimMoneyLedger, build_claim_money_ledger
from korgan.legal_calc import (
    CAP_MRP_INDIVIDUAL,
    CAP_MRP_LEGAL_ENTITY,
    NEEDS_CALCULATION_MARKER,
    NONPROPERTY_DUTY_MRP,
    RATE_INDIVIDUAL,
    RATE_LEGAL_ENTITY,
    RATE_SOURCE_ARTICLE,
    calc_gosposhlina_claim,
    calc_nonproperty_state_duty,
    claimant_is_individual,
    format_kzt,
)
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

_STATE_DUTY_RE = re.compile(r"(?:госпошлин\w*|государственн\w*\s+пошлин\w*|мемлекеттік\s+баж)", re.IGNORECASE)
_COST_RE = re.compile(r"(?:судебн\w*\s+расход\w*|сот\s+шығын\w*)", re.IGNORECASE)
_PROCEDURAL_RE = re.compile(
    r"^(?:вызвать|допросить|истребовать|приобщить|назначить|обеспечить\s+иск|"
    r"шақыр|сұрат|тірке|сараптама\s+тағайында)",
    re.IGNORECASE,
)
_NONPROPERTY_RE = re.compile(
    r"(?:\bрасторг\w*\s+договор\w*|\bизмен\w*\s+договор\w*|"
    r"\bпризнать\b.{0,100}(?:недействительн\w*|прав\w*|обязанност\w*|факт\w*|договор\w*)|"
    r"\bобязать\b|\bвозложить\s+обязанност\w*|\bзапретить\b|\bпрекратить\b.{0,80}(?:действ|наруш|договор)|"
    r"\bосвободить\b.{0,80}\b(?:имуществ\w*|арест\w*)|\bпродлить\b.{0,80}\bсрок\w*|"
    r"\bвселить\b|\bвыселить\b|\bустранить\b.{0,80}\bпрепятств\w*|"
    r"міндетте\w*|жарамсыз\s+деп\s+тану|шартты\s+бұзу)",
    re.IGNORECASE,
)
_SPECIAL_CATEGORY_RE = re.compile(
    r"(?:расторжени\w*\s+брака|развод\w*|административн\w*\s+иск|"
    r"оспарив\w*\s+(?:уведомлен|акт\w*\s+проверк|действ\w*\s+гос)|"
    r"банкрот\w*|реабилитационн\w*\s+процедур\w*|судебн\w*\s+приказ\w*|"
    r"отмен\w*\s+решени\w*\s+арбитраж\w*|исполнительн\w*\s+лист\w*|"
    r"чест[ьи]\b|достоинств\w*|делов\w*\s+репутаци\w*)",
    re.IGNORECASE,
)
_CONSUMER_SOURCE_RE = re.compile(
    r"(?:Z100000274_|защит\w*\s+прав\w*\s+потребител\w*|тұтынушылардың\s+құқықтарын\s+қорға)",
    re.IGNORECASE,
)
_DISABILITY_RE = re.compile(
    r"(?:лиц\w*\s+с\s+инвалидност\w*|инвалидност\w*|"
    r"родител\w*[^\n,;]{0,80}(?:ребенк\w*|ребёнк\w*)\s+с\s+инвалидност\w*|"
    r"мүгедект\w*)",
    re.IGNORECASE,
)
_EXEMPTION_PROOF_RE = re.compile(
    r"(?:справк\w*|удостоверен\w*|заключени\w*|құжат\w*).{0,80}(?:инвалидност\w*|мүгедект\w*)|"
    r"(?:инвалидност\w*|мүгедект\w*).{0,80}(?:справк\w*|удостоверен\w*|құжат\w*)",
    re.IGNORECASE,
)
_ALIMONY_RE = re.compile(r"(?:взыска\w*|өндір\w*).{0,80}(?:алимент\w*|алименттер\w*)", re.IGNORECASE)
_WAGE_RE = re.compile(
    r"(?:взыска\w*|өндір\w*).{0,100}(?:заработн\w*\s+плат\w*|жалақы\w*)|"
    r"(?:заработн\w*\s+плат\w*|жалақы\w*).{0,100}(?:взыска\w*|өндір\w*)",
    re.IGNORECASE,
)
_HEALTH_DAMAGE_RE = re.compile(
    r"возмещ\w*.{0,100}(?:вред\w*).{0,100}(?:здоров\w*|увечь\w*|смерт\w*\s+кормил\w*)|"
    r"(?:здоров\w*|увечь\w*|смерт\w*\s+кормил\w*).{0,100}возмещ\w*",
    re.IGNORECASE,
)
_CRIMINAL_DAMAGE_RE = re.compile(
    r"возмещ\w*.{0,100}материал\w*\s+ущерб\w*.{0,120}уголовн\w*\s+правонаруш\w*|"
    r"уголовн\w*\s+правонаруш\w*.{0,120}материал\w*\s+ущерб\w*",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class StateDutyDecision:
    mode: str
    line: str
    amount: int | None
    deferred: bool = False
    exempt: bool = False
    needs_review: bool = False
    note: str = ""
    exemption_proof_required: bool = False


def _claimant_individual(case_context: str, draft: ClaimDraft) -> bool | None:
    result = claimant_is_individual(case_context)
    if result is not None:
        return result
    party = " ".join(str(item) for item in draft.claimant or [])
    return claimant_is_individual(f"Истец: {party}")


def _claimant_context(case_context: str, draft: ClaimDraft) -> str:
    parts = [" ".join(str(item) for item in draft.claimant or [])]
    match = re.search(
        r"(?is)(?:истец|талап\s+қоюшы)\s*:\s*(.*?)(?=(?:\n|;|\s)(?:ответчик|жауапкер)\s*:|\Z)",
        case_context or "",
    )
    if match:
        parts.append(match.group(1))
    return "\n".join(parts)


def _consumer_grounded(case_context: str, research: LegalResearch, draft: ClaimDraft) -> bool:
    if _claimant_individual(case_context, draft) is not True:
        return False
    # Deferral is a legal consequence.  A stray word "consumer" in a pleading,
    # especially inside the opponent's position, is not enough.  Require a
    # source-bound VERIFIED proposition from the consumer-law research path.
    verified = "\n".join(str(item) for item in research.verified_claims or [])
    return bool(_CONSUMER_SOURCE_RE.search(verified))


def _article668_exemption(case_context: str, draft: ClaimDraft) -> StateDutyDecision | None:
    claimant = _claimant_context(case_context, draft)
    relief = "\n".join([draft.title or "", *[str(item) for item in draft.requests or []]])

    if _DISABILITY_RE.search(claimant):
        return StateDutyDecision(
            mode="exempt_disability",
            line="0 тенге (освобождение от уплаты государственной пошлины; пункт 13 статьи 668 Налогового кодекса РК)",
            amount=0,
            exempt=True,
            exemption_proof_required=True,
        )
    if _ALIMONY_RE.search(relief):
        return StateDutyDecision(
            mode="exempt_alimony",
            line="0 тенге (освобождение от уплаты государственной пошлины; пункт 4 статьи 668 Налогового кодекса РК)",
            amount=0,
            exempt=True,
        )
    if _WAGE_RE.search(relief):
        return StateDutyDecision(
            mode="exempt_wage",
            line="0 тенге (освобождение от уплаты государственной пошлины; пункт 1 статьи 668 Налогового кодекса РК)",
            amount=0,
            exempt=True,
        )
    if _HEALTH_DAMAGE_RE.search(relief):
        return StateDutyDecision(
            mode="exempt_health_damage",
            line="0 тенге (освобождение от уплаты государственной пошлины; пункт 5 статьи 668 Налогового кодекса РК)",
            amount=0,
            exempt=True,
        )
    if _CRIMINAL_DAMAGE_RE.search(relief):
        return StateDutyDecision(
            mode="exempt_criminal_damage",
            line="0 тенге (освобождение от уплаты государственной пошлины; пункт 6 статьи 668 Налогового кодекса РК)",
            amount=0,
            exempt=True,
        )
    return None


def _nonproperty_requests(draft: ClaimDraft, ledger: ClaimMoneyLedger) -> list[str]:
    result: list[str] = []
    if ledger.nonproperty_money_components:
        result.extend(item.source_request for item in ledger.nonproperty_money_components)

    for raw in draft.requests or []:
        text = " ".join(str(raw or "").split()).strip()
        if not text or _STATE_DUTY_RE.search(text) or _COST_RE.search(text) or _PROCEDURAL_RE.search(text):
            continue
        if re.search(r"\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:тенге|теңге|тг\b|₸|kzt)", text, re.IGNORECASE):
            continue
        if _NONPROPERTY_RE.search(text):
            result.append(text)
    return list(dict.fromkeys(result))


def _property_line(amount: int, is_individual: bool) -> tuple[int, str]:
    duty = calc_gosposhlina_claim(amount, is_individual)
    rate = RATE_INDIVIDUAL if is_individual else RATE_LEGAL_ENTITY
    cap_mrp = CAP_MRP_INDIVIDUAL if is_individual else CAP_MRP_LEGAL_ENTITY
    line = (
        f"{format_kzt(duty)} ({rate * 100:g}% от цены иска; максимум {cap_mrp:,} МРП; {RATE_SOURCE_ARTICLE})"
    ).replace(",", " ")
    return duty, line


def decide_state_duty(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
) -> StateDutyDecision:
    """Choose and calculate an applicable current-law state-duty route."""
    exemption = _article668_exemption(case_context, draft)
    if exemption is not None:
        return exemption

    # Route by final court-facing relief, not incidental words in the source
    # documents.  Historical references to bankruptcy/divorce/etc. must not
    # change the tariff of the claim actually being filed.
    relief_text = "\n".join([draft.title or "", *draft.requests])
    if _SPECIAL_CATEGORY_RE.search(relief_text):
        return StateDutyDecision(
            mode="special",
            line=NEEDS_CALCULATION_MARKER,
            amount=None,
            needs_review=True,
            note=(
                "обнаружена специальная категория статьи 665 НК РК; обычная ставка имущественного/"
                "неимущественного иска не применяется автоматически без отдельной классификации."
            ),
        )

    ledger = build_claim_money_ledger(list(draft.requests or []))
    if ledger.unresolved_requests:
        return StateDutyDecision(
            mode="ambiguous_price",
            line=NEEDS_CALCULATION_MARKER,
            amount=None,
            needs_review=True,
            note="цена иска не определена однозначно по независимым денежным требованиям.",
        )

    is_individual = _claimant_individual(case_context, draft)
    if is_individual is None:
        return StateDutyDecision(
            mode="unknown_claimant",
            line=NEEDS_CALCULATION_MARKER,
            amount=None,
            needs_review=True,
            note="не установлен статус истца (физическое или юридическое лицо) для выбора ставки.",
        )

    nonproperty = _nonproperty_requests(draft, ledger)
    if len(nonproperty) > 1:
        return StateDutyDecision(
            mode="multiple_nonproperty",
            line=NEEDS_CALCULATION_MARKER,
            amount=None,
            needs_review=True,
            note=(
                "заявлено несколько самостоятельных неимущественных требований; до автоматического расчета "
                "нужно определить, образуют ли они один способ защиты или подлежат отдельной оплате."
            ),
        )

    has_property = ledger.total > 0
    has_nonproperty = bool(nonproperty)
    if not has_property and not has_nonproperty:
        return StateDutyDecision(
            mode="unclassified",
            line=NEEDS_CALCULATION_MARKER,
            amount=None,
            needs_review=True,
            note="вид требования для расчета государственной пошлины не классифицирован детерминированно.",
        )

    if has_property:
        property_duty, property_line = _property_line(ledger.total, is_individual)
    else:
        property_duty, property_line = 0, ""
    nonproperty_duty = calc_nonproperty_state_duty(demands=1) if has_nonproperty else 0

    if has_property and has_nonproperty:
        amount = property_duty + nonproperty_duty
        line = (
            f"{format_kzt(amount)} ({property_line.split('(', 1)[1].rstrip(')')} + "
            f"{NONPROPERTY_DUTY_MRP:g} МРП за неимущественное требование; пункт 4 {RATE_SOURCE_ARTICLE})"
        )
        mode = "mixed"
    elif has_property:
        amount, line, mode = property_duty, property_line, "property"
    else:
        amount = nonproperty_duty
        line = f"{format_kzt(amount)} ({NONPROPERTY_DUTY_MRP:g} МРП; подпункт 7 пункта 1 {RATE_SOURCE_ARTICLE})"
        mode = "nonproperty"

    deferred = _consumer_grounded(case_context, research, draft)
    if deferred:
        line = (
            f"{format_kzt(amount)} (рассчитано по {RATE_SOURCE_ARTICLE}; "
            "уплата отсрочена до принятия решения судом по части 3 статьи 106 ГПК РК)"
        )
    return StateDutyDecision(mode=mode, line=line, amount=amount, deferred=deferred)


def _remove_payment_filing_actions(draft: ClaimDraft) -> None:
    draft.verification_notes = [
        note for note in draft.verification_notes
        if not (
            str(note).startswith(FILING_ACTION_PREFIX)
            and "пошлин" in str(note).lower()
            and any(word in str(note).lower() for word in ("уплат", "квитанц", "платеж", "документ"))
        )
    ]


def apply_professional_state_duty(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
) -> StateDutyDecision:
    decision = decide_state_duty(case_context, research, draft)
    draft.state_duty = decision.line

    # Legacy pre-QA may have inserted a reimbursement request before the final
    # category was known.  The final router owns the single canonical outcome.
    draft.requests = [request for request in draft.requests if not _STATE_DUTY_RE.search(str(request))]

    if decision.needs_review:
        note = "Государственная пошлина требует проверки: " + decision.note
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        return decision

    draft.verification_notes = [
        note for note in draft.verification_notes
        if not str(note).startswith("Государственная пошлина требует проверки:")
    ]

    if decision.deferred or decision.exempt:
        _remove_payment_filing_actions(draft)
        if decision.exempt and decision.exemption_proof_required:
            proof_text = "\n".join([case_context or "", *draft.attachments])
            if not _EXEMPTION_PROOF_RE.search(proof_text):
                note = (
                    FILING_ACTION_PREFIX
                    + "приложить документ, подтверждающий льготу истца по пункту 13 статьи 668 НК РК."
                )
                if note not in draft.verification_notes:
                    draft.verification_notes.append(note)
                draft.status = VerificationStatus.NEEDS_VERIFICATION
        return decision

    if decision.amount is not None:
        draft.requests.append(
            "Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины "
            f"в размере {format_kzt(decision.amount)}."
        )
    return decision
