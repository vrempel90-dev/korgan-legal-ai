"""Exemplar-driven claim architecture derived from 12 user-provided RK pleadings.

The exemplars define reasoning order and cross-block consistency only. Facts and
current law still come exclusively from the user's materials and VERIFIED sources.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.openai_legal import _CLAIM_SCHEMA
from korgan.pro_claim_sections import pro_payload


@dataclass(frozen=True, slots=True)
class ClaimArchitecture:
    code: str
    label: str
    sequence: tuple[str, ...]


_ARCH = {
    "supply": ClaimArchitecture("supply", "договор поставки", (
        "договор и предмет поставки", "профильная норма о поставке", "исполнение поставщиком и доказательство передачи",
        "срок оплаты", "нарушение покупателем", "расчет долга", "неустойка/проценты только при подтвержденном основании",
        "досудебные действия только по фактам", "судебные расходы только по фактам", "краткий вывод и ПРОШУ СУД",
    )),
    "work": ClaimArchitecture("work", "подряд / услуги", (
        "договор и результат работ/услуг", "профильная квалификация", "срок и цена", "исполнение истцом и акт/иной доказанный результат",
        "обязанность ответчика принять/оплатить", "нарушение и период просрочки", "расчет каждого требования",
        "досудебные действия только по фактам", "судебные расходы только по фактам", "ПРОШУ СУД зеркально мотивировке",
    )),
    "money": ClaimArchitecture("money", "расписка / заем / задаток", (
        "документ-основание", "передача денег", "срок/условие возврата", "нарушение", "профильная материальная норма",
        "точный расчет", "дополнительная ответственность только по праву и фактам", "расходы только по подтвержденным материалам", "ПРОШУ СУД",
    )),
    "refund": ClaimArchitecture("refund", "возврат предоплаты / гарантии", (
        "основание платежа", "факт и размер платежа", "встречное обязательство", "неисполнение/расторжение только если подтверждено",
        "почему сумма подлежит возврату", "проценты/неустойка только по VERIFIED и фактам", "ПРОШУ СУД",
    )),
    "property": ClaimArchitecture("property", "имущество / аренда", (
        "право/договор на имущество", "идентификация объекта", "передача/пользование", "нарушение",
        "соответствующий способ защиты", "денежные требования и расчет при наличии", "ПРОШУ СУД",
    )),
    "admin": ClaimArchitecture("admin", "административный иск", (
        "оспариваемый административный акт/действие", "дата и содержание", "затронутое право/интерес",
        "конкретная незаконность по VERIFIED", "порядок и срок обращения, если применимы", "точный способ административной защиты",
    )),
}
_DEFAULT = ClaimArchitecture("general", "гражданский иск", (
    "правоотношение", "юридически значимые условия", "исполнение истца", "нарушение ответчика",
    "профильные VERIFIED нормы", "расчет каждого требования", "досудебные действия только по фактам",
    "судебные расходы только по фактам", "ПРОШУ СУД зеркально мотивировке",
))


def detect_architecture(case_context: str) -> ClaimArchitecture:
    t = (case_context or "").lower()
    if any(x in t for x in ("налог", "угд", "госорган")) and any(x in t for x in ("административ", "уведомлен")):
        return _ARCH["admin"]
    if any(x in t for x in ("поставк", "поставщик", "покупател")):
        return _ARCH["supply"]
    if any(x in t for x in ("подряд", "акт выполн", "монтаж", "оказанн", "услуг")):
        return _ARCH["work"]
    if any(x in t for x in ("расписк", "займ", "заем", "задат")):
        return _ARCH["money"]
    if any(x in t for x in ("предоплат", "аванс", "гарант")) and any(x in t for x in ("возврат", "расторж", "не исполн")):
        return _ARCH["refund"]
    if any(x in t for x in ("аренд", "имуще", "освобожд", "собственност")):
        return _ARCH["property"]
    return _DEFAULT


def architecture_block(case_context: str) -> str:
    arch = detect_architecture(case_context)
    seq = "\n".join(f"{i}. {x}" for i, x in enumerate(arch.sequence, 1))
    return f"""ЭТАЛОННАЯ АРХИТЕКТУРА ИСКА KORGAN — на основе 12 реальных исков пользователя.
Профиль: {arch.label}. Это не источник фактов и не источник права.

Последовательность мотивировки:
{seq}

