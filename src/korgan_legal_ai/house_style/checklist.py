from __future__ import annotations

import re
from dataclasses import dataclass

from korgan_legal_ai.domain.models import CalculationResult, DraftDocument
from korgan_legal_ai.house_style.rules import HouseStyleRuleSet, load_rules

# Presentation probes only. Each one asks "is the verified content laid out the KORGAN way?",
# never "is this legally correct?" — the latter belongs to Legal RAG and Final Legal QA.
_PROBES: dict[str, re.Pattern[str]] = {
    "header.court_then_parties_then_price": re.compile(r"ЦЕНА ИСКА", re.I),
    "heading.isk_with_subject": re.compile(r"ИСКОВОЕ ЗАЯВЛЕНИЕ|И\s?С\s?К\b"),
    "calc.explicit_formula": re.compile(r"РАСЧЕТ ТРЕБОВАНИЙ", re.I),
    "pretrial.factual_block": re.compile(r"ДОСУДЕБН", re.I),
    "closing.rukovodstvuyas_proshu_sud": re.compile(r"ПРОШУ|ТРЕБОВАНИ", re.I),
    "attachments.numbered_from_text": re.compile(r"ПРИЛОЖЕНИ", re.I),
}

_DUPLICATE_ROW = re.compile(r"^\s*Иные суммы:\s*0*[.,]?0*\s+\w+\s*$", re.M)


@dataclass(frozen=True)
class StyleFinding:
    rule_id: str
    title: str
    satisfied: bool
    detail: str = ""


def review_claim_presentation(
    document: DraftDocument,
    calculation: CalculationResult | None = None,
    *,
    rule_set: HouseStyleRuleSet | None = None,
) -> list[StyleFinding]:
    """Report how the drafted text lines up with the house style.

    This is advisory presentation feedback. It never edits the document, never adds a citation,
    and never changes a verification status: a style gap is a formatting observation, not a legal
    defect, and a satisfied style rule is not evidence that anything was verified.
    """
    rules = rule_set or load_rules()
    findings: list[StyleFinding] = []
    text = document.text

    for rule in rules.rules:
        probe = _PROBES.get(rule.id)
        if probe is None:
            continue
        findings.append(
            StyleFinding(
                rule_id=rule.id,
                title=rule.title,
                satisfied=bool(probe.search(text)),
            )
        )

    # The one presentation rule with a money consequence: a filler row invites a duplicate to be
    # written into it, which is how the contract sum used to be claimed twice.
    empty_other = _DUPLICATE_ROW.search(text) is not None
    findings.append(
        StyleFinding(
            rule_id="calc.no_empty_catch_all_row",
            title="Нулевая строка «Иные суммы» не печатается",
            satisfied=not empty_other,
            detail="Пустая строка-заглушка провоцирует задвоение суммы." if empty_other else "",
        )
    )

    if calculation is not None and calculation.contract_amount is not None:
        shows_derivation = "Стоимость по договору" in text and "Оплачено" in text
        findings.append(
            StyleFinding(
                rule_id="calc.debt_shown_as_derived",
                title="Долг показан как «стоимость по договору − оплачено»",
                satisfied=shows_derivation,
            )
        )

    return findings
