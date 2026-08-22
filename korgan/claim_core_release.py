from __future__ import annotations

import re
from urllib.parse import urlparse

from korgan import citation_audit
from korgan.citation_audit import ProvisionReference
from korgan.legal_types import ClaimDraft, LegalResearch
from korgan.provision_check import quote_is_usable

_PLACEHOLDER_RE = re.compile(
    r"\[(?:ТРЕБУЕТ УТОЧНЕНИЯ|ТРЕБУЕТ ПРОВЕРКИ|ТРЕБУЕТ РАСЧ[ЕЁ]ТА|ТРЕБУЕТ ДОБАВИТЬ|"
    r"НАҚТЫЛАУ ҚАЖЕТ|ТЕКСЕРУ ҚАЖЕТ|ЕСЕПТЕУ ҚАЖЕТ)[^\]]*\]",
    re.IGNORECASE,
)
# Requests are already isolated in the claim prayer field. Require a concrete
# executable court remedy somewhere in that request, while allowing ordinary
# lead-ins such as "Прошу:" / "Прошу суд:" and the Kazakh filing form used by
# the production legal bridge.
_EXECUTABLE_RELIEF_RE = re.compile(
    r"(?:"
    r"\bвзыскать\b|\bобязать\b|\bпризнать\b|\bрасторгнуть\b|\bпрекратить\b|"
    r"\bотменить\b|\bаннулировать\b|\bвыселить\b|\bвселить\b|\bустранить\b|"
    r"\bзапретить\b|\bвозвратить\b|\bвернуть\b|\bпередать\b|\bприсудить\b|"
    r"\bвозложить\b|\bобратить\s+взыскание\b|\bистребовать\s+(?:имущество|вещь)\b|"
    r"\bустановить\s+(?:право|обязанность|факт)\b|"
    r"өндіріп\s+алу|міндеттеу|тану|бұзу|тоқтату|жою|қайтару|беру|"
    r"тыйым\s+салу|өтеу"
    r")",
    re.IGNORECASE,
)
_CONSUMER_REFERENCE_RE = re.compile(
    r"(?:(?:част[ьияею]\w*|ч\.|пункт\w*|п\.)\s*(?P<part>\d+)\s*)?"
    r"(?:стать[ияеёю]\w*|ст\.)\s*(?P<article>\d+(?:-\d+)?)"
    r"[^.;\n]{0,140}защит\w*\s+прав\w*\s+потребител",
    re.IGNORECASE,
)
_VERIFIED_NORM_SOURCE_RE = re.compile(
    r"текст\s+нормы\s*:\s*[«\"](?P<text>.*?)[»\"]\s*;\s*"
    r"источник\s*:\s*(?P<url>https?://[^\]\s]+)",
    re.IGNORECASE | re.DOTALL,
)
_KK_MATERIAL_REFERENCE_RE = re.compile(
    r"(?P<act>ҚР\s+(?:АК|ЕК))\s+"
    r"(?P<article>\d+(?:-\d+)?)\s*[-–]?\s*"
    r"бап(?:ы|тың|тің|та|те|қа|ке|пен|бында|бінде|тан|тен)?"
    r"(?:ның|нің)?"
    r"(?:\s+(?P<part>\d+)\s*[-–]?\s*(?:бөлігі|бөлім|тармағы|тармақ))?",
    re.IGNORECASE,
)
_KK_MATERIAL_ACTS = {
    "қр ак": "ГК РК",
    "қр ек": "ТК РК",
}

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


def _kazakh_material_references(text: str) -> list[ProvisionReference]:
    """Parse the localized material-law forms used in Kazakh claim drafts."""
    refs: list[ProvisionReference] = []
    for match in _KK_MATERIAL_REFERENCE_RE.finditer(text or ""):
        act_key = " ".join(match.group("act").lower().split())
        act = _KK_MATERIAL_ACTS.get(act_key)
        if not act:
            continue
        ref = ProvisionReference(
            act,
            match.group("article"),
            (match.group("part") or "").strip(),
        )
        if ref not in refs:
            refs.append(ref)
    return refs


def _material_basis_references(basis: list[str]) -> list[ProvisionReference]:
    text = "\n".join(_meaningful(basis))
    references: list[ProvisionReference] = []
    # Resolve through the module at call time: install_kazakh_legal_bridge patches
    # citation_audit.extract_references with the proven bilingual parser after the
    # Russian-first production runtime has been installed. Keep the small local
    # parser as a deterministic fallback so the release gate never depends on
    # test/import order for the standard localized material-law forms.
    for reference in [
        *citation_audit.extract_references(text),
        *_consumer_references(text),
        *_kazakh_material_references(text),
    ]:
        if reference.act in _MATERIAL_ACTS and reference not in references:
            references.append(reference)
    return references


def _official_consumer_verified_references(verified_claims: list[str]) -> list[ProvisionReference]:
    refs: list[ProvisionReference] = []
    for line in verified_claims or []:
        match = _VERIFIED_NORM_SOURCE_RE.search(str(line))
        if match is None:
            continue
        provision_text = " ".join(match.group("text").split())
        if not quote_is_usable(provision_text):
            continue
        try:
            parsed = urlparse(match.group("url").rstrip(".,;)"))
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


def _required_reference_matches(wanted: ProvisionReference, actual: ProvisionReference) -> bool:
    if wanted.act != actual.act or wanted.article != actual.article:
        return False
    # If the draft relies on a particular part, article-level research is not
    # enough. The verified evidence must identify that same part explicitly.
    if wanted.part:
        return wanted.part == actual.part
    return True


def _has_source_bound_material_law(research: LegalResearch, basis: list[str]) -> bool:
    """Require the exact material provision used in the draft to be source-bound.

    Shared runtime provisions accept only canonical verified-claim records with a
    usable provision quote and an official Adilet host. Consumer-law references
    use the same official-source requirement locally because the legacy shared
    citation parser does not yet classify that act. Matching is by act, article
    and, when required by the draft, the exact part.
    """
    required = _material_basis_references(basis)
    if not required:
        return False

    verified_refs = [
        record.reference
        for record in citation_audit.runtime_provisions(research.verified_claims)
        if record.reference.act in _MATERIAL_ACTS
    ]
    for reference in _official_consumer_verified_references(research.verified_claims):
        if reference not in verified_refs:
            verified_refs.append(reference)

    return any(
        _required_reference_matches(wanted, actual)
        for wanted in required
        for actual in verified_refs
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
