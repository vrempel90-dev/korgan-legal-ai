"""Narrow production guards for client feedback received 2026-08-25.

This module intentionally touches only document wording/research guidance. It does
not change models, payments, Telegram routing, consultation flow or generation
ownership.
"""

from __future__ import annotations

import re
from typing import Any

_SPECIAL_PART_SUFFIX = (
    "\n\nКЛИЕНТСКИЙ КОНТРОЛЬ МАТЕРИАЛЬНОГО ПРАВА:\n"
    "29. Если спор вытекает из поставки, купли-продажи, подряда, оказания услуг, аренды, займа или иного поименованного договора, обязательно проверь на Adilet применимые нормы Особенной части ГК РК. Общие нормы об обязательствах не заменяют профильную главу Особенной части.\n"
    "30. В досудебной претензии и ответе на претензию переноси профильную норму Особенной части только если она VERIFIED и действительно относится к спорному обязательству. Номер статьи по памяти запрещён."
)

_BAD_RU_OPENING_RE = re.compile(r"(?i)^\s*на\s+рассмотрев\b\s*")


def _clean_response_sentence(value: str) -> str:
    text = str(value or "").strip()
    if _BAD_RU_OPENING_RE.search(text):
        text = _BAD_RU_OPENING_RE.sub("Рассмотрев ", text, count=1)
    return text


def _sanitize_response_draft(draft: Any) -> None:
    for attr in ("claim_summary", "position", "objections", "legal_basis", "response_terms"):
        values = list(getattr(draft, attr, []) or [])
        setattr(draft, attr, [_clean_response_sentence(item) for item in values])


def install_pretrial_response_grammar_guard() -> None:
    from korgan import pretrial_response

    current = pretrial_response.normalize_pretrial_response
    if getattr(current, "_korgan_client_opening_guard", False):
        return

    def normalize_with_opening_guard(draft: Any) -> None:
        current(draft)
        _sanitize_response_draft(draft)

    normalize_with_opening_guard._korgan_client_opening_guard = True  # type: ignore[attr-defined]
    pretrial_response.normalize_pretrial_response = normalize_with_opening_guard


def install_special_part_research_guard() -> None:
    from korgan import fast_professional_litigation as litigation

    current = litigation._professional_research_prompt
    if getattr(current, "_korgan_client_special_part_20260825", False):
        return

    def prompt_with_special_part(case_context: str, *, max_chars: int, checked_on: str, **kwargs: object) -> str:
        return current(case_context, max_chars=max_chars, checked_on=checked_on, **kwargs) + _SPECIAL_PART_SUFFIX

    prompt_with_special_part._korgan_client_special_part_20260825 = True  # type: ignore[attr-defined]
    litigation._professional_research_prompt = prompt_with_special_part


def install_client_feedback_20260825() -> None:
    install_pretrial_response_grammar_guard()
    install_special_part_research_guard()
