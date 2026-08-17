"""Additive legal-release layer; existing production generators stay authoritative.

Every override calls the already deployed implementation first and only adds
source-bound fail-closed checks.  Intake, claim/contract drafters, DOCX renderers
and deterministic calculations stay untouched here.
"""

from __future__ import annotations

import re
from typing import Any

from korgan.legal.current_law_guard import is_current_source
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.material_law_guard import (
    has_material_basis,
    has_material_verified,
    inject_material_basis,
    mark_missing_material_law,
    material_research_context,
    merge_research,
    requires_material_law,
)
from korgan.pretrial import PretrialDraft, PretrialProductionService
from korgan.request_basis_coverage import _RULES, _basis_has, _render_verified, _rule_applies
from korgan.response_types import ResponseToClaimDraft
from korgan.stable_legal_release import sanitize_research_sources


_SUBSTANTIVE_OBJECTION_RE = re.compile(
    r"(?i)\b(?:долг\w*|задолженн\w*|за[её]м\w*|договор\w*|обязательств\w*|"
    r"оплат\w*|возврат\w*|неустойк\w*|пен[яию]\b|убытк\w*|ущерб\w*|"
    r"заработн\w*|зарплат\w*|отпуск\w*|потребител\w*|собственност\w*|"
    r"алимент\w*|банк\w*|кредит\w*|қарыз\w*|еңбекақ\w*|шарт\w*)\b"
)


def _add_note(target: Any, note: str) -> None:
    target.status = VerificationStatus.NEEDS_VERIFICATION
    notes = getattr(target, "verification_notes", None)
    if isinstance(notes, list) and note not in notes:
        notes.append(note)


def _pretrial_basis_coverage(
    case_context: str,
    draft: PretrialDraft,
    research: LegalResearch,
) -> list[str]:
    """Apply proven claim-remedy rules to matching pre-trial demands."""
    basis = list(draft.legal_basis)
    missing: list[str] = []

    for demand in draft.demands:
        demand_text = str(demand or "").strip()
        if not demand_text:
            continue
        for rule in _RULES:
            if not _rule_applies(rule, demand_text, case_context):
                continue
            if not _basis_has(rule, basis):
                for verified in research.verified_claims:
                    if not rule.basis.search(str(verified or "")):
                        continue
                    rendered = _render_verified(str(verified))
                    if rendered and rendered not in basis:
                        basis.append(rendered)
                if not _basis_has(rule, basis):
                    missing.append(rule.label)

    # If a specific remedy rule already explains the gap, do not add a second
    # generic issue.  Otherwise ensure a generic substantive demand is not
    # justified only by GPK/state-duty/representative-cost provisions.
    substantive_text = "\n".join([case_context, *draft.demands, *draft.facts])
    if not missing and requires_material_law(substantive_text) and not has_material_basis(basis):
        basis = inject_material_basis(basis, research)
        if not has_material_basis(basis):
            missing.append("материально-правовое основание основного требования")

    draft.legal_basis = list(dict.fromkeys(basis))
    missing = list(dict.fromkeys(missing))
    if missing:
        _add_note(
            draft,
            "Нет отдельной VERIFIED правовой опоры для требований: " + "; ".join(missing),
        )
    return missing


def _response_basis_coverage(
    draft: ResponseToClaimDraft,
    research: LegalResearch,
) -> list[str]:
    objection_text = "\n".join(
        line
        for objection in draft.objections
        for line in objection.body_lines()
    )
    if not _SUBSTANTIVE_OBJECTION_RE.search(objection_text):
        return []

    draft.legal_basis = inject_material_basis(list(draft.legal_basis), research)
    if has_material_basis(draft.legal_basis):
        return []

    note = (
        "Содержательные возражения не имеют отдельной VERIFIED материально-правовой опоры; "
        "процессуальная статья об отзыве на иск сама по себе недостаточна."
    )
    _add_note(draft, note)
    return [note]


