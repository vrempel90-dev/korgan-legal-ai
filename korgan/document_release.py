"""The gate every KORGAN document passes before it reaches the user.

The gate reads finished document text and is document-type agnostic. Legal
citations are checked first against source-bound provisions verified for the
current document and then against the dated local corpus. Text integrity is
always checked independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from korgan.citation_audit import CitationAudit, audit_citations
from korgan.provision_corpus import corpus_checked_on
from korgan.text_integrity import IntegrityFinding, integrity_findings

LAW_CHECK_NOTE_PREFIX = "Сверьте каждую статью в разделе «Правовое обоснование»"


def law_verification_note() -> str:
    """Conservative checklist note for documents that cite law."""
    checked = corpus_checked_on()
    provenance = (
        f"последняя сверка локальной базы норм KORGAN: {checked}"
        if checked
        else "локальная база норм KORGAN не имеет общей даты полной сверки"
    )
    return (
        f"{LAW_CHECK_NOTE_PREFIX} с действующей редакцией на дату подачи "
        f"({provenance})."
    )


@dataclass(slots=True)
class ReleaseReport:
    citations: CitationAudit
    integrity: list[IntegrityFinding] = field(default_factory=list)

    @property
    def cites_law(self) -> bool:
        return self.citations.has_citations

    @property
    def blocking(self) -> list[str]:
        blocking = [finding.as_note() for finding in self.citations.blocking]
        blocking.extend(finding.as_note() for finding in self.integrity)
        return blocking

    @property
    def released(self) -> bool:
        return not self.blocking

    def checklist(self, base_notes: list[str] | None = None) -> list[str]:
        notes = list(base_notes or [])
        if self.cites_law:
            note = law_verification_note()
            if note not in notes:
                notes.append(note)
        for finding in self.citations.notes():
            if finding not in notes:
                notes.append(finding)
        return notes


def review_document(
    text: str,
    *,
    verified_claims: list[str] | None = None,
) -> ReleaseReport:
    """Run release checks using current source-bound law plus corpus fallback."""
    return ReleaseReport(
        citations=audit_citations(text, verified_claims=verified_claims),
        integrity=integrity_findings(text),
    )


def review_lines(
    lines: list[str],
    *,
    verified_claims: list[str] | None = None,
) -> ReleaseReport:
    return review_document(
        "\n".join(line for line in lines if line),
        verified_claims=verified_claims,
    )
