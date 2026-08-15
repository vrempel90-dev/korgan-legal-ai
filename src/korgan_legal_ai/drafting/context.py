from __future__ import annotations

from dataclasses import dataclass

from korgan_legal_ai.blueprints.models import STYLE_SUPPORT_ITEM, DocumentBlueprint
from korgan_legal_ai.domain.models import (
    CalculationResult,
    EvidenceMap,
    LockedCase,
    Party,
    ProceduralItem,
    ProceduralReport,
    ResearchCitation,
    VerificationStatus,
)

__all__ = ["STYLE_SUPPORT_ITEM", "DraftContext"]


@dataclass(frozen=True)
class DraftContext:
    """Everything a section renderer may read, and nothing it may invent.

    Renderers receive locked facts, deterministic calculations and already-verified procedural
    conclusions. They have no model access and no corpus access, so a section can only present what
    an earlier verified stage produced.
    """

    blueprint: DocumentBlueprint
    case: LockedCase
    procedural: ProceduralReport
    evidence_map: EvidenceMap
    calculation: CalculationResult

    def item(self, name: str) -> ProceduralItem | None:
        return next((item for item in self.procedural.items if item.name == name), None)

    def is_verified(self, name: str) -> bool:
        item = self.item(name)
        return item is not None and item.status == VerificationStatus.VERIFIED

    def author(self) -> Party:
        roles = self.blueprint.parties.author_roles
        return next(
            (party for party in self.case.parties if party.role in roles),
            self.case.parties[0],
        )

    def opponent(self) -> Party:
        roles = self.blueprint.parties.opponent_roles
        author = self.author()
        return next(
            (
                party
                for party in self.case.parties
                if party.role in roles and party.id != author.id
            ),
            self.case.parties[1] if self.case.parties[1].id != author.id else self.case.parties[0],
        )

    def verified_citations(self) -> list[ResearchCitation]:
        """Deduplicated VERIFIED citations from every procedural item, in report order."""
        seen: set[tuple[str | None, str | None, str | None]] = set()
        unique: list[ResearchCitation] = []
        for item in self.procedural.items:
            for citation in item.sources:
                if citation.status != VerificationStatus.VERIFIED:
                    continue
                key = (citation.law_name, citation.article, citation.source_url)
                if key in seen:
                    continue
                seen.add(key)
                unique.append(citation)
        return unique

    def style_citation(self, article_number: str) -> ResearchCitation | None:
        """Return a VERIFIED citation gathered purely for house-style presentation.

        Used for quotes the KORGAN style opens or closes with. Absence means the quote is simply
        not printed: a presentation habit never justifies reciting a norm the corpus did not confirm.
        """
        item = self.item(STYLE_SUPPORT_ITEM)
        if item is None:
            return None
        for citation in item.sources:
            if citation.status != VerificationStatus.VERIFIED or not citation.article:
                continue
            if citation.article.split(",", maxsplit=1)[0].strip() == article_number:
                return citation
        return None
