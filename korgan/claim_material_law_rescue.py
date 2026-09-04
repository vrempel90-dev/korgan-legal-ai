from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from korgan.claim_corpus_health import _snapshot_issue
from korgan.legal.corpus import ACT_GK_GENERAL, ACT_GK_SPECIAL, LegalCorpus, Provision
from korgan.legal.pipeline import local_corpus_enabled, open_corpus
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.provision_check import verified_claim_line

LOGGER = logging.getLogger(__name__)

_CONTRACT_DEBT_RE = re.compile(
    r"(?is)(?:договор\w*|обязательств\w*|шарт\w*|міндеттем\w*).{0,240}"
    r"(?:задолженн\w*|долг\w*|не\s+оплат\w*|просроч\w*|берешек\w*|қарыз\w*|төлеме\w*|кешіктір\w*)|"
    r"(?:задолженн\w*|долг\w*|не\s+оплат\w*|просроч\w*|берешек\w*|қарыз\w*|төлеме\w*|кешіктір\w*)"
    r".{0,240}(?:договор\w*|обязательств\w*|шарт\w*|міндеттем\w*)"
)
_EMPLOYMENT_CONTEXT_RE = re.compile(
    r"(?i)(?:трудов\w*\s+договор\w*|заработн\w*\s+плат\w*|зарплат\w*|"
    r"еңбек\s+шарт\w*|еңбекақ\w*|жалақы\w*)"
)
_SUPPLY_RE = re.compile(
    r"(?i)(?:поставк\w*|поставщик\w*|покупател\w*|товар\w*|жеткіз\w*|тауар\w*|сатып\s+алуш\w*)"
)
_PENALTY_RE = re.compile(
    r"(?i)(?:договорн\w*\s+неустойк\w*|неустойк\w*|пен[яию]\b|штраф\w*|"
    r"тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*)"
)
_CONTRACTUAL_PENALTY_CONTEXT_RE = re.compile(
    r"(?is)(?:договорн\w*\s+(?:неустойк\w*|пен[яию]\b|штраф\w*)|"
    r"(?:неустойк\w*|пен[яию]\b|штраф\w*).{0,180}(?:по|согласно|в\s+соответствии\s+с)\s+(?:услови\w*\s+)?договор\w*|"
    r"договор\w*.{0,180}(?:неустойк\w*|пен[яию]\b|штраф\w*)|"
    r"шарт\w*.{0,180}(?:тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*)|"
    r"(?:тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*).{0,180}шарт\w*)"
)
_BASIS_LABEL_RE = re.compile(r"(?i)\[\s*основание\s*:\s*([^;\]]+)")
_GENERIC_GK_ARTICLE_RE = re.compile(r"(?i)(?:ст\.?|статья)\s*(?:272|293)\b.*\bгк\b")
_PROCEDURAL_OR_FISCAL_RE = re.compile(
    r"(?i)(?:\bгпк\b|гражданск\w*\s+процессуальн\w*|\bнк\s*рк\b|налогов\w*\s+кодекс)"
)


@dataclass(frozen=True, slots=True)
class _Rule:
    name: str
    act_id: str
    query: str
    required_groups: tuple[tuple[str, ...], ...]
    preferred: tuple[str, ...] = ()


