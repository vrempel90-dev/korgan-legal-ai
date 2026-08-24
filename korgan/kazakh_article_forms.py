from __future__ import annotations

import re


def install_kazakh_article_forms() -> None:
    """Accept Kazakh article forms across the existing RU-first quality guards."""
    from korgan import claim_quality_hotfix, document_quality, professional_claim_finalizer
    from korgan import citation_audit, client_document_feedback_hotfix, kazakh_legal_bridge

    article = re.compile(
        r"(?i)(?:(?:стать[ьяиеёю]\w*|ст\.)\s*\d+(?:-\d+)?|"
        r"\b\d+(?:-\d+)?\s*[-–]?\s*ба[пб](?:ы|тың|тің|та|те|қа|ке|пен|ында|інде|ынан|інен)?\b)"
    )
    reference = re.compile(
        r"(?P<article>\d+(?:-\d+)?)\s*[-–]?\s*ба[пб](?:ы|тың|тің|та|те|қа|ке|пен|ында|інде|ынан|інен)?"
        r"(?:\s*(?:ның|нің)?\s*(?P<part>\d+)\s*[-–]?\s*(?:тармағ\w*|бөліг\w*))?",
        re.IGNORECASE,
    )

    kazakh_legal_bridge._ARTICLE_BILINGUAL = article
    kazakh_legal_bridge._KK_REFERENCE_RE = reference
    document_quality._ARTICLE_RE = article
    claim_quality_hotfix._ARTICLE_TOKEN_RE = article
    professional_claim_finalizer._ARTICLE_RE = article

    # client_document_feedback_hotfix predates the Kazakh citation bridge and
    # originally recognised only Russian «статья N ...» labels. Reuse the
    # canonical citation parser already patched by install_kazakh_legal_bridge()
    # so the material-law quality gate treats «ҚР АК 272-бабы» as the same
    # source-bound provision as «статья 272 ГК РК».
    current_basis_label = client_document_feedback_hotfix._basis_label
    if not getattr(current_basis_label, "_korgan_bilingual_citations", False):
        original_basis_label = current_basis_label

        def basis_label_bilingual(line: str) -> str:
            refs = citation_audit.extract_references(str(line or ""))
            if refs:
                return refs[0].label()
            return original_basis_label(line)

        basis_label_bilingual._korgan_bilingual_citations = True  # type: ignore[attr-defined]
        client_document_feedback_hotfix._basis_label = basis_label_bilingual

    current_basis_present = client_document_feedback_hotfix._basis_present_in_draft
    if not getattr(current_basis_present, "_korgan_bilingual_citations", False):
        original_basis_present = current_basis_present

        def basis_present_bilingual(label: str, legal_basis: list[str]) -> bool:
            target_refs = citation_audit.extract_references(str(label or ""))
            draft_refs = citation_audit.extract_references(
                "\n".join(str(item) for item in legal_basis or [])
            )
            if target_refs and draft_refs:
                if any(target.matches(candidate) for target in target_refs for candidate in draft_refs):
                    return True
            return original_basis_present(label, legal_basis)

        basis_present_bilingual._korgan_bilingual_citations = True  # type: ignore[attr-defined]
        client_document_feedback_hotfix._basis_present_in_draft = basis_present_bilingual