ЖЕСТКИЕ ПРАВИЛА:
1. Каждое требование в ПРОШУ СУД ранее обосновано фактом + доказательством + VERIFIED-нормой.
2. Для гражданского спора процессуальные нормы ГПК не заменяют материальное право: по каждому самостоятельному способу защиты должна остаться конкретная VERIFIED материальная норма.
3. Явно запрошенное пользователем требование нельзя «исправить» удалением. Если оно подтверждено фактами и VERIFIED — восстанови его в мотивировке и ПРОШУ СУД. Если VERIFIED-основания нет — не выдумывай статью, оставь вопрос на проверку.
4. Договорную пеню/неустойку и ответственность по статье 353 не смешивай автоматически: используй только тот способ ответственности, который следует из материалов и VERIFIED.
5. Госпошлину и расходы представителя заявляй как понесенные расходы только когда входные материалы подтверждают их оплату. Сам расчет госпошлины не является фактом ее уплаты.
6. Процессуальная норма допускается только при фактическом якоре. Нельзя писать о филиале, представительстве, договорной подсудности и иных специальных основаниях, если их нет в фабуле.
7. Если VERIFIED подтверждает территориальную подсудность по месту нахождения/жительства ответчика и в иске указан конкретный суд, соответствующая норма не должна исчезать при repair.
8. Статья в тезисе и статья в его основании должны совпадать либо связь нескольких норм прямо объясняется.
9. Для специального договора сначала профильная норма; общие нормы — только если реально нужны.
10. Не используй хедж вроде «в зависимости от того, что наступит ранее». Выбирай один подтвержденный предел требования либо не выдумывай его.
11. Обязательный, но отсутствующий процессуальный документ не придумывай как существующий: используй [ТРЕБУЕТ ДОБАВИТЬ: ...], если его необходимость следует из VERIFIED.
12. Перед возвратом сверка обязательна: ФАКТЫ -> ДОКАЗАТЕЛЬСТВА -> НОРМЫ -> РАСЧЕТЫ -> ПРОШУ СУД -> ПРИЛОЖЕНИЯ.
"""


def _money(value: str) -> bool:
    u = (value or "").upper()
    return bool(u and "ТРЕБУЕТ" not in u and "NEEDS" not in u and re.search(r"\d[\d\s\u00a0]*\s*(?:ТЕНГЕ|₸)", u))


def _penalty(text: str) -> bool:
    low = (text or "").lower()
    return "неустойк" in low or bool(re.search(r"\bпен(?:я|и|ю|ей|е)?\b", low))


def _articles(text: str) -> set[str]:
    low = (text or "").lower()
    return set(re.findall(r"(?:стать(?:я|и|ей|ю)|ст\.)\s*(\d{1,4})", low))


def _is_procedural_line(text: str) -> bool:
    low = (text or "").lower()
    return "гпк" in low or "гражданского процессуального кодекса" in low or "гражданский процессуальный кодекс" in low


def _is_material_line(text: str) -> bool:
    low = (text or "").lower()
    if _is_procedural_line(low):
        return False
    return any(x in low for x in ("гк рк", "гражданского кодекса", "гражданский кодекс", "закон республики казахстан", "закон рк"))


def _verified_articles(research: LegalResearch, predicate: Callable[[str], bool]) -> set[str]:
    result: set[str] = set()
    for line in research.verified_claims:
        if predicate(line):
            result.update(_articles(line))
    return result


def _verified_material_articles(research: LegalResearch) -> set[str]:
    return _verified_articles(research, _is_material_line)


def _verified_penalty_articles(research: LegalResearch) -> set[str]:
    return _verified_articles(research, lambda line: _is_material_line(line) and (_penalty(line) or "353" in line))


def _verified_venue_articles(research: LegalResearch) -> set[str]:
    def venue(line: str) -> bool:
        low = line.lower()
        return _is_procedural_line(line) and any(
            x in low for x in ("месту нахождения ответчика", "место нахождения ответчика", "месту жительства ответчика", "территориальн", "подсудн")
        )
    return _verified_articles(research, venue)


def _requested_penalty(case_context: str) -> bool:
    low = (case_context or "").lower()
    return bool(
        re.search(r"взыск\w*.{0,140}(?:неустойк|пен(?:я|и|ю|ей|е)?)", low, re.S)
        or re.search(r"(?:неустойк|пен(?:я|и|ю|ей|е)?).{0,140}взыск\w*", low, re.S)
    )


def _state_duty_paid_fact(case_context: str) -> bool:
    low = (case_context or "").lower()
    if "госпошлин" not in low and "государственн" not in low:
        return False
    return bool(re.search(r"(?:уплачен|оплачен|квитанц|платежн\w* поручен).{0,100}(?:госпошлин|государственн\w* пошлин)|(?:госпошлин|государственн\w* пошлин).{0,100}(?:уплачен|оплачен|квитанц|платежн\w* поручен)", low, re.S))


def _representative_paid_fact(case_context: str) -> bool:
    low = (case_context or "").lower()
    return bool(re.search(r"(?:представител|юрист).{0,180}(?:уплачен|оплачен|платеж|тенге)|(?:уплачен|оплачен|платеж).{0,180}(?:представител|юрист)", low, re.S))


def _citation_mismatch(line: str) -> bool:
    low = (line or "").lower()
    mentioned = _articles(low.split("основан", 1)[0])
    base = re.search(r"основан\w*\s*[:\-]\s*([^\]\n]+)", low)
    if not mentioned or not base:
        return False
    grounded = set(re.findall(r"\b(\d{1,4})\b", base.group(1)))
    return bool(grounded and mentioned.isdisjoint(grounded))


def _verified_relevant_basis_lines(case_context: str, research: LegalResearch, lines: list[str]) -> list[str]:
    allowed = _verified_material_articles(research) | _verified_penalty_articles(research) | _verified_venue_articles(research)
    if not allowed:
        return []
    result: list[str] = []
    context = (case_context or "").lower()
    for line in lines:
        nums = _articles(line)
        if not nums.intersection(allowed) or _citation_mismatch(line):
            continue
        low = line.lower()
        if ("филиал" in low or "представительств" in low) and "филиал" not in context and "представительств" not in context:
            continue
        result.append(line)
    return result


def _rebuild_repaired_draft(
    case_context: str,
    research: LegalResearch,
    original: ClaimDraft,
    payload: dict[str, Any],
) -> ClaimDraft:
    """Rebuild after LLM repair without amputating deterministic calculations or verified law."""
    repaired = ClaimDraft(
        status=research.status,
        source_urls=list(research.source_urls),
        state_duty=original.state_duty,
        late_interest=original.late_interest,
        **payload,
    )
    preserved = _verified_relevant_basis_lines(case_context, research, list(original.legal_basis))
    existing_articles = set().union(*(_articles(line) for line in repaired.legal_basis)) if repaired.legal_basis else set()
    for line in preserved:
        nums = _articles(line)
        if nums and nums.issubset(existing_articles):
            continue
        repaired.legal_basis.append(line)
        existing_articles.update(nums)
    return repaired


def architecture_issues(case_context: str, research: LegalResearch, draft: ClaimDraft) -> list[str]:
    context = (case_context or "").lower()
    reasoning = "\n".join([*draft.facts, *draft.legal_basis, draft.late_interest or ""]).lower()
    prayer = "\n".join(draft.requests).lower()
    issues: list[str] = []
    arch = detect_architecture(case_context)
    legal_articles = set().union(*(_articles(line) for line in draft.legal_basis)) if draft.legal_basis else set()
    material_articles = _verified_material_articles(research)

    # The principal regression in v2: a civil claim may not survive with GPK only.
    if arch.code != "admin" and material_articles and not legal_articles.intersection(material_articles):
        issues.append("Правовое обоснование гражданского требования потеряло конкретную VERIFIED материальную норму; нормы ГПК не заменяют основание взыскания.")

    # A remedy explicitly requested by the user cannot be fixed by deletion.
    if _requested_penalty(case_context) and not _penalty(prayer):
        issues.append("Пользователь явно просит взыскать неустойку/пеню, но требование отсутствует в ПРОШУ СУД; удалять его вместо правового исправления запрещено.")
    penalty_articles = _verified_penalty_articles(research)
    if _requested_penalty(case_context) and penalty_articles and not legal_articles.intersection(penalty_articles):
        issues.append("Для явно заявленной неустойки/пени отсутствует конкретная VERIFIED материальная норма; восстанови правовое основание, а не удаляй требование.")

    # Article 353 is a separate remedy and is required only when actually claimed/verified.
    if ("353" in reasoning or "пользован" in context and "чуж" in context and "деньг" in context) and "353" in _verified_penalty_articles(research):
        if "353" not in prayer and "чужими деньгами" not in prayer and not _penalty(prayer):
            issues.append("Мотивировка содержит самостоятельное требование по статье 353, но петитум его не отражает либо этот блок должен быть исключен как не заявленный.")

    # Do not convert a calculation into a fabricated fact of payment.
    if _money(draft.state_duty) and _state_duty_paid_fact(case_context) and "госпошлин" not in prayer and "государственн" not in prayer:
        issues.append("Материалы подтверждают уплату госпошлины, но ПРОШУ СУД не содержит требования о возмещении этого судебного расхода.")
    if _money(draft.state_duty) and not _state_duty_paid_fact(case_context) and ("госпошлин" in prayer or "государственн" in prayer):
        issues.append("ПРОШУ СУД утверждает взыскание уплаченной госпошлины, хотя входные материалы подтверждают только расчет, но не факт оплаты.")
    if _representative_paid_fact(case_context) and not any(x in prayer for x in ("представител", "юрист", "юридическ")):
        issues.append("Материалы подтверждают оплаченные представительские расходы, но соответствующее требование потеряно в ПРОШУ СУД.")

    # Retrieval noise needs a factual anchor.
    if "филиал" not in context and "представительств" not in context:
        if any("филиал" in x.lower() or "представительств" in x.lower() for x in draft.legal_basis):
            issues.append("Норма о филиале/представительстве не имеет фактического якоря и должна быть удалена.")

    # If research verified the ordinary territorial venue, a repair must not drop it.
    venue_articles = _verified_venue_articles(research)
    court_is_specific = bool(draft.court and "ТРЕБУЕТ" not in draft.court.upper() and "УТОЧН" not in draft.court.upper())
    if court_is_specific and venue_articles and not legal_articles.intersection(venue_articles):
        issues.append("VERIFIED содержит норму территориальной подсудности по месту ответчика, но она потеряна из обоснования выбранного суда.")

    for line in draft.legal_basis:
        if _citation_mismatch(line):
            issues.append("Несогласованная цитата: номер статьи в тезисе не совпадает с указанным основанием.")
            break

    if any("в составе гражданского процессуального кодекса" in line.lower() for line in draft.legal_basis):
        issues.append("Удалить служебную тавтологию «в составе Гражданского процессуального кодекса»; оставить нормальную судебную ссылку на статью и ее содержание.")

    if "в зависимости от того, что наступит ранее" in reasoning or "в зависимости от того, что наступит ранее" in prayer:
        issues.append("Удалить хеджирующую формулу «в зависимости от того, что наступит ранее» и выбрать один подтвержденный предел требования.")
    return list(dict.fromkeys(issues))


_INSTALLED = False


def install_claim_exemplar_architecture() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from korgan import fast_professional_litigation as litigation
    original: Callable[..., Awaitable[ClaimDraft]] = litigation.FastProfessionalLitigationService.draft_claim
    if getattr(original, "_korgan_exemplar_architecture", False):
        _INSTALLED = True
        return

    async def wrapped(self: Any, case_context: str, research: LegalResearch, language: str = "ru") -> ClaimDraft:
        enriched = f"{case_context}\n\n---\n{architecture_block(case_context)}"
        draft = await original(self, enriched, research, language=language)
        issues = architecture_issues(case_context, research, draft)
        if not issues:
            return draft
        current = {
            "title": draft.title, "court": draft.court, "claimant": draft.claimant, "defendant": draft.defendant,
            "price_of_claim": draft.price_of_claim, "facts": draft.facts, "legal_basis": draft.legal_basis,
            "requests": draft.requests, "attachments": draft.attachments, "verification_notes": draft.verification_notes,
            **pro_payload(draft),
        }
        payload = await self._quality_repair(
            schema_name="korgan_exemplar_architecture_repair", schema=_CLAIM_SCHEMA, case_context=enriched,
            research=research, current_payload=current, issues=issues, language=language,
            document_label="исковое заявление по эталонной архитектуре 12 реальных исков",
            extra_rules=(
                "13. Исправь только указанные разрывы архитектуры, не создавая новых фактов или способов защиты.\n"
                "14. ЯВНО ЗАПРОШЕННОЕ требование нельзя исправлять удалением. Если материалы и VERIFIED его поддерживают — восстанови материальную норму, расчет и отдельный пункт ПРОШУ СУД.\n"
                "15. Для гражданского иска не оставляй только ГПК: минимум одна конкретная VERIFIED материальная норма должна обосновывать каждый самостоятельный способ защиты.\n"
                "16. Договорную пеню и статью 353 не смешивай автоматически; выбери только подтвержденное основание.\n"
                "17. Госпошлину и расходы представителя называй понесенными только при подтвержденной оплате во входных материалах. Не превращай расчет в факт оплаты.\n"
                "18. Удали процессуальные нормы без фактического якоря, но не удаляй VERIFIED норму обычной территориальной подсудности, если она обосновывает выбранный суд.\n"
                "19. Сверь номера статей в тезисах с основаниями; убери служебные подписи вида «Основание:» и тавтологию «в составе ... кодекса», сохранив саму VERIFIED норму.\n"
                "20. Сохрани факты, суммы, документы пользователя, state_duty и детерминированный расчет статьи 353 без изменений."
            ),
        )
        repaired = _rebuild_repaired_draft(case_context, research, draft, payload)
        remaining = architecture_issues(case_context, research, repaired)
        if remaining:
            repaired.status = VerificationStatus.NEEDS_VERIFICATION
            repaired.verification_notes.extend(f"EXEMPLAR_ARCHITECTURE: {x}" for x in remaining)
        return repaired

    wrapped._korgan_exemplar_architecture = True  # type: ignore[attr-defined]
    litigation.FastProfessionalLitigationService.draft_claim = wrapped
    _INSTALLED = True