_PROPER_PERFORMANCE = _Rule(
    name="proper_performance",
    act_id=ACT_GK_GENERAL,
    query="обязательство должно исполняться надлежащим образом условия обязательства законодательство",
    required_groups=((r"обязательств",), (r"надлежащ", r"тиісінше")),
    preferred=(r"должно\s+исполня", r"услови\w*\s+обязательств"),
)
_SUPPLY_PAYMENT = _Rule(
    name="supply_payment",
    act_id=ACT_GK_SPECIAL,
    query="покупатель поставщик оплатить поставленный товар потребовать оплаты товара",
    required_groups=(
        (r"покупател", r"поставщик"),
        (r"товар", r"поставл"),
        (r"оплат", r"расчет"),
        (r"вправе\s+потребовать", r"обязан\w*\s+уплат", r"оплачивает"),
    ),
    preferred=(
        r"поставщик\w*\s+вправе\s+потребовать\s+оплат",
        r"продавец\w*\s+вправе\s+потребовать\s+оплат",
        r"покупатель\w*\s+обязан\w*\s+уплат",
        r"покупатель\w*\s+оплачивает\s+поставляем",
    ),
)
_CONTRACTUAL_PENALTY = _Rule(
    name="contractual_penalty",
    act_id=ACT_GK_GENERAL,
    query="неустойка договор денежная сумма должник обязан уплатить кредитору просрочка исполнения",
    required_groups=(
        (r"неустойк", r"пен", r"штраф"),
        (r"договор", r"обязательств"),
        (r"неисполн", r"ненадлежащ", r"просроч", r"обязан\w*\s+уплат"),
    ),
    preferred=(
        r"определенн\w*\s+(?:законодательств\w*|договор\w*)\s+денежн\w*\s+сумм",
        r"должник\w*\s+обязан\w*\s+уплат",
        r"просроч\w*\s+исполн",
    ),
)


def _text(provision: Provision) -> str:
    return f"{provision.heading}\n{provision.body}".lower().replace("ё", "е")


def _matches_rule(provision: Provision, rule: _Rule) -> bool:
    value = _text(provision)
    for group in rule.required_groups:
        if not any(re.search(pattern, value, flags=re.IGNORECASE | re.DOTALL) for pattern in group):
            return False
    return True


def _score(provision: Provision, rule: _Rule) -> int:
    value = _text(provision)
    score = 0
    for pattern in rule.preferred:
        if re.search(pattern, value, flags=re.IGNORECASE | re.DOTALL):
            score += 10
    if provision.item_no:
        score += 2
    return score


def _pick(corpus: LegalCorpus, rule: _Rule) -> Provision | None:
    candidates = [
        item
        for item in corpus.search(rule.query, act_id=rule.act_id, limit=30)
        if _matches_rule(item, rule)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (_score(item, rule), -len(item.body)))


def _already_present(research: LegalResearch, provision: Provision) -> bool:
    label = provision.label().lower()
    return any(label in str(line).lower() for line in research.verified_claims)


def _append_verified(research: LegalResearch, provision: Provision) -> bool:
    if _already_present(research, provision):
        return False
    statement = " ".join(str(provision.body or "").split()).strip()
    if not statement:
        return False
    line = verified_claim_line(statement, provision.label(), provision.body, provision.url)
    research.verified_claims.append(line)
    if provision.url and provision.url not in research.source_urls:
        research.source_urls.append(provision.url)
    return True


def _basis_labels(research: LegalResearch) -> list[str]:
    labels: list[str] = []
    for line in research.verified_claims:
        match = _BASIS_LABEL_RE.search(str(line or ""))
        if match:
            label = " ".join(match.group(1).split()).strip()
            if label:
                labels.append(label)
    return labels


def _has_specific_primary_basis(research: LegalResearch) -> bool:
    """True when research already owns a specific substantive legal basis.

    Article 272 GK is a useful civil-law fallback, not a decoration that should
    be appended to every contractual dispute.  Procedural GPK and fiscal NK
    provisions do not replace a material-law basis.  A specific statute or a
    specific Civil Code provision does, so the generic rescue must stay out.
    """
    for label in _basis_labels(research):
        if _PROCEDURAL_OR_FISCAL_RE.search(label):
            continue
        if _GENERIC_GK_ARTICLE_RE.search(label):
            continue
        return True
    return False


