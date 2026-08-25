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
    r"(?i)(?:трудов\w*\s+договор\w*|заработн\w*\s+плат\w*|зарплат\w*|еңбек\s+шарт\w*|еңбекақ\w*|жалақы\w*)"
)
_SUPPLY_RE = re.compile(r"(?i)(?:поставк\w*|поставщик\w*|покупател\w*|товар\w*|жеткіз\w*|тауар\w*|сатып\s+алуш\w*)")
_PENALTY_RE = re.compile(r"(?i)(?:договорн\w*\s+неустойк\w*|неустойк\w*|пен[яию]\b|штраф\w*|тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*)")
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
    required_groups=((r"покупател", r"поставщик"), (r"товар", r"поставл"), (r"оплат", r"расчет"), (r"вправе\s+потребовать", r"обязан\w*\s+уплат", r"оплачивает")),
    preferred=(r"поставщик\w*\s+вправе\s+потребовать\s+оплат", r"продавец\w*\s+вправе\s+потребовать\s+оплат", r"покупатель\w*\s+обязан\w*\s+уплат", r"покупатель\w*\s+оплачивает\s+поставляем"),
)
_CONTRACTUAL_PENALTY = _Rule(
    name="contractual_penalty",
    act_id=ACT_GK_GENERAL,
    query="неустойка договор денежная сумма должник обязан уплатить кредитору просрочка исполнения",
    required_groups=((r"неустойк", r"пен", r"штраф"), (r"договор", r"обязательств"), (r"неисполн", r"ненадлежащ", r"просроч", r"обязан\w*\s+уплат")),
    preferred=(r"определенн\w*\s+(?:законодательств\w*|договор\w*)\s+денежн\w*\s+сумм", r"должник\w*\s+обязан\w*\s+уплат", r"просроч\w*\s+исполн"),
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
    candidates = [item for item in corpus.search(rule.query, act_id=rule.act_id, limit=30) if _matches_rule(item, rule)]
    if not candidates:
        return None
    # Stable tie-breaker is essential for I9: corpus row order may differ after
    # refresh, but the selected article may not.
    return max(candidates, key=lambda item: (_score(item, rule), -len(item.body), item.article_id))


def _already_present(research: LegalResearch, provision: Provision) -> bool:
    label = provision.label().lower()
    return any(label in str(line).lower() for line in research.verified_claims)


def _append_verified(research: LegalResearch, provision: Provision) -> str:
    if _already_present(research, provision):
        return ""
    statement = " ".join(str(provision.body or "").split()).strip()
    if not statement:
        return ""
    line = verified_claim_line(statement, provision.label(), provision.body, provision.url)
    research.verified_claims.append(line)
    if provision.url and provision.url not in research.source_urls:
        research.source_urls.append(provision.url)
    return line


def _rule_related(rule: _Rule, text: str) -> bool:
    low = str(text or "").casefold()
    if rule.name == "proper_performance":
        return "обязат" in low and ("надлежащ" in low or "исполн" in low)
    if rule.name == "supply_payment":
        return any(x in low for x in ("постав", "покупател", "товар")) and "оплат" in low
    if rule.name == "contractual_penalty":
        return bool(_PENALTY_RE.search(low))
    return False


def _rewrite_unverified_with_verified(research: LegalResearch, rule: _Rule, provision: Provision) -> list[str]:
    """Replace stale/uncertain same-role research claims, never merely append."""
    rewritten: list[str] = []
    kept: list[str] = []
    for raw in research.unverified_claims or []:
        text = str(raw)
        if _rule_related(rule, text):
            rewritten.append(f"{text[:120]} -> {provision.article_id}")
            continue
        kept.append(text)
    if rewritten:
        research.unverified_claims = kept
    return rewritten


def enrich_material_law_from_corpus(case_context: str, research: LegalResearch) -> LegalResearch:
    """Rescue missing core material law from the fresh official Adilet snapshot."""
    if not local_corpus_enabled():
        return research

    context = str(case_context or "")
    employment_context = bool(_EMPLOYMENT_CONTEXT_RE.search(context))
    contract_debt = bool(_CONTRACT_DEBT_RE.search(context)) and not employment_context
    contractual_penalty = bool(not employment_context and _PENALTY_RE.search(context) and (contract_debt or _CONTRACTUAL_PENALTY_CONTEXT_RE.search(context)))

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
    supplemented: list[str] = []
    rewritten: list[str] = []
    stale_acts: list[str] = []
    try:
        fresh_acts: set[str] = set()
        for act_id in {rule.act_id for rule in rules}:
            if _snapshot_issue(corpus, act_id, today=date.today()) is None:
                fresh_acts.add(act_id)
            else:
                stale_acts.append(act_id)
                LOGGER.warning("CLAIM_MATERIAL_LAW_RESCUE stale_act=%s", act_id)

        for rule in rules:
            if rule.act_id not in fresh_acts:
                continue
            provision = _pick(corpus, rule)
            if provision is None:
                LOGGER.warning("CLAIM_MATERIAL_LAW_RESCUE no_match rule=%s", rule.name)
                continue
            line = _append_verified(research, provision)
            if not line:
                continue
            replacements = _rewrite_unverified_with_verified(research, rule, provision)
            if replacements:
                rewritten.extend(replacements)
                added.append(f"{rule.name}:{provision.article_id}")
            else:
                # Pure supplementation is not called `added`: I6 reserves that
                # word for a true replacement and therefore every `added` has a
                # corresponding rewritten item in the same log record.
                supplemented.append(f"{rule.name}:{provision.article_id}")
    except Exception:
        LOGGER.exception("CLAIM_MATERIAL_LAW_RESCUE failed; keeping source-bound research unchanged")
        return research
    finally:
        corpus.close()

    if added or supplemented:
        if not research.unverified_claims:
            research.status = VerificationStatus.VERIFIED
        LOGGER.info(
            "CLAIM_MATERIAL_LAW_RESCUE added=%s rewritten=%s supplemented=%s stale_acts=%s I6=%s",
            added,
            rewritten,
            supplemented,
            stale_acts,
            "PASS" if (not added or rewritten) else "FAIL",
        )
    return research
