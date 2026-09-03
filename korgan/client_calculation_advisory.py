from __future__ import annotations

"""Client-facing advice when a monetary point cannot be verified safely.

This module is deliberately presentation-only. It never calculates a number and
never changes the legal draft. Deterministic calculators and legal verification
remain authoritative; this layer only explains which monetary point was left
unresolved instead of pretending that an uncertain amount is exact.
"""

import re
from typing import Any

from korgan.legal_calc import NEEDS_CALCULATION_MARKER

_UNCERTAIN_RE = re.compile(
    r"(?i)(?:требует\s+(?:уточнен|провер)|нужно\s+уточн|не\s+удалось|"
    r"не\s+подтвержд|не\s+определ[её]н|нақтылау\s+қажет|расталма|анықталма|"
    + re.escape(NEEDS_CALCULATION_MARKER)
    + r")"
)
_PENALTY_RE = re.compile(r"(?i)(?:неустойк|пен[яию]\b|өсімпұл|тұрақсыздық\s+айыб)")
_DUTY_RE = re.compile(r"(?i)(?:госпошлин|государственн\w*\s+пошлин|мемлекеттік\s+баж)")
_PARTIAL_RE = re.compile(r"(?i)(?:частичн\w*\s+оплат|ішінара\s+төлем)")
_DUE_DATE_RE = re.compile(r"(?i)(?:дат\w*\s+(?:начала\s+)?просроч|срок\w*\s+исполн|мерзім)")
_RATE_RE = re.compile(r"(?i)(?:базов\w*\s+ставк|ставк\w*|мөлшерлем)")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _reason_from_penalty_text(text: str) -> str:
    for marker in ("Требует уточнения:", "требует уточнения:", "Нақтылау қажет:", "нақтылау қажет:"):
        if marker in text:
            reason = text.split(marker, 1)[1].strip().rstrip(".")
            if reason:
                return reason
    return ""


def _ru_item(text: str) -> str:
    if _DUTY_RE.search(text):
        return "Госпошлина: уточнить размер государственной пошлины или подтвердить основание льготы."
    if _PENALTY_RE.search(text):
        reason = _reason_from_penalty_text(text)
        if reason:
            return f"Неустойка: {reason.rstrip('.')}."
        if _PARTIAL_RE.search(text):
            return "Неустойка: уточнить дату и сумму частичной оплаты."
        if _DUE_DATE_RE.search(text):
            return "Неустойка: уточнить дату начала просрочки или срок исполнения обязательства."
        if _RATE_RE.search(text):
            return "Неустойка: подтвердить применимую ставку и период расчёта."
        return "Неустойка: уточнить правовое основание и исходные данные для точного расчёта."
    return "Расчёт: уточнить исходные данные, которые система не смогла подтвердить автоматически."


def _kk_item(text: str) -> str:
    if _DUTY_RE.search(text):
        return "Мемлекеттік баж: баж мөлшерін немесе жеңілдік негізін нақтылау қажет."
    if _PENALTY_RE.search(text):
        if _PARTIAL_RE.search(text):
            return "Тұрақсыздық айыбы: ішінара төлемнің күні мен сомасын нақтылау қажет."
        if _DUE_DATE_RE.search(text):
            return "Тұрақсыздық айыбы: мерзімнің басталу күнін немесе міндеттемені орындау мерзімін нақтылау қажет."
        if _RATE_RE.search(text):
            return "Тұрақсыздық айыбы: қолданылатын мөлшерлеме мен есептеу кезеңін растау қажет."
        return "Тұрақсыздық айыбы: нақты есептеу үшін құқықтық негіз бен бастапқы деректерді нақтылау қажет."
    return "Есептеу: жүйе автоматты түрде растай алмаған бастапқы деректерді нақтылау қажет."


def unresolved_calculation_items(draft: Any, *, language: str = "ru") -> list[str]:
    """Return only unresolved monetary items that are safe to show to a client."""
    candidates: list[str] = []
    for value in (
        getattr(draft, "late_interest", ""),
        getattr(draft, "state_duty", ""),
    ):
        text = _clean(value)
        if text:
            candidates.append(text)
    for value in list(getattr(draft, "calculation", []) or []):
        text = _clean(value)
        if text:
            candidates.append(text)
    for value in list(getattr(draft, "verification_notes", []) or []):
        text = _clean(value)
        if text:
            candidates.append(text)

    items: list[str] = []
    for text in candidates:
        if not _UNCERTAIN_RE.search(text):
            continue
        if not (_PENALTY_RE.search(text) or _DUTY_RE.search(text) or NEEDS_CALCULATION_MARKER in text):
            continue
        item = _kk_item(text) if language == "kk" else _ru_item(text)
        if item not in items:
            items.append(item)
    return items[:6]


def build_calculation_advisory(draft: Any, *, language: str = "ru") -> str:
    """Build a post-generation message, or an empty string when nothing is unresolved."""
    items = unresolved_calculation_items(draft, language=language)
    if not items:
        return ""
    bullets = "\n".join(f"• {item}" for item in items)
    if language == "kk":
        return (
            "⚠️ Кейбір есептеулерді дәл мән ретінде растау мүмкін болмады. "
            "KORGAN расталмаған сомаларды нақты деп көрсетпейді.\n\n"
            f"Нақтылау қажет:\n{bullets}\n\n"
            "Осы тармақтар бойынша құжатты бермес бұрын KORGAN заңгеріне жүгінуге кеңес беремін. "
            "Заңгер бастапқы деректерді тексеріп, қажет болса есеп пен құжатты түзетеді."
        )
    return (
        "⚠️ Некоторые расчёты не удалось подтвердить как точные. "
        "KORGAN не подставляет неподтверждённые суммы как достоверные.\n\n"
        f"Нужно уточнить:\n{bullets}\n\n"
        "По этим пунктам перед подачей документа советую обратиться к юристу KORGAN. "
        "Юрист проверит исходные данные и при необходимости скорректирует расчёт и документ."
    )
