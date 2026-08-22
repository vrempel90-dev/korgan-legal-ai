from __future__ import annotations

import re

from korgan.citation_audit import extract_references, runtime_provisions
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

# GPK and the Tax Code are procedural/fee sources. They may support filing, but
# cannot by themselves establish the substantive cause of action. These are the
# material-law act labels understood by the shared citation parser.
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


def _material_basis_references(basis: list[str]):
    references = []
    for reference in extract_references("\n".join(_meaningful(basis))):
        if reference.act in _MATERIAL_ACTS and reference not in references:
            references.append(reference)
    return references


def _has_source_bound_material_law(research: LegalResearch, basis: list[str]) -> bool:
    """Require the exact material provision used in the draft to be source-bound.

    ``runtime_provisions`` accepts only the canonical verified-claim shape with a
    usable provision quote and an official Adilet host. Matching uses act,
    article and, when present, part — an unrelated verified norm cannot promote
    a different draft citation into release-ready status.
    """
    required = _material_basis_references(basis)
    if not required:
        return False
    verified = runtime_provisions(research.verified_claims)
    return any(
        wanted.matches(record.reference)
        for wanted in required
        for record in verified
        if record.reference.act in _MATERIAL_ACTS
    )


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
