"""Production resilience for the final legal-document release gates.

This module does not disable legal verification. It removes two deterministic
false-positive classes that used to turn an otherwise generated Word document
into a 95% failure across claim/response/pretrial document types:

* modal wording is compared semantically (``вправе``/``может``/``имеет право``)
  instead of requiring the exact token used by the statute;
* explicit KORGAN placeholders such as ``[ТРЕБУЕТ УТОЧНЕНИЯ: ...]`` are treated
  as placeholders, not as fabricated party/address/contract facts.

Real contradictions remain blockers: a statutory right rewritten as a duty or
prohibition, a missing exclusive/conditional limitation, a fabricated amount, a
wrong article, an exact-quote mismatch, or an unsupported factual value is not
suppressed here.
"""

from __future__ import annotations

import logging
import re

from korgan import document_truth_runtime as truth
from korgan import live_article_release_runtime as live
from korgan import provision_check

LOGGER = logging.getLogger(__name__)
_INSTALLED = False

_ORIGINAL_PARAPHRASE_DEFECTS = provision_check.paraphrase_defects
_ORIGINAL_GENERAL_TRUTH = truth.general_truth_findings
_ORIGINAL_CONTRACT_TRUTH = truth.contract_truth_findings

_RIGHT_RE = re.compile(
    r"(?i)\b(?:вправе|может|могут|имеет\s+право|имеют\s+право|право\s+на|допускается|разрешено)\b"
)
_DUTY_RE = re.compile(
    r"(?i)\b(?:обязан\w*|должен\w*|надлежит|необходимо|требуется|подлежит)\b"
)
_PROHIBITION_RE = re.compile(
    r"(?i)(?:\bне\s+(?:вправе|может|могут|допускается)\b|\bзапрещ(?:ен\w*|ается)\b|\bне\s+имеет\s+права\b)"
)
_NEGATED_DUTY_RE = re.compile(r"(?i)\bне\s+(?:обязан\w*|должен\w*|требуется|подлежит)\b")
_ALTERNATIVE_RE = re.compile(r"(?i)\b(?:либо|или)\b|\bодин\s+из\b|\bпо\s+выбору\b")
_EXCLUSIVE_RE = re.compile(r"(?i)\b(?:только|исключительно|лишь)\b")
_CONDITION_RE = re.compile(
    r"(?i)\b(?:если|когда|при\s+услови\w*|в\s+случа\w*|при\s+наличи\w*|при\s+отсутстви\w*)\b"
)

# Only explicit bracketed placeholders created by KORGAN are exempted from the
# factual provenance blocker. Ordinary prose such as "адрес нужно уточнить" is
# not enough to bypass the guard.
_PLACEHOLDER_RE = re.compile(
    r"\[(?:\s*)(?:"
    r"ТРЕБУЕТ\s+УТОЧНЕНИЯ|ТРЕБУЕТСЯ\s+УТОЧНИТЬ|УТОЧНИТЬ|УКАЗАТЬ|ЗАПОЛНИТЬ|"
    r"НЕ\s+УКАЗАНО|ДАННЫЕ\s+ОТСУТСТВУЮТ|ҚОСЫМША\s+НАҚТЫЛАУ|КӨРСЕТУ|ТОЛТЫРУ"
    r")(?:\s*[:—-])?[^\]]*\]",
    re.IGNORECASE,
)


def _semantic_scope_filter(defect: str, *, claim: str, provision: str) -> bool:
    """Return True when an original defect remains a real contradiction.

    ``provision_check`` intentionally started conservative and compared scope
    markers lexically. The final live verifier now sees production prose where
    modal synonyms are normal. We retain the old defect unless the claim keeps
    the same legal modality through an accepted equivalent.
    """
    text = str(defect or "")

    if "норма формулирует право, а не обязанность" in text:
        # ``не вправе`` contains the token ``вправе`` but is a prohibition; its
        # dedicated prohibition check owns a prohibitory provision.
        if _PROHIBITION_RE.search(provision):
            return False
        # A real right may be restated as ``может``/``имеет право`` or neutral
        # descriptive wording. Turning it into a duty OR a prohibition remains
        # a hard contradiction.
        if _PROHIBITION_RE.search(claim):
            return True
        return bool(_DUTY_RE.search(claim) and not _RIGHT_RE.search(claim))

    if "норма формулирует обязанность, а не право" in text:
        # A duty is distorted when the paraphrase affirmatively weakens it into
        # discretion or prohibition. Neutral wording alone is not that change.
        if _PROHIBITION_RE.search(claim) or _NEGATED_DUTY_RE.search(claim):
            return True
        return bool(_RIGHT_RE.search(claim) and not _DUTY_RE.search(claim))

    if "норма предлагает альтернативу" in text:
        return not bool(_ALTERNATIVE_RE.search(claim))

    if "ограничение «только»" in text or "ограничение «исключительно»" in text:
        return not bool(_EXCLUSIVE_RE.search(claim))

    if "норма действует при определённом условии" in text or "норма привязана к конкретному случаю" in text:
        return not bool(_CONDITION_RE.search(claim))

    if "норма содержит запрет" in text:
        # Keep the blocker unless the paraphrase also expresses a prohibition.
        return not bool(_PROHIBITION_RE.search(claim))

    return True


