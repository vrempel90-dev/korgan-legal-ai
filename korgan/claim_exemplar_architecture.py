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
2. Каждое рассчитанное и обоснованное денежное требование обязано попасть в ПРОШУ СУД отдельным пунктом. Нельзя подробно обосновать пеню/353/расходы и потерять их в петитуме.
3. Конкретно рассчитанную госпошлину не теряй из судебных расходов. Представительские расходы включай только при наличии факта и суммы во входных материалах.
4. Процессуальная норма допускается только при фактическом якоре. Нельзя писать о филиале, представительстве, договорной подсудности, несовершеннолетнем и т.п., если этого нет в фабуле.
5. Статья в тезисе и статья в его основании должны совпадать либо связь нескольких норм прямо объясняется.
6. Для специального договора сначала профильная норма; общие нормы — только если реально нужны.
7. Не используй хедж вроде «в зависимости от того, что наступит ранее». Выбирай один подтвержденный предел требования либо не выдумывай его.
8. Перед возвратом сверка обязательна: ФАКТЫ -> ДОКАЗАТЕЛЬСТВА -> НОРМЫ -> РАСЧЕТЫ -> ПРОШУ СУД -> ПРИЛОЖЕНИЯ.
"""


def _money(value: str) -> bool:
    u = (value or "").upper()
    return bool(u and "ТРЕБУЕТ" not in u and "NEEDS" not in u and re.search(r"\d[\d\s\u00a0]*\s*(?:ТЕНГЕ|₸)", u))


def architecture_issues(case_context: str, research: LegalResearch, draft: ClaimDraft) -> list[str]:
    context = (case_context or "").lower()
    reasoning = "\n".join([*draft.facts, *draft.legal_basis, draft.late_interest or ""]).lower()
    prayer = "\n".join(draft.requests).lower()
    issues: list[str] = []

    if any(x in context for x in ("неустойк", "пеня", "пени")) and any(x in reasoning for x in ("неустойк", "пеня", "пени")) and not any(x in prayer for x in ("неустойк", "пеня", "пени")):
        issues.append("Мотивировка обосновывает неустойку/пеню, но требование отсутствует в ПРОШУ СУД.")
    if ("353" in reasoning or "чужими деньгами" in reasoning) and not ("353" in prayer or "чужими деньгами" in prayer or "неустойк" in prayer):
        issues.append("Мотивировка содержит самостоятельное денежное требование по статье 353/чужим деньгам, но петитум его не отражает либо мотивировка должна быть удалена как нерелевантная.")
    if _money(draft.state_duty) and "госпошлин" not in prayer and "государственн" not in prayer:
        issues.append("В проекте есть конкретный расчет госпошлины, но ПРОШУ СУД не содержит требования о взыскании этого судебного расхода.")

    if "филиал" not in context and "представительств" not in context:
        if any("филиал" in x.lower() or "представительств" in x.lower() for x in draft.legal_basis):
            issues.append("Норма о филиале/представительстве не имеет фактического якоря и должна быть удалена.")

    for line in draft.legal_basis:
        low = line.lower()
        mentioned = set(re.findall(r"(?:стать(?:я|и|ей)|ст\.)\s*(\d{1,4})", low))
        base = re.search(r"основан\w*\s*[:\-]\s*([^\]\n]+)", low)
        if mentioned and base:
            grounded = set(re.findall(r"\b(\d{1,4})\b", base.group(1)))
            if grounded and mentioned.isdisjoint(grounded):
                issues.append("Несогласованная цитата: номер статьи в тезисе не совпадает с указанным основанием.")
                break

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
        }
        payload = await self._quality_repair(
            schema_name="korgan_exemplar_architecture_repair", schema=_CLAIM_SCHEMA, case_context=enriched,
            research=research, current_payload=current, issues=issues, language=language,
            document_label="исковое заявление по эталонной архитектуре 12 реальных исков",
            extra_rules=(
                "13. Исправь только указанные разрывы архитектуры, не создавая новых фактов или способов защиты.\n"
                "14. Если мотивировка не поддерживает самостоятельное требование — удали нерелевантный блок; если требование явно запрошено и подтверждено — восстанови его в ПРОШУ СУД.\n"
                "15. Удали процессуальные нормы без фактического якоря. Сверь номера статей в тезисах с основаниями.\n"
                "16. Сохрани факты, суммы и документы пользователя без изменений."
            ),
        )
        repaired = ClaimDraft(status=research.status, source_urls=list(research.source_urls), **payload)
        remaining = architecture_issues(case_context, research, repaired)
        if remaining:
            repaired.status = VerificationStatus.NEEDS_VERIFICATION
            repaired.verification_notes.extend(f"EXEMPLAR_ARCHITECTURE: {x}" for x in remaining)
        return repaired

    wrapped._korgan_exemplar_architecture = True  # type: ignore[attr-defined]
    litigation.FastProfessionalLitigationService.draft_claim = wrapped
    _INSTALLED = True
