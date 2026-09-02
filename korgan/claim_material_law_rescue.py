from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from korgan.claim_corpus_health import _snapshot_issue
from korgan.legal.corpus import (
    ACT_CONSUMER,
    ACT_GK_GENERAL,
    ACT_GK_SPECIAL,
    LegalCorpus,
    Provision,
)
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

# Consumer claims need a narrower detector than a generic word such as
# "repair".  The personal/household side and the work/service side must both be
# visible in user facts.  This prevents consumer provisions from leaking into
# ordinary B2B construction and supply disputes.
_CONSUMER_PERSONAL_RE = re.compile(
    r"(?is)(?:потребител\w*|физическ\w*\s+лиц\w*.{0,180}(?:личн\w*|бытов\w*|квартир\w*)|"
    r"личн\w*.{0,120}бытов\w*|бытов\w*.{0,120}нужд\w*|собственн\w*.{0,80}квартир\w*|"
    r"не\s+(?:связан\w*\s+с|в\s+целях)\s+предпринимательск\w*)"
)
_CONSUMER_WORK_RE = re.compile(
    r"(?i)(?:подряд\w*|подрядчик\w*|исполнител\w*|ремонт\w*|отделочн\w*|"
    r"выполнени\w*\s+работ\w*|работ\w*.{0,60}(?:квартир|дом|ремонт)|услуг\w*)"
)
_CONSUMER_DELAY_RE = re.compile(
    r"(?is)(?:срок\w*.{0,180}(?:наруш|просроч|не\s+заверш|не\s+выполн)|"
    r"(?:наруш|просроч|не\s+заверш).{0,180}срок\w*|прекратил\w*.{0,80}работ\w*)"
)
_CONSUMER_DEFECT_RE = re.compile(
    r"(?i)(?:недостат\w*|некачествен\w*|ненадлежащ\w*\s+качеств\w*|дефект\w*|"
    r"трещин\w*|расход\w*\s+по\s+шв\w*|устранени\w*\s+недостат\w*)"
)
_PRETRIAL_RE = re.compile(r"(?i)(?:досудебн\w*\s+претензи\w*|претензи\w*.{0,120}(?:направ|получ|ответ))")
_MORAL_RE = re.compile(r"(?i)(?:моральн\w*\s+вред\w*|компенсац\w*.{0,80}моральн\w*)")


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
_CONSUMER_DELAY = _Rule(
    name="consumer_work_delay",
    act_id=ACT_CONSUMER,
    query="потребитель нарушение сроков выполнения работы исполнитель отказаться договор убытки",
    required_groups=(
        (r"потребител",),
        (r"работ", r"услуг"),
        (r"срок", r"просроч"),
        (r"отказ", r"расторг", r"убыт"),
    ),
    preferred=(r"нарушен\w*\s+срок", r"отказ\w*\s+от\s+договор", r"возмещен\w*\s+убыт"),
)
_CONSUMER_DEFECTS = _Rule(
    name="consumer_work_defects",
    act_id=ACT_CONSUMER,
    query="потребитель недостатки выполненной работы уменьшение цены устранение недостатков расторжение договора",
    required_groups=(
        (r"потребител",),
        (r"недостат", r"существенн\w*\s+недостат"),
        (r"работ", r"услуг"),
        (r"уменьшен", r"устран", r"расторг", r"отказ"),
    ),
    preferred=(r"существенн\w*\s+недостат", r"соразмерн\w*\s+уменьшен", r"расторжени\w*\s+договор"),
)
_CONSUMER_STATUTORY_PENALTY = _Rule(
    name="consumer_work_statutory_penalty",
    act_id=ACT_CONSUMER,
    query="исполнитель нарушение сроков начала окончания работы неустойка один процент каждый день просрочки",
    required_groups=(
        (r"неустойк",),
        (r"один\s+процент", r"1\s*(?:%|процент)"),
        (r"кажд\w*\s+день",),
        (r"срок",),
    ),
    preferred=(r"начал\w*\s+и\s+окончан", r"один\s+процент", r"кажд\w*\s+день"),
)
_CONSUMER_MORAL = _Rule(
    name="consumer_moral_damage",
    act_id=ACT_CONSUMER,
    query="моральный вред компенсация потребитель нарушение прав",
    required_groups=((r"моральн\w*\s+вред",), (r"компенсац",), (r"потребител", r"прав\w*\s+потребител")),
    preferred=(r"компенсац\w*\s+моральн\w*\s+вред",),
)
_CONSUMER_PRETRIAL = _Rule(
    name="consumer_pretrial_claim",
    act_id=ACT_CONSUMER,
    query="потребитель претензия письменный ответ десять календарных дней исполнитель",
    required_groups=((r"претензи",), (r"письменн\w*\s+ответ", r"мотивированн\w*\s+ответ"), (r"десят\w*\s+календарн\w*\s+дн", r"10\s+календарн\w*\s+дн")),
    preferred=(r"десят\w*\s+календарн\w*\s+дн", r"мотивированн\w*\s+ответ"),
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

    Besides ordinary contract debt, the deterministic rescue covers consumer
    work/service disputes only when personal/household use is grounded in user
    facts.  The current article number comes from the refreshed official corpus;
    this module never hardcodes an article number into the filing.

    Contractual-penalty rescue is deliberately gated to a civil contractual
    context. Generic statutory penalties, including salary-delay penalties,
    must never pull a Civil Code contractual-penalty provision into the filing.
    """
    if not local_corpus_enabled():
        return research

    context = str(case_context or "")
    employment_context = bool(_EMPLOYMENT_CONTEXT_RE.search(context))
    contract_debt = bool(_CONTRACT_DEBT_RE.search(context)) and not employment_context
    consumer_work = bool(
        not employment_context
        and _CONSUMER_PERSONAL_RE.search(context)
        and _CONSUMER_WORK_RE.search(context)
    )
    contractual_penalty = bool(
        not employment_context
        and not consumer_work
        and _PENALTY_RE.search(context)
        and (contract_debt or _CONTRACTUAL_PENALTY_CONTEXT_RE.search(context))
    )

    rules: list[_Rule] = []
    if contract_debt or consumer_work:
        rules.append(_PROPER_PERFORMANCE)
    if contract_debt and _SUPPLY_RE.search(context):
        rules.append(_SUPPLY_PAYMENT)
    if contractual_penalty:
        rules.append(_CONTRACTUAL_PENALTY)

    if consumer_work:
        if _CONSUMER_DELAY_RE.search(context):
            rules.append(_CONSUMER_DELAY)
        if _CONSUMER_DEFECT_RE.search(context):
            rules.append(_CONSUMER_DEFECTS)
        if _PENALTY_RE.search(context):
            rules.append(_CONSUMER_STATUTORY_PENALTY)
        if _MORAL_RE.search(context):
            rules.append(_CONSUMER_MORAL)
        if _PRETRIAL_RE.search(context):
            rules.append(_CONSUMER_PRETRIAL)

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
