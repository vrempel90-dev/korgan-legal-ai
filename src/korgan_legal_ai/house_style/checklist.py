from __future__ import annotations

import re
from dataclasses import dataclass

from korgan_legal_ai.domain.models import CalculationResult, DraftDocument
from korgan_legal_ai.house_style.rules import HouseStyleRuleSet, load_rules

# Presentation probes only. Each one asks "is the verified content laid out the KORGAN way?",
# never "is this legally correct?" — the latter belongs to Legal RAG and Final Legal QA.
#
# Some rules describe a layout the firm can always produce (a heading, a numbered attachment list).
# Others describe quoting a specific norm, and those can only be satisfied when the canonical corpus
# supplied that norm's effective wording. Reporting the second group as unsatisfied on an empty
# corpus is the correct outcome, not a defect: the alternative would be reciting law from memory.
def _title_with_subject_probe() -> re.Pattern[str]:
    """Any registered document title followed by its subject line.

    The corpus derived this rule from claims, where it reads "И С К" plus a subject. The habit is
    the same for a претензия or a жалоба; only the word changes, so the probe is built from the
    registered titles rather than hardcoding the claim's.
    """
    from korgan_legal_ai.blueprints.registry import BLUEPRINTS

    titles = sorted({blueprint.title for blueprint in BLUEPRINTS}, key=len, reverse=True)
    alternation = "|".join(re.escape(title) for title in titles)
    return re.compile(rf"(?m)^(?:{alternation}|И\s?С\s?К)\s*$\n^\S", re.UNICODE)


_PROBES: dict[str, re.Pattern[str]] = {
    "header.court_then_parties_then_price": re.compile(r"ЦЕНА ИСКА", re.I),
    "heading.isk_with_subject": _title_with_subject_probe(),
    "calc.explicit_formula": re.compile(r"РАСЧЕТ ТРЕБОВАНИЙ", re.I),
    "pretrial.factual_block": re.compile(r"ДОСУДЕБН", re.I),
    "closing.rukovodstvuyas_proshu_sud": re.compile(r"(?is)Руководствуясь.*?(ПРОШУ|ТРЕБУЮ)"),
    "attachments.numbered_from_text": re.compile(r"(?is)ПРИЛОЖЕНИ.*?^\s*1\.\s+\S", re.M),
    # The opening formula is a verbatim ГПК ст. 8 quote; it appears only when the corpus verified it.
    "opening.gpk8_verbatim": re.compile(r"(?s)«.+?»\s*\n\(.*?стать[яеи]\s*8\b", re.I),
    # The profile norm is cited right where the contractual relationship is described.
    "facts.norm_after_contract": re.compile(
        r"(?is)ПРАВОВОЕ ОБОСНОВАНИЕ.*?^-\s+.*,\s*статья\s+\d+", re.M
    ),
    "costs.representative_113": re.compile(r"(?i)представител\w*.*стать\w*\s*113"),
    "duty.state_fee_separate_demand": re.compile(
        r"(?im)^\s*\d+\.\s+.*государственн\w+\s+пошлин", re.U
    ),
    "signature.representative_ecp": re.compile(
        r"(?i)(Подписант\s*:|ЭЦП|Подпись\s*:\s*_+)"
    ),
}

# Why a rule that depends on verified law could not be satisfied. Shown as finding detail so a
# reviewer can tell "the corpus lacks this norm" apart from "the drafter forgot the house style".
_CORPUS_DEPENDENT = {
    "opening.gpk8_verbatim": "Дословная вступительная цитата печатается только при VERIFIED ст. 8 ГПК РК.",
    "facts.norm_after_contract": "Профильная норма приводится только при наличии VERIFIED-источника.",
    "costs.representative_113": "Требование о расходах на представителя приводится только при VERIFIED ст. 113 ГПК РК.",
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
        satisfied = bool(probe.search(text))
        findings.append(
            StyleFinding(
                rule_id=rule.id,
                title=rule.title,
                satisfied=satisfied,
                detail="" if satisfied else _CORPUS_DEPENDENT.get(rule.id, ""),
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
