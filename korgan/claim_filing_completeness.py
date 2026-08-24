"""Deterministic filing-completeness checks for a Kazakhstan civil claim.

This is deliberately a release gate, not an intake questionnaire. KORGAN keeps
accepting the user's free-form facts and documents. The gate only prevents a
claim from being labelled filing-ready when mandatory Article 148 GPK details
are absent from the actual court-facing party block.
"""

from __future__ import annotations

import re

from korgan.claim_filing_accuracy import FILING_ACTION_PREFIX
from korgan.legal_types import ClaimDraft, VerificationStatus

_PLACEHOLDER_RE = re.compile(r"\[(?:ТРЕБУЕТ|НАҚТЫЛАУ|ТЕКСЕРУ)[^\]]*\]", re.IGNORECASE)
_LEGAL_ENTITY_RE = re.compile(
    r"(?:\bБИН\b|\bТОО\b|\bАО\b|\bНАО\b|\bРГП\b|\bРГКП\b|\bКГП\b|\bКГКП\b|\bКГУ\b|"
    r"\bГУ\b|товариществ\w*\s+с\s+ограниченн\w*\s+ответственност\w*|акционерн\w*\s+обществ\w*)",
    re.IGNORECASE,
)
_IP_RE = re.compile(r"(?:\bИП\b|индивидуальн\w*\s+предпринимател\w*)", re.IGNORECASE)
_IIN_RE = re.compile(r"(?:\bИИН\s*[:\-–]?\s*)?(?<!\d)\d{12}(?!\d)", re.IGNORECASE)
_BIN_RE = re.compile(r"(?:\bБИН\s*[:\-–]?\s*)\d{12}\b", re.IGNORECASE)
_DOB_RE = re.compile(
    r"(?:дата\s+рождени\w*\s*[:\-–]?\s*\d{1,2}[./-]\d{1,2}[./-]\d{4}|"
    r"\d{1,2}[./-]\d{1,2}[./-]\d{4}\s*(?:г\.?\s*р\.?|года\s+рождени\w*)|"
    r"туған\s+күні\s*[:\-–]?\s*\d{1,2}[./-]\d{1,2}[./-]\d{4})",
    re.IGNORECASE,
)
_BANK_RE = re.compile(
    r"(?:\bIBAN\b|\bИИК\b|\bБИК\b|банковск\w*\s+реквизит\w*|расчетн\w*\s+счет|"
    r"есеп\s+айырысу\s+шот\w*|банк\s+деректем\w*)",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(
    r"(?:\bадрес\b|место\s+(?:жительства|нахождения|регистрации)|мекенжай|тұрғылықты\s+жер|"
    r"\bул\.?\s+|\bулиц\w*\s+|\bпр(?:оспект|-т)\.?\s+|\bмкр\.?\s+|\bмикрорайон\w*\s+|"
    r"\bдом\s+\d|\bд\.?\s*\d|\bквартир\w*\s+\d|\bкв\.?\s*\d|"
    r"\bауыл\w*\s+|\bсело\w*\s+)",
    re.IGNORECASE,
)


def _text(values: list[str]) -> str:
    return "\n".join(str(value or "").strip() for value in values or [] if str(value or "").strip())


def _usable(text: str) -> bool:
    return bool((text or "").strip()) and not bool(_PLACEHOLDER_RE.search(text or ""))


def _is_legal_entity(text: str) -> bool:
    # An individual entrepreneur remains a physical person; the mere token ИП
    # must not switch Article 148 requirements to the legal-entity branch.
    return bool(_LEGAL_ENTITY_RE.search(text or "")) and not bool(_IP_RE.search(text or ""))


def _has_iin(text: str) -> bool:
    if not _IIN_RE.search(text or ""):
        return False
    # A labeled BIN cannot satisfy the claimant's IIN requirement.
    bare = re.sub(r"\bБИН\s*[:\-–]?\s*\d{12}\b", "", text or "", flags=re.IGNORECASE)
    return bool(_IIN_RE.search(bare))


def _add(draft: ClaimDraft, message: str) -> None:
    note = FILING_ACTION_PREFIX + message
    if note not in draft.verification_notes:
        draft.verification_notes.append(note)
    draft.status = VerificationStatus.NEEDS_VERIFICATION


def enforce_article148_party_completeness(draft: ClaimDraft) -> list[str]:
    """Return and attach missing mandatory party details from GPK Article 148.

    Defendant IIN/BIN, bank details and contacts are intentionally not made hard
    requirements because Article 148 requires them only when known to claimant.
    """
    before = set(str(item) for item in draft.verification_notes)
    claimant = _text(draft.claimant)
    defendant = _text(draft.defendant)

    if not _usable(claimant):
        _add(draft, "указать в иске сведения об истце, обязательные по статье 148 ГПК РК.")
    elif _is_legal_entity(claimant):
        if not _BIN_RE.search(claimant):
            _add(draft, "указать БИН истца-юридического лица в реквизитах иска.")
        if not _ADDRESS_RE.search(claimant):
            _add(draft, "указать место нахождения истца-юридического лица в реквизитах иска.")
        if not _BANK_RE.search(claimant):
            _add(draft, "указать банковские реквизиты истца-юридического лица в реквизитах иска.")
    else:
        if not _DOB_RE.search(claimant):
            _add(draft, "указать дату рождения истца-физического лица в реквизитах иска.")
        if not _ADDRESS_RE.search(claimant):
            _add(draft, "указать место жительства истца-физического лица в реквизитах иска.")
        if not _has_iin(claimant):
            _add(draft, "указать ИИН истца-физического лица в реквизитах иска.")

    if not _usable(defendant):
        _add(draft, "указать в иске сведения об ответчике, обязательные по статье 148 ГПК РК.")
    elif not _ADDRESS_RE.search(defendant):
        if _is_legal_entity(defendant):
            _add(draft, "указать место нахождения ответчика-юридического лица в реквизитах иска.")
        else:
            _add(draft, "указать место жительства ответчика-физического лица в реквизитах иска.")

    return [
        str(item)[len(FILING_ACTION_PREFIX):]
        for item in draft.verification_notes
        if str(item) not in before and str(item).startswith(FILING_ACTION_PREFIX)
    ]