def _append_modal_contradictions(defects: list[str], *, claim: str, provision: str) -> list[str]:
    """Catch contradictions that lexical overlap can hide.

    The legacy checker sees the token ``вправе`` inside ``не вправе`` and the
    token ``обязан`` inside ``не обязан``. Without this independent semantic
    pass, an affirmative statutory right/duty can therefore look lexically
    preserved even when the generated sentence states the opposite.
    """
    result = list(defects)
    provision_is_prohibition = bool(_PROHIBITION_RE.search(provision))
    provision_has_right = bool(_RIGHT_RE.search(provision)) and not provision_is_prohibition
    provision_has_duty = bool(_DUTY_RE.search(provision)) and not _NEGATED_DUTY_RE.search(provision)

    if provision_has_right and _PROHIBITION_RE.search(claim):
        finding = "пересказ меняет предусмотренное нормой право на запрет"
        if finding not in result:
            result.append(finding)

    if provision_has_duty and _NEGATED_DUTY_RE.search(claim):
        finding = "пересказ отрицает предусмотренную нормой обязанность"
        if finding not in result:
            result.append(finding)

    return result


def semantic_paraphrase_defects(statement: str, provision_text: str) -> list[str]:
    defects = _ORIGINAL_PARAPHRASE_DEFECTS(statement, provision_text)
    claim = str(statement or "")
    provision = str(provision_text or "")
    kept = [
        defect
        for defect in defects
        if _semantic_scope_filter(defect, claim=claim, provision=provision)
    ]
    kept = _append_modal_contradictions(kept, claim=claim, provision=provision)
    removed = len(defects) - len([item for item in defects if item in kept])
    if removed:
        LOGGER.info("PARAPHRASE_SCOPE_FALSE_POSITIVE_FILTERED removed=%d", removed)
    return kept


def _explicit_placeholder_finding(finding: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(str(finding or "")))


def _filter_placeholder_findings(findings: list[str]) -> list[str]:
    result: list[str] = []
    for finding in findings:
        if _explicit_placeholder_finding(finding):
            LOGGER.info("TRUTH_PLACEHOLDER_FALSE_POSITIVE_FILTERED finding=%s", finding[:240])
            continue
        result.append(finding)
    return result


def resilient_general_truth_findings(
    lines: list[str],
    *,
    case_context: str,
    verified_claims: list[str] | None,
) -> list[str]:
    return _filter_placeholder_findings(
        _ORIGINAL_GENERAL_TRUTH(
            lines,
            case_context=case_context,
            verified_claims=verified_claims,
        )
    )


def resilient_contract_truth_findings(
    lines: list[str],
    *,
    case_context: str,
    verified_claims: list[str] | None,
) -> list[str]:
    return _filter_placeholder_findings(
        _ORIGINAL_CONTRACT_TRUTH(
            lines,
            case_context=case_context,
            verified_claims=verified_claims,
        )
    )


def install_document_release_resilience_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # live_article_release_runtime imported the function directly, therefore
    # both module globals must be replaced. Tests and later callers using the
    # provision_check module receive the same semantics.
    provision_check.paraphrase_defects = semantic_paraphrase_defects  # type: ignore[assignment]
    live.paraphrase_defects = semantic_paraphrase_defects  # type: ignore[assignment]

    # _truth_common_hygiene resolves these globals on every call, so replacing
    # the module functions is sufficient without touching route ownership.
    truth.general_truth_findings = resilient_general_truth_findings  # type: ignore[assignment]
    truth.contract_truth_findings = resilient_contract_truth_findings  # type: ignore[assignment]

    _INSTALLED = True
    LOGGER.info(
        "Installed document release resilience: semantic modal scope + explicit placeholder truth handling"
    )


install_document_release_resilience_runtime()
