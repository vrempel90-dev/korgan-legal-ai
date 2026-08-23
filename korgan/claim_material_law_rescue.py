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


def _append_verified(research: LegalResearch, provision: Provision) -> None:
    if _already_present(research, provision):
        return
    statement = " ".join(str(provision.body or "").split()).strip()
    if not statement:
        return
    line = verified_claim_line(statement, provision.label(), provision.body, provision.url)
    research.verified_claims.append(line)
    if provision.url and provision.url not in research.source_urls:
        research.source_urls.append(provision.url)


def enrich_material_law_from_corpus(case_context: str, research: LegalResearch) -> LegalResearch:
    """Rescue missing core material law from the fresh official Adilet snapshot.

    Contractual-penalty rescue is deliberately gated to a contractual context.
    A generic statutory ``пеня`` in an employment/tax/administrative case must
    never pull the Civil Code contractual-penalty provision into the filing.
    """
    if not local_corpus_enabled():
        return research

    context = str(case_context or "")
    contract_debt = bool(_CONTRACT_DEBT_RE.search(context))
    contractual_penalty = bool(
        _PENALTY_RE.search(context)
        and (contract_debt or _CONTRACTUAL_PENALTY_CONTEXT_RE.search(context))
    )

    rules: list[_Rule] = []
    if contract_debt:
        rules.append(_PROPER_PERFORMANCE)
        if _SUPPLY_RE.search(context):
            rules.append(_SUPPLY_PAYMENT)
    if contractual_penalty:
        rules.append(_CONTRACTUAL_PENALTY)
    if not rules:
        return research

    corpus = open_corpus()
    if corpus is None:
        return research

    added: list[str] = []
    try:
        fresh_acts: set[str] = set()
        for act_id in {rule.act_id for rule in rules}:
            if _snapshot_issue(corpus, act_id, today=date.today()) is None:
                fresh_acts.add(act_id)
            else:
                LOGGER.warning("CLAIM_MATERIAL_LAW_RESCUE stale_act=%s", act_id)

        for rule in rules:
            if rule.act_id not in fresh_acts:
                continue
            provision = _pick(corpus, rule)
            if provision is None:
                LOGGER.warning("CLAIM_MATERIAL_LAW_RESCUE no_match rule=%s", rule.name)
                continue
            before = len(research.verified_claims)
            _append_verified(research, provision)
            if len(research.verified_claims) > before:
                added.append(f"{rule.name}:{provision.article_id}")
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
