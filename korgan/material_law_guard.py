"""Shared material-law guard for KORGAN legal documents.

A procedural provision can be current and correctly cited while still saying
nothing about why the principal debt, refund, termination, penalty or other
substantive remedy is owed.  This module keeps that distinction explicit and
never guesses an article: material propositions must already be source-bound
VERIFIED research.
"""

from __future__ import annotations

import re

from korgan.legal_types import LegalResearch, VerificationStatus

_BASIS_RE = re.compile(r"\[основание:\s*(?P<article>.*?);", re.IGNORECASE | re.DOTALL)
_VERIFIED_RE = re.compile(
    r"^(?P<statement>.*?)\s*\[основание:\s*(?P<article>.*?);\s*текст\s+нормы:",
    re.IGNORECASE | re.DOTALL,
)
_ARTICLE_RE = re.compile(
    r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*\d+(?:-\d+)?|\d+(?:-\d+)?-бап"
)
_GPK_RE = re.compile(
    r"(?i)\b(?:гпк\s*рк|гражданск\w*\s+процессуальн\w*\s+кодекс)\b"
)
_ADMIN_PROCEDURE_RE = re.compile(
    r"(?i)\b(?:аппк\s*рк|административн\w*\s+процедурно-процессуальн\w*\s+кодекс)\b"
)
_COURT_DIRECTORY_RE = re.compile(
    r"(?i)официальн\w*\s+перечень\s+судов|verified_court"
)
_COST_ONLY_RE = re.compile(
    r"(?i)(?:госпошлин|государственн\w*\s+пошлин|судебн\w*\s+расход|"
    r"расход\w*\s+(?:по\s+оплате\s+)?(?:помощи\s+)?представител|"
    r"оплат\w*\s+помощ\w*\s+представител)"
)
_SUBSTANTIVE_RE = re.compile(
    r"(?i)\b(?:долг\w*|задолженн\w*|обязательств\w*|договор\w*|шарт\w*|"
    r"оплат\w*|уплат\w*|возврат\w*|взыска\w*|неустойк\w*|пен[яию]\b|"
    r"процент\w*|убытк\w*|ущерб\w*|вред\w*|заработн\w*|зарплат\w*|"
    r"еңбекақ\w*|жалақ\w*|отпуск\w*|потребител\w*|подряд\w*|услуг\w*|"
    r"работ\w*|поставк\w*|товар\w*|за[её]м\w*|кредит\w*|алимент\w*|"
    r"собственност\w*|высел\w*|расторг\w*|прекращен\w*|исполнени\w*)\b"
)


def requires_material_law(text: str | None) -> bool:
    """Whether the matter contains a substantive private/employment/etc. issue."""
    return bool(_SUBSTANTIVE_RE.search(str(text or "")))


def _basis_label(line: str) -> str:
    match = _BASIS_RE.search(str(line or ""))
    return match.group("article").strip() if match else str(line or "")


def is_material_law_line(line: str | None) -> bool:
    """True for a source-bound proposition supporting substantive rights.

    GPK/APПК, court-directory propositions and propositions dealing only with
    state duty or representative/court costs do not prove the underlying debt
    or other principal remedy.
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


def render_material_claim(line: str) -> str | None:
    """Turn a VERIFIED research record into client-facing legal-basis prose."""
    match = _VERIFIED_RE.search(str(line or ""))
    if not match:
        return None
    statement = " ".join(match.group("statement").split()).strip(" .")
    article = " ".join(match.group("article").split()).strip(" .")
    if not statement or not article or not _ARTICLE_RE.search(article):
        return None
    return f"{statement}. Правовое основание: {article}."


def inject_material_basis(
    lines: list[str],
    research: LegalResearch,
    *,
    max_items: int = 4,
) -> list[str]:
    """Prepend material VERIFIED law when the draft contains only procedure.

    Existing material basis is left untouched.  Nothing is invented: only
    research records that survived the source/provision gates may be inserted.
    """
    current = [str(line).strip() for line in lines if str(line).strip()]
    if has_material_basis(current):
        return current

    additions: list[str] = []
    for verified in material_verified_claims(research):
        rendered = render_material_claim(verified)
        if rendered and rendered not in additions:
            additions.append(rendered)
        if len(additions) >= max_items:
            break
    return list(dict.fromkeys([*additions, *current]))


def merge_research(primary: LegalResearch, supplement: LegalResearch) -> LegalResearch:
    """Merge one targeted fallback research pass without losing the first pass."""
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
        "процессуальные нормы и судебные расходы сами по себе не подтверждают основное требование."
    )
    if note not in research.unverified_claims:
        research.unverified_claims.append(note)


def material_research_context(case_context: str, document_label: str) -> str:
    """Append a research-only instruction; it is explicitly not a case fact."""
    return (
        f"{case_context}\n\n---\n\n"
        "ВНУТРЕННЯЯ ЗАДАЧА ЮРИДИЧЕСКОГО ИССЛЕДОВАНИЯ — НЕ ФАКТ ДЕЛА:\n"
        f"Для {document_label} отдельно найди действующую материально-правовую основу ОСНОВНОГО требования/возражения. "
        "Сначала квалифицируй правоотношение по фактам (например: подряд, услуги, поставка, заем, потребительское, трудовое, семейное, вещное и т.п.), "
        "затем проверь применимые нормы ГК РК и специальные нормативные акты по официальному текущему источнику. "
        "ГПК, подсудность, госпошлина и расходы представителя относятся к процессу и НЕ считаются правовой опорой задолженности, возврата денег, "
        "исполнения/прекращения договора, неустойки, убытков либо иного основного материального требования. "
        "Не придумывай статью: если точная материальная норма не подтверждена source-bound, оставь вопрос непроверенным."
    )
