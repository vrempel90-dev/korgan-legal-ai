from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from korgan.legal.corpus import (
    ACT_GK_GENERAL,
    ACT_GK_SPECIAL,
    LegalCorpus,
    Provision,
    make_article_id,
)
from korgan.legal.pipeline import local_corpus_enabled, open_corpus
from korgan.legal_routing import detect_claim_profile
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.provision_check import verified_claim_line

LOGGER = logging.getLogger(__name__)

PROFILE_GROUNDING_PREFIX = "PROFILE_GROUNDING: "

_PENALTY_RE = re.compile(
    r"(?i)(?:договорн\w*\s+неустойк\w*|неустойк\w*|пен[яию]\b|"
    r"тұрақсыздық\s+айыб\w*|өсімпұл\w*)"
)


@dataclass(frozen=True, slots=True)
class RequiredProvision:
    act_id: str
    article_no: str
    item_no: str | None = None
    purpose: str = ""

    @property
    def article_id(self) -> str:
        return make_article_id(self.act_id, self.article_no, self.item_no)


# These are deterministic routing requirements, not legal text. The actual
# current provision body, edition and Adilet URL are always loaded from corpus.
_PROFILE_REQUIREMENTS: dict[str, tuple[RequiredProvision, ...]] = {
    "supply": (
        RequiredProvision(
            ACT_GK_SPECIAL,
            "458",
            None,
            "квалификация договора поставки",
        ),
        RequiredProvision(
            ACT_GK_SPECIAL,
            "469",
            "1",
            "обязанность покупателя оплачивать поставленные товары по договору",
        ),
        RequiredProvision(
            ACT_GK_GENERAL,
            "272",
            None,
            "надлежащее исполнение обязательства",
        ),
    ),
}


def _extra_requirements(case_context: str) -> tuple[RequiredProvision, ...]:
    if not _PENALTY_RE.search(case_context or ""):
        return ()
    return (
        RequiredProvision(
            ACT_GK_GENERAL,
            "293",
            None,
            "договорная неустойка",
        ),
    )


def _act_token(provision: Provision) -> str:
    if provision.act_id == ACT_GK_GENERAL:
        return "K940001000_"
    if provision.act_id == ACT_GK_SPECIAL:
        return "K990000409_"
    return ""


def _already_grounded(research: LegalResearch, provision: Provision) -> bool:
    article_pattern = re.compile(
        rf"(?i)(?:(?:статья|статьи|ст\.)\s*{re.escape(provision.article_no)}(?!\d)|"
        rf"(?<!\d){re.escape(provision.article_no)}-бап)"
    )
    token = _act_token(provision).casefold()
    for raw in research.verified_claims or []:
        line = str(raw or "")
        if not article_pattern.search(line):
            continue
        if token and token not in line.casefold():
            continue
        if provision.item_no:
            item_pattern = re.compile(
                rf"(?i)(?:(?:пункт|п\.)\s*{re.escape(provision.item_no)}(?!\d)|"
                rf"(?<!\d){re.escape(provision.item_no)}-тармақ)"
            )
            if not item_pattern.search(line):
                continue
        return True
    return False


def _verified_line(provision: Provision) -> str:
    own_text = " ".join(
        part.strip()
        for part in (provision.heading, provision.body)
        if str(part or "").strip()
    )
    return verified_claim_line(
        own_text,
        provision.label(),
        own_text,
        provision.url,
    )


def _mark_missing(
    research: LegalResearch,
    profile_code: str,
    requirement: RequiredProvision,
) -> None:
    detail = requirement.article_id
    if requirement.purpose:
        detail += f" ({requirement.purpose})"
    note = (
        PROFILE_GROUNDING_PREFIX
        + f"для профиля {profile_code} в текущем локальном корпусе не подтверждена обязательная норма {detail}."
    )
    if note not in research.notes:
        research.notes.append(note)
    if note not in research.unverified_claims:
        research.unverified_claims.append(note)
    research.status = VerificationStatus.NEEDS_VERIFICATION


def ground_claim_profile_from_corpus(
    case_context: str,
    research: LegalResearch,
) -> LegalResearch:
    """Add the minimum profile-specific legal backbone from the current Adilet corpus.

    This function never invents provision text. Article numbers are only routing
    keys. Every filing-facing statement is the exact current corpus heading/body
    and remains subject to the existing corpus-health and filing-accuracy gates.
    """
    profile = detect_claim_profile(case_context)
    requirements = [
        *_PROFILE_REQUIREMENTS.get(profile.code, ()),
        *_extra_requirements(case_context),
    ]
    if not requirements:
        return research
    if not local_corpus_enabled():
        # Existing filing-accuracy gates already fail closed when local grounding
        # is unavailable. Do not duplicate that user-facing error here.
        return research

    corpus: LegalCorpus | None = open_corpus()
    if corpus is None:
        return research

    added = 0
    missing = 0
    try:
        for requirement in requirements:
            provision = corpus.get(requirement.article_id)
            if provision is None:
                _mark_missing(research, profile.code, requirement)
                missing += 1
                continue
            if _already_grounded(research, provision):
                continue
            research.verified_claims.append(_verified_line(provision))
            if provision.url not in research.source_urls:
                research.source_urls.append(provision.url)
            added += 1
    except Exception as exc:
        LOGGER.exception("CLAIM_PROFILE_GROUNDING corpus failure profile=%s", profile.code)
        note = (
            PROFILE_GROUNDING_PREFIX
            + f"локальная профильная сверка не завершена: {type(exc).__name__}."
        )
        if note not in research.notes:
            research.notes.append(note)
        if note not in research.unverified_claims:
            research.unverified_claims.append(note)
        research.status = VerificationStatus.NEEDS_VERIFICATION
        missing += 1
    finally:
        corpus.close()

    LOGGER.info(
        "CLAIM_PROFILE_GROUNDING profile=%s requirements=%d added=%d missing=%d",
        profile.code,
        len(requirements),
        added,
        missing,
    )
    return research
