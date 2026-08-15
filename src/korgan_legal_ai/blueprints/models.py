from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from korgan_legal_ai.domain.models import DocumentType, LegalArea, PartyRole

# Name of the procedural item that carries house-style-only citations. It is kept out of the legal
# issue list on purpose: an unavailable style quote is a presentation gap, never a verification gap.
STYLE_SUPPORT_ITEM = "style_support"


class SectionKind(StrEnum):
    """Structural slot of a legal document.

    A blueprint lists the slots a document type uses and in which order. Rendering logic lives in
    one renderer per slot, so a new document type is described by data rather than by new branches
    in the drafting engine.
    """

    ADDRESSEE = "addressee"
    PARTIES = "parties"
    TITLE = "title"
    CLAIM_PRICE = "claim_price"
    OPENING_FORMULA = "opening_formula"
    FACTS = "facts"
    POSITION = "position"
    PRETRIAL = "pretrial"
    CALCULATION = "calculation"
    TERMS = "terms"
    GROUNDS = "grounds"
    LEGAL_GROUNDS = "legal_grounds"
    CLOSING_FORMULA = "closing_formula"
    PRAYER = "prayer"
    ATTACHMENTS = "attachments"
    SIGNATURE = "signature"


class AddresseeKind(StrEnum):
    COURT = "court"
    APPEAL_COURT = "appeal_court"
    COUNTERPARTY = "counterparty"
    NONE = "none"


@dataclass(frozen=True)
class Section:
    """One structural slot plus the heading printed above it.

    An empty ``heading`` means the block is printed without a heading line, which is how the
    addressee, the party requisites and the claim price appear in the KORGAN house style.
    """

    kind: SectionKind
    heading: str = ""
    # Fixed lead-in prose for the section. It is drafting boilerplate about the document itself and
    # never states a legal conclusion, an amount or a norm — those come from verified stages only.
    intro: str = ""


@dataclass(frozen=True)
class PartyPresentation:
    """How the two sides are labelled in this document type.

    The label is presentation; the role sets are what bind a label to an actual locked party, so a
    document can never silently swap who is suing whom. A response prints the same two parties as a
    claim but is authored by the defendant, and that difference lives here rather than in the QA
    policies.
    """

    author_label: str
    opponent_label: str
    # Roles that may appear under each label. Used to match an already-locked party to its side.
    author_roles: frozenset[PartyRole]
    opponent_roles: frozenset[PartyRole]
    # The role assigned when this system creates the parties itself, as it does in the guided
    # dialogue. Matching accepts several roles; creation must pick exactly one.
    author_role: PartyRole = PartyRole.CLAIMANT
    opponent_role: PartyRole = PartyRole.DEFENDANT


@dataclass(frozen=True)
class DocumentBlueprint:
    """Declarative definition of one document type.

    Everything the pipeline needs to draft, verify, QA and export a document type is data here:
    which sections exist, how the parties are labelled, whether money is claimed, which procedural
    checks apply, and which interview questions collect the facts. Supporting a new document type
    means adding a blueprint, not editing the engine.
    """

    key: str
    document_type: DocumentType
    legal_area: LegalArea | None
    title: str
    subject: str
    addressee: AddresseeKind
    parties: PartyPresentation
    monetary: bool
    sections: tuple[Section, ...]
    summary: str
    # Transliterated stem used when the document is delivered as a file, so a lawyer can tell an
    # иск from a претензия by the attachment name alone.
    file_slug: str = "document"
    prayer_items: tuple[str, ...] = ()
    procedural_issues: tuple[str, ...] = ()
    # Norms quoted for house-style reasons only (for example the opening formula). They are
    # resolved through the same fail-closed citation gateway and are never required: an absent
    # style quote degrades presentation, it does not become a legal verification gap.
    style_norm_locators: tuple[tuple[str, str, str, str], ...] = ()
    interview_fields: tuple[str, ...] = ()
    _section_index: dict[SectionKind, Section] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "_section_index", {section.kind: section for section in self.sections}
        )

    def has_section(self, kind: SectionKind) -> bool:
        return kind in self._section_index

    def heading_for(self, kind: SectionKind) -> str:
        section = self._section_index.get(kind)
        return section.heading if section is not None else ""

    def headings(self) -> tuple[str, ...]:
        return tuple(section.heading for section in self.sections if section.heading)
