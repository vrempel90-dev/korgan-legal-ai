from __future__ import annotations

import re

from korgan.legal_types import ClaimDraft, LegalResearch

_ARTICLE_RE = re.compile(r"(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*\d+(?:-\d+)?", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"\[(?:ТРЕБУЕТ УТОЧНЕНИЯ|ТРЕБУЕТ ПРОВЕРКИ|ТРЕБУЕТ РАСЧ[ЕЁ]ТА|ТРЕБУЕТ ДОБАВИТЬ)[^\]]*\]", re.IGNORECASE)

# Every civil filing needs a source-bound substantive cause of action. These are
# the substantive acts currently supported by KORGAN's verified legal corpus;
# GPK and the Tax Code remain procedural/fee sources and cannot satisfy this gate
# by themselves.
_MATERIAL_LAW_RE = re.compile(
    r"ГК\s*РК|Гражданск\w*\s+кодекс\w*\s+Республик\w*\s+Казахстан|"
    r"защит\w*\s+прав\w*\s+потребител|"
    r"ТК\s*РК|Трудов\w*\s+кодекс\w*\s+Республик\w*\s+Казахстан",
    re.IGNORECASE,
)


def _meaningful(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and not _PLACEHOLDER_RE.search(text):
            result.append(text)
    return result


def _has_source_bound_material_law(research: LegalResearch) -> bool:
    for claim in research.verified_claims or []:
        text = str(claim or "")
        if _ARTICLE_RE.search(text) and _MATERIAL_LAW_RE.search(text) and "источник:" in text.lower():
            return True
    return False


def core_claim_release_blockers(research: LegalResearch, draft: ClaimDraft) -> list[str]:
    """Return substantive blockers that make even a preliminary Word unsafe.

    Filing-only prerequisites may still produce the existing PRELIMINARY document,
    but a claim with no executable relief or no source-bound material legal basis
    must never be delivered as if it were a usable court filing.
    """
    blockers: list[str] = []

    requests = _meaningful(list(draft.requests or []))
    if not requests:
        blockers.append("не сформирована исполнимая просительная часть")

    basis = _meaningful(list(draft.legal_basis or []))
    if not basis or not any(_ARTICLE_RE.search(item) for item in basis):
        blockers.append("в иске отсутствует конкретное материально-правовое основание")

    if not _has_source_bound_material_law(research):
        blockers.append("материально-правовая основа не подтверждена source-bound официальным источником")

    return list(dict.fromkeys(blockers))
