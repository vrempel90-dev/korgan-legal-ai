from __future__ import annotations

import re
from urllib.parse import urlparse

from korgan.citation_audit import ProvisionReference, extract_references, runtime_provisions
from korgan.legal_types import ClaimDraft, LegalResearch

_PLACEHOLDER_RE = re.compile(
    r"\[(?:ТРЕБУЕТ УТОЧНЕНИЯ|ТРЕБУЕТ ПРОВЕРКИ|ТРЕБУЕТ РАСЧ[ЕЁ]ТА|ТРЕБУЕТ ДОБАВИТЬ)[^\]]*\]",
    re.IGNORECASE,
)
_EXECUTABLE_RELIEF_RE = re.compile(
    r"^\s*(?:\d+[.)]\s*)?(?:"
    r"взыскать|обязать|признать|расторгнуть|прекратить|отменить|аннулировать|"
    r"выселить|вселить|устранить|запретить|возвратить|вернуть|передать|"
    r"присудить|возложить|обратить\s+взыскание|"
    r"истребовать\s+(?:имущество|вещь)|установить\s+(?:право|обязанность|факт)"
    r")\b",
    re.IGNORECASE,
)
_CONSUMER_REFERENCE_RE = re.compile(
    r"(?:(?:част[ьияею]\w*|ч\.|пункт\w*|п\.)\s*(?P<part>\d+)\s*)?"
    r"(?:стать[ияеёю]\w*|ст\.)\s*(?P<article>\d+(?:-\d+)?)"
    r"[^.;\n]{0,140}защит\w*\s+прав\w*\s+потребител",
    re.IGNORECASE,
)
_SOURCE_URL_RE = re.compile(r"источник\s*:\s*(?P<url>https?://[^\]\s]+)", re.IGNORECASE)

# GPK and the Tax Code are procedural/fee sources. They may support filing, but
# cannot by themselves establish the substantive cause of action.
_MATERIAL_ACTS = frozenset({"ГК РК", "ТК РК", "ЗПП РК"})


def _meaningful(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and not _PLACEHOLDER_RE.search(text):
            result.append(text)
    return result


def _executable_requests(values: list[str]) -> list[str]:
    return [value for value in _meaningful(values) if _EXECUTABLE_RELIEF_RE.search(value)]


def _consumer_references(text: str) -> list[ProvisionReference]:
    refs: list[ProvisionReference] = []
    for match in _CONSUMER_REFERENCE_RE.finditer(text or ""):
        ref = ProvisionReference("ЗПП РК", match.group("article"), (match.group("part") or "").strip())
        if ref not in refs:
            refs.append(ref)
    return refs


def _material_basis_references(basis: list[str]) -> list[ProvisionReference]:
    text = "\n".join(_meaningful(basis))
    references: list[ProvisionReference] = []
    for reference in [*extract_references(text), *_consumer_references(text)]:
        if reference.act in _MATERIAL_ACTS and reference not in references:
            references.append(reference)
    return references


def _official_consumer_verified_references(verified_claims: list[str]) -> list[ProvisionReference]:
    refs: list[ProvisionReference] = []
    for line in verified_claims or []:
        if "текст нормы:" not in str(line).lower():
            continue
        source = _SOURCE_URL_RE.search(str(line))
        if source is None:
            continue
        try:
            parsed = urlparse(source.group("url").rstrip(".,;)"))
        except ValueError:
            continue
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {
            "adilet.zan.kz",
            "www.adilet.zan.kz",
        }:
            continue
        for reference in _consumer_references(str(line)):
            if reference not in refs:
                refs.append(reference)
    return refs


def _has_source_bound_material_law(research: LegalResearch, basis: list[str]) -> bool:
    """Require the exact material provision used in the draft to be source-bound.

    Shared runtime provisions accept only canonical verified-claim records with a
    usable provision quote and an official Adilet host. Consumer-law references
    use the same official-source requirement locally because the legacy shared
    citation parser does not yet classify that act. Matching is by act, article
    and, when present, part, so an unrelated verified norm cannot authorize a
    different draft citation.
    """
    required = _material_basis_references(basis)
    if not required:
        return False

    verified_refs = [
        record.reference
        for record in runtime_provisions(research.verified_claims)
        if record.reference.act in _MATERIAL_ACTS
    ]
    for reference in _official_consumer_verified_references(research.verified_claims):
        if reference not in verified_refs:
            verified_refs.append(reference)

    return any(wanted.matches(actual) for wanted in required for actual in verified_refs)


def core_claim_release_blockers(research: LegalResearch, draft: ClaimDraft) -> list[str]:
    """Return substantive blockers that make even a preliminary Word unsafe.

    Filing-only prerequisites may still produce the existing PRELIMINARY document,
    but a claim with no executable relief or no source-bound material legal basis
    must never be delivered as if it were a usable court filing.
    """
    blockers: list[str] = []

    if not _executable_requests(list(draft.requests or [])):
        blockers.append("не сформирована исполнимая просительная часть")

    basis = _meaningful(list(draft.legal_basis or []))
    if not _material_basis_references(basis):
        blockers.append("в иске отсутствует конкретное материально-правовое основание")

    if not _has_source_bound_material_law(research, basis):
        blockers.append("материально-правовая основа не подтверждена source-bound официальным источником")

    return list(dict.fromkeys(blockers))