class AdditiveLegalGuardService(PretrialProductionService):
    """Production service plus additive research/pre-trial/response guards."""

    async def research_case(
        self,
        case_context: str,
        language: str = "ru",
    ) -> LegalResearch:
        research = await super().research_case(case_context, language=language)
        research = sanitize_research_sources(research)

        # One targeted fallback only. It is triggered when a first pass found
        # procedure/costs but no substantive law for the underlying obligation.
        if requires_material_law(case_context) and not has_material_verified(research):
            supplement = await super().research_case(
                material_research_context(case_context, "искового заявления или досудебной претензии"),
                language=language,
            )
            supplement = sanitize_research_sources(supplement)
            research = sanitize_research_sources(merge_research(research, supplement))

        if requires_material_law(case_context) and not has_material_verified(research):
            mark_missing_material_law(research, "основного требования")
        return research

    async def draft_pretrial(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> PretrialDraft:
        draft = await super().draft_pretrial(case_context, research, language=language)
        _pretrial_basis_coverage(case_context, draft, research)
        return draft

    async def research_response_to_claim(
        self,
        case_context: str,
        language: str = "ru",
    ) -> LegalResearch:
        research = await super().research_response_to_claim(case_context, language=language)  # type: ignore[misc]
        research = sanitize_research_sources(research)
        if requires_material_law(case_context) and not has_material_verified(research):
            supplement = await super().research_response_to_claim(  # type: ignore[misc]
                material_research_context(case_context, "отзыва на иск"),
                language=language,
            )
            supplement = sanitize_research_sources(supplement)
            research = sanitize_research_sources(merge_research(research, supplement))
        if requires_material_law(case_context) and not has_material_verified(research):
            mark_missing_material_law(research, "возражений по существу иска")
        return research

    async def draft_response_to_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ResponseToClaimDraft:
        draft = await super().draft_response_to_claim(case_context, research, language=language)  # type: ignore[misc]
        _response_basis_coverage(draft, research)
        return draft

    async def research_contract(
        self,
        case_context: str,
        language: str = "ru",
    ) -> LegalResearch:
        research = await super().research_contract(case_context, language=language)  # type: ignore[misc]
        research = sanitize_research_sources(research)
        if requires_material_law(case_context) and not has_material_verified(research):
            supplement = await super().research_contract(  # type: ignore[misc]
                material_research_context(case_context, "договора"),
                language=language,
            )
            supplement = sanitize_research_sources(supplement)
            research = sanitize_research_sources(merge_research(research, supplement))
        if requires_material_law(case_context) and not has_material_verified(research):
            mark_missing_material_law(research, "юридической конструкции договора")
        return research


def install_global_current_law_guard() -> None:
    """Protect citation release for every document type without replacing it."""
    from korgan import citation_audit, provision_corpus

    if getattr(citation_audit, "_current_law_guard_installed", False):
        return

    original_runtime = citation_audit.runtime_provisions
    original_citation_lookup = citation_audit.lookup
    original_corpus_lookup = provision_corpus.lookup

    def guarded_runtime(verified_claims: list[str] | None) -> list[Any]:
        records = original_runtime(verified_claims)
        return [
            record
            for record in records
            if is_current_source(
                record.source_url,
                article_label=record.reference.label(),
            )
        ]

    def _guard_record(record: Any, act: str, article: str, part: str = "") -> Any:
        if record is None:
            return None
        label = f"статья {article} {act}"
        if part:
            label = f"пункт {part} статьи {article} {act}"
        if not is_current_source(
            str(getattr(record, "source_url", "") or ""),
            article_label=label,
        ):
            return None
        return record

    def guarded_citation_lookup(act: str, article: str, part: str = "") -> Any:
        return _guard_record(original_citation_lookup(act, article, part), act, article, part)

    def guarded_corpus_lookup(act: str, article: str, part: str = "") -> Any:
        return _guard_record(original_corpus_lookup(act, article, part), act, article, part)

    citation_audit.runtime_provisions = guarded_runtime
    citation_audit.lookup = guarded_citation_lookup
    provision_corpus.lookup = guarded_corpus_lookup
    citation_audit._current_law_guard_installed = True