def _has_verified_penalty_basis(research: LegalResearch) -> bool:
    """Do not inject generic GK 293 when research already verified penalty law."""
    for line in research.verified_claims:
        value = str(line or "")
        match = _BASIS_LABEL_RE.search(value)
        if not match or _PROCEDURAL_OR_FISCAL_RE.search(match.group(1)):
            continue
        if _PENALTY_RE.search(value):
            return True
    return False


def _fresh_act_ids(corpus: LegalCorpus, rules: list[_Rule]) -> set[str]:
    fresh: set[str] = set()
    for act_id in {rule.act_id for rule in rules}:
        if _snapshot_issue(corpus, act_id, today=date.today()) is None:
            fresh.add(act_id)
        else:
            LOGGER.warning("CLAIM_MATERIAL_LAW_RESCUE stale_act=%s", act_id)
    return fresh


def _append_rule(
    corpus: LegalCorpus,
    research: LegalResearch,
    rule: _Rule,
    fresh_acts: set[str],
    added: list[str],
) -> bool:
    if rule.act_id not in fresh_acts:
        return False
    provision = _pick(corpus, rule)
    if provision is None:
        LOGGER.warning("CLAIM_MATERIAL_LAW_RESCUE no_match rule=%s", rule.name)
        return False
    if _append_verified(research, provision):
        added.append(f"{rule.name}:{provision.article_id}")
    return True


def enrich_material_law_from_corpus(case_context: str, research: LegalResearch) -> LegalResearch:
    """Rescue missing material law from the current official legal corpus.

    Specific law wins over generic law.  For a supply dispute, the specific
    supply/payment provision is tried first; Article 272 GK is used only when
    there is still no specific verified substantive basis.  The same principle
    applies to contractual penalties: Article 293 is a fallback only if research
    has not already verified a penalty-specific basis.

    Employment statutory penalties remain outside the Civil Code contractual
    penalty path altogether.
    """
    if not local_corpus_enabled():
        return research

    context = str(case_context or "")
    employment_context = bool(_EMPLOYMENT_CONTEXT_RE.search(context))
    contract_debt = bool(_CONTRACT_DEBT_RE.search(context)) and not employment_context
    supply_context = bool(contract_debt and _SUPPLY_RE.search(context))
    contractual_penalty = bool(
        not employment_context
        and _PENALTY_RE.search(context)
        and (contract_debt or _CONTRACTUAL_PENALTY_CONTEXT_RE.search(context))
    )

    candidate_rules: list[_Rule] = []
    if contract_debt:
        candidate_rules.append(_PROPER_PERFORMANCE)
        if supply_context:
            candidate_rules.append(_SUPPLY_PAYMENT)
    if contractual_penalty:
        candidate_rules.append(_CONTRACTUAL_PENALTY)
    if not candidate_rules:
        return research

    corpus = open_corpus()
    if corpus is None:
        return research

    added: list[str] = []
    try:
        fresh_acts = _fresh_act_ids(corpus, candidate_rules)
        has_specific_primary = _has_specific_primary_basis(research)

        # Specific contract-type law first.  If it is verified, do not clutter
        # the pleading with generic Article 272 merely because the dispute also
        # contains the words "договор" and "долг".
        if supply_context and not has_specific_primary:
            if _append_rule(corpus, research, _SUPPLY_PAYMENT, fresh_acts, added):
                has_specific_primary = True

        if contract_debt and not has_specific_primary:
            _append_rule(corpus, research, _PROPER_PERFORMANCE, fresh_acts, added)

        if contractual_penalty and not _has_verified_penalty_basis(research):
            _append_rule(corpus, research, _CONTRACTUAL_PENALTY, fresh_acts, added)
    except Exception:
        LOGGER.exception("CLAIM_MATERIAL_LAW_RESCUE failed; keeping source-bound research unchanged")
        return research
    finally:
        corpus.close()

    if added:
        if not research.unverified_claims:
            research.status = VerificationStatus.VERIFIED
        LOGGER.info("CLAIM_MATERIAL_LAW_RESCUE added=%s", added)
    return research
