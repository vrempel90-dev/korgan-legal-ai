"""The gate every KORGAN document passes before it reaches the user."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from korgan.citation_audit import CitationAudit, audit_citations
from korgan.provision_corpus import corpus_checked_on
from korgan.temporal_law import relationship_date_in_text
from korgan.text_integrity import IntegrityFinding, integrity_findings

LAW_CHECK_NOTE_PREFIX = "Сверьте каждую статью в разделе «Правовое обоснование»"


def law_verification_note(relationship_date: date | None = None) -> str:
    """Указание сверить нормы — с датой, на которую их следует сверять.

    Раньше здесь стояла «действующая редакция на дату подачи». Для
    процессуальных норм это верно, для материальных — нет: договор 2019 года
    исполняется по закону 2019 года (статья 4 ГК РК), и сегодняшняя редакция
    статьи к нему может не иметь отношения. Указание сверять не с той датой
    хуже отсутствия указания: оно выглядит выполненным.
    """
    checked = corpus_checked_on()
    provenance = (
        f"последняя сверка локальной базы норм KORGAN: {checked}"
        if checked
        else "общая полная сверка локальной базы норм KORGAN не проводилась"
    )
    when = (
        f"на {relationship_date.strftime('%d.%m.%Y')} — дату возникновения спорного правоотношения"
        if relationship_date is not None
        else "на дату возникновения спорного правоотношения"
    )
    return (
        f"{LAW_CHECK_NOTE_PREFIX} с редакцией, действовавшей {when}; "
        "процессуальные нормы — в редакции на дату подачи "
        f"({provenance})."
    )


@dataclass(slots=True)
class ReleaseReport:
    citations: CitationAudit
    integrity: list[IntegrityFinding] = field(default_factory=list)
    #: Дата договора, найденная в самом документе. Определяет, на какую дату
    #: сверяется редакция материальных норм.
    relationship_date: date | None = None

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
            note = law_verification_note(self.relationship_date)
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
    return ReleaseReport(
        citations=audit_citations(text, verified_claims=verified_claims),
        integrity=integrity_findings(text),
        relationship_date=relationship_date_in_text(text),
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
