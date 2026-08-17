"""Shared material-law guard for every KORGAN legal document.

A procedural provision can be perfectly current and correctly cited while still
being irrelevant to the legal reason why money, performance, termination or
another substantive remedy is owed.  This module keeps that distinction
explicit without hard-coding a particular Civil Code article as the answer to
every case.
"""

from __future__ import annotations

import re

from korgan.legal_types import LegalResearch, VerificationStatus

_BASIS_RE = re.compile(r"\[основание:\s*(?P<article>.*?);", re.IGNORECASE | re.DOTALL)
_ARTICLE_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*\d+(?:-\d+)?|\d+(?:-\d+)?-бап")
_GPK_RE = re.compile(r"(?i)\b(?:гпк\s*рк|гражданск\w*\s+процессуальн\w*\s+кодекс)\b")
_ADMIN_PROCEDURE_RE = re.compile(r"(?i)\b(?:аппк\s*рк|административн\w*\s+процедурно-процессуальн\w*\s+кодекс)\b")
_COURT_DIRECTORY_RE = re.compile(r"(?i)официальн\w*\s+перечень\s+судов|verified_court")
_COST_ONLY_RE = re.compile(
    r"(?i)(?:госпошлин|государственн\w*\s+пошлин|судебн\w*\s+расход|"
    r"расход\w*\s+(?:по\s+оплате\s+)?(?:помощи\s+)?представител|"
    r"оплат\w*\s+помощ\w*\s+представител)"
)

# Signals that the document resolves the underlying private-law/employment/
# consumer/family/property obligation rather than merely a procedural step.
_SUBSTANTIVE_RE = re.compile(
    r"(?i)\b(?:долг\w*|задолженн\w*|обязательств\w*|договор\w*|шарт\w*|"
    r"оплат\w*|уплат\w*|возврат\w*|взыска\w*|неустойк\w*|пен[яию]\b|"
    r"процент\w*|убытк\w*|ущерб\w*|вред\w*|заработн\w*|зарплат\w*|"
    r"еңбекақ\w*|жалақ\w*|отпуск\w*|потребител\w*|подряд\w*|услуг\w*|"
    r"работ\w*|поставк\w*|товар\w*|за[её]м\w*|кредит\w*|алимент\w*|"
    r"собственност\w*|высел\w*|расторг\w*|прекращен\w*|исполнени\w*)\b"
)


def requires_material_law(text: str | None) -> bool:
    return bool(_SUBSTANTIVE_RE.search(str(text or "")))


def _basis_label(line: str) -> str:
    match = _BASIS_RE.search(str(line or ""))
    return match.group("article").strip() if match else str(line or "")


def is_material_law_line(line: str | None) -> bool:
    """Return True only for a filing/drafting proposition about substantive law.

    GPK/APПК and court-directory propositions are procedural by nature.  A tax
    provision is not rejected categorically because tax can itself be the
    substantive dispute; only a proposition whose content is merely state duty
    or court costs is excluded.
    """
    text = str(line or "").strip()
    if not text or not _ARTICLE_RE.search(text):
        return False
    basis = _basis_label(text)
    if _GPK_RE.search(basis) or _ADMIN_PROCEDURE_RE.search(basis):
        return False
    if _COURT_DIRECTORY_RE.search(text):
        return False
    if _COST_ONLY_RE.search(text):
        return False
    return True


def material_verified_claims(research: LegalResearch) -> list[str]:
    return [str(line) for line in research.verified_claims if is_material_law_line(str(line))]


def has_material_verified(research: LegalResearch) -> bool:
    return bool(material_verified_claims(research))


def has_material_basis(lines: list[str]) -> bool:
    return any(is_material_law_line(str(line)) for line in lines)


def merge_research(primary: LegalResearch, supplement: LegalResearch) -> LegalResearch:
    """Merge a targeted fallback pass without discarding the first pass."""
    primary.applicable_law = list(dict.fromkeys([*primary.applicable_law, *supplement.applicable_law]))
    primary.procedural_requirements = list(
        dict.fromkeys([*primary.procedural_requirements, *supplement.procedural_requirements])
    )
    primary.verified_claims = list(dict.fromkeys([*primary.verified_claims, *supplement.verified_claims]))
    primary.unverified_claims = list(dict.fromkeys([*primary.unverified_claims, *supplement.unverified_claims]))
    primary.source_urls = list(dict.fromkeys([*primary.source_urls, *supplement.source_urls]))
    primary.notes = list(dict.fromkeys([*primary.notes, *supplement.notes]))
    if primary.verified_claims and not primary.unverified_claims:
        primary.status = VerificationStatus.VERIFIED
    else:
        primary.status = VerificationStatus.NEEDS_VERIFICATION
    return primary


def mark_missing_material_law(research: LegalResearch, label: str) -> None:
    research.status = VerificationStatus.NEEDS_VERIFICATION
    note = (
        f"Не подтверждена материально-правовая основа для {label}; "
        "процессуальные нормы сами по себе не подтверждают основное требование."
    )
    if note not in research.unverified_claims:
        research.unverified_claims.append(note)
