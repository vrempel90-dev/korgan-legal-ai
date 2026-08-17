"""Additive legal-release layer; existing production generators stay authoritative.

Every override calls the already deployed implementation first and only adds a
fail-closed post-check.  No intake, drafting prompt, DOCX renderer, calculation
or menu behavior is replaced here.
"""

from __future__ import annotations

import re
from typing import Any

from korgan.legal.current_law_guard import is_current_source
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.pretrial import PretrialDraft, PretrialProductionService
from korgan.request_basis_coverage import _RULES, _basis_has, _render_verified, _rule_applies
from korgan.response_types import ResponseToClaimDraft
from korgan.stable_legal_release import sanitize_research_sources


_PROCEDURAL_ONLY_RE = re.compile(
    r"(?i)\b(?:гпк\s*рк|процессуальн\w*|отзыв\w*\s+на\s+иск|срок\w*\s+представлен\w*\s+отзыв)\b"
)
_SUBSTANTIVE_OBJECTION_RE = re.compile(
    r"(?i)\b(?:долг\w*|задолженн\w*|за[её]м\w*|договор\w*|обязательств\w*|"
    r"оплат\w*|возврат\w*|неустойк\w*|пен[яию]\b|убытк\w*|ущерб\w*|"
    r"заработн\w*|зарплат\w*|отпуск\w*|потребител\w*|собственност\w*|"
    r"алимент\w*|банк\w*|кредит\w*|қарыз\w*|еңбекақ\w*|шарт\w*)\b"
)
_ARTICLE_166_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*166\b.{0,80}\bгпк\b|\bгпк\b.{0,80}(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*166\b")


def _pretrial_basis_coverage(case_context: str, draft: PretrialDraft, research: LegalResearch) -> list[str]:
    """Apply the proven claim-remedy rules to matching pre-trial demands."""
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

    draft.legal_basis = list(dict.fromkeys(basis))
    missing = list(dict.fromkeys(missing))
    if missing:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        note = "Нет отдельной VERIFIED правовой опоры для требований: " + "; ".join(missing)
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)
    return missing


def _verified_substantive_law(research: LegalResearch) -> list[str]:
    result: list[str] = []
    for line in research.verified_claims:
        text = str(line or "")
        # Art. 166 is necessary procedure for a response, but it cannot by itself
        # prove why the claimant's substantive demand should be rejected.
        if _ARTICLE_166_RE.search(text):
            continue
        if _PROCEDURAL_ONLY_RE.search(text) and not _SUBSTANTIVE_OBJECTION_RE.search(text):
            continue
        result.append(text)
    return result


def _response_basis_coverage(draft: ResponseToClaimDraft, research: LegalResearch) -> list[str]:
    objection_text = "\n".join(
        line
        for objection in draft.objections
        for line in objection.body_lines()
    )
    if not _SUBSTANTIVE_OBJECTION_RE.search(objection_text):
        return []
    if _verified_substantive_law(research):
        return []

    draft.status = VerificationStatus.NEEDS_VERIFICATION
    note = (
        "Содержательные возражения не имеют отдельной VERIFIED материально-правовой опоры; "
        "процессуальная статья об отзыве на иск сама по себе недостаточна."
    )
    if note not in draft.verification_notes:
        draft.verification_notes.append(note)
    return [note]


class AdditiveLegalGuardService(PretrialProductionService):
    """Existing KORGAN production service plus post-generation legal guards."""

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
        return sanitize_research_sources(research)

    async def draft_response_to_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ResponseToClaimDraft:
        draft = await super().draft_response_to_claim(case_context, research, language=language)  # type: ignore[misc]
        _response_basis_coverage(draft, research)
        return draft


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
        if not is_current_source(str(getattr(record, "source_url", "") or ""), article_label=label):
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
