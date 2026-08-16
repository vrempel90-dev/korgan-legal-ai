"""The gate every KORGAN document passes before it reaches the user.

One entry point, one set of checks, all eight document types. Placing the checks
here rather than inside a drafting prompt is the point: a rule that lives in a
prompt is applied as often as the model remembers to apply it, and the citation
defects showed up *within* a single document — some citations checked, others
not.

The gate reads the finished text, so it does not care which pipeline produced
it:

* every provision reference is re-verified individually (korgan.citation_audit);
* the text is checked for damage from truncation or re-gluing
  (korgan.text_integrity);
* the user-facing checklist is assembled here, so a document that cites law can
  never reach the user without the instruction to re-check that law.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from korgan.citation_audit import CitationAudit, audit_citations
from korgan.provision_corpus import corpus_checked_on
from korgan.text_integrity import IntegrityFinding, integrity_findings

LAW_CHECK_NOTE_PREFIX = "Сверьте каждую статью в разделе «Правовое обоснование»"


def law_verification_note() -> str:
    """The checklist item that must appear whenever a document cites law."""
    checked = corpus_checked_on()
    provenance = (
        f"последняя сверка базы норм KORGAN: {checked}"
        if checked
        else "сверка базы норм KORGAN с официальным источником не проводилась"
    )
    return (
        f"{LAW_CHECK_NOTE_PREFIX} с действующей редакцией кодекса на дату подачи — "
        f"формулировки норм могли измениться ({provenance})."
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
        """Defects that must stop the document, not merely annotate it."""
        blocking = [finding.as_note() for finding in self.citations.blocking]
        blocking.extend(finding.as_note() for finding in self.integrity)
        return blocking

    @property
    def released(self) -> bool:
        return not self.blocking

    def checklist(self, base_notes: list[str] | None = None) -> list[str]:
        """The user-facing «что проверить перед подачей» list.

        The law-verification item is not conditional on how well verification
        went: a checklist that omits it reads as "the law was checked", which is
        exactly the false sense of completeness to avoid.
        """
        notes = list(base_notes or [])
        if self.cites_law:
            note = law_verification_note()
            if note not in notes:
                notes.append(note)
        for finding in self.citations.notes():
            if finding not in notes:
                notes.append(finding)
        return notes


def review_document(text: str) -> ReleaseReport:
    """Run the release gate over a finished document's text."""
    return ReleaseReport(citations=audit_citations(text), integrity=integrity_findings(text))


def review_lines(lines: list[str]) -> ReleaseReport:
    return review_document("\n".join(line for line in lines if line))
