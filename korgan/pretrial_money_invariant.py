"""Deterministic money invariant for pre-trial demands.

A model may phrase the business letter, but it may not silently degrade an
explicit calculable penalty into "произвести расчет пени".  The same cap-aware
calculator used by claims owns the number here as well.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from korgan.claim_money_authority import _source_principal_amount
from korgan.contractual_penalty import calc_contractual_penalty, parse_contractual_penalty_terms
from korgan.legal_calc import format_kzt
from korgan.pretrial import PretrialDraft
from korgan.universal_word_final_hardening import contractual_penalty_period_from_source
from korgan import universal_word_quality_guard as word_guard

LOGGER = logging.getLogger(__name__)

_PENALTY_RE = re.compile(r"(?i)(?:неустойк\w*|пен(?:я|и|ю|ей|е)\b|штраф\w*|өсімпұл\w*|тұрақсыздық\s+айыб\w*)")
_MONEY_RE = re.compile(r"(?i)\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:тенге|теңге|тг\b|₸)")
_CALCULATE_YOURSELF_RE = re.compile(r"(?i)(?:произвест\w*\s+расч[её]т|рассчитать\s+(?:пен|неустой)|есепте\w*)")


@dataclass(frozen=True, slots=True)
class PretrialMoneyResult:
    monetary_input: bool
    calculated: bool
    amount: int | None
    cap_reached_on: str | None
    issue: str = ""


def ensure_pretrial_money(case_context: str, draft: PretrialDraft, *, language: str = "ru") -> PretrialMoneyResult:
    explicit_penalty = bool(word_guard._source_penalty_demand_segments(case_context))
    principal = _source_principal_amount(case_context)
    terms = parse_contractual_penalty_terms(case_context)
    period = contractual_penalty_period_from_source(case_context)
    monetary_input = principal is not None or bool(_MONEY_RE.search(case_context or ""))

    if not explicit_penalty:
        LOGGER.info(
            "PIPELINE_INVARIANT I2 kind=pretrial monetary_input=%s explicit_penalty=False result=PASS",
            monetary_input,
        )
        return PretrialMoneyResult(monetary_input, False, None, None)

    missing: list[str] = []
    if principal is None:
        missing.append("точная сумма задолженности")
    if terms is None:
        missing.append("однозначная договорная ставка/предел неустойки")
    if period is None:
        missing.append("дата начала и дата окончания расчётного периода просрочки")

    if missing:
        issue = "не хватает данных для расчета договорной неустойки: " + ", ".join(missing)
        marker = "[ДАННЫЕ: " + ", ".join(missing) + "]"
        rebuilt: list[str] = []
        found = False
        for raw in draft.demands or []:
            text = str(raw).strip()
            if _PENALTY_RE.search(text):
                found = True
                if marker not in text:
                    text = _CALCULATE_YOURSELF_RE.sub("определить размер после предоставления данных", text)
                    text = text.rstrip(". ") + f" {marker}."
            rebuilt.append(text)
        if not found:
            rebuilt.append(f"Уплатить договорную неустойку {marker}.")
        draft.demands = rebuilt
        if issue not in draft.verification_notes:
            draft.verification_notes.append(issue)
        LOGGER.warning(
            "PIPELINE_INVARIANT I2 kind=pretrial explicit_penalty=True calculated=False class=NEEDS_USER_DATA issue=%s",
            issue,
        )
        return PretrialMoneyResult(monetary_input, False, None, None, issue)

    start, end = period
    result = calc_contractual_penalty(principal, terms, start, end)
    amount_text = format_kzt(result.amount)
    if language == "kk":
        amount_text = amount_text.replace(" тенге", " теңге")
        request = f"Шарттық тұрақсыздық айыбын {amount_text} мөлшерінде төлеу."
    else:
        request = f"Уплатить договорную неустойку в размере {amount_text}."

    rebuilt = []
    replaced = False
    for raw in draft.demands or []:
        text = str(raw).strip()
        if _PENALTY_RE.search(text):
            if not replaced:
                rebuilt.append(request)
                replaced = True
            continue
        rebuilt.append(text)
    if not replaced:
        rebuilt.append(request)
    draft.demands = rebuilt

    calc_line = (
        f"Расчёт договорной неустойки: {format_kzt(result.principal)} × {result.rate_percent:g}% × "
        f"{result.days} календарных дней = {format_kzt(result.amount)}."
    )
    if result.cap_amount is not None:
        calc_line += (
            f" Договорный предел {result.cap_percent:g}% составляет {format_kzt(result.cap_amount)}; "
            f"предел достигнут {result.cap_reached_on.strftime('%d.%m.%Y') if result.cap_reached_on else '[СВЕРИТЬ]'}."
        )
    if calc_line not in draft.facts:
        draft.facts.append(calc_line)

    LOGGER.info(
        "PIPELINE_INVARIANT I2 kind=pretrial explicit_penalty=True calculated=True amount=%s capped=%s cap_reached_on=%s result=PASS",
        result.amount,
        result.capped,
        result.cap_reached_on.isoformat() if result.cap_reached_on else None,
    )
    return PretrialMoneyResult(
        monetary_input,
        True,
        result.amount,
        result.cap_reached_on.isoformat() if result.cap_reached_on else None,
    )
