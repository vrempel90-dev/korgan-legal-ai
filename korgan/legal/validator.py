"""Citation validator: no provision reaches a document unless the corpus has it.

The model is given a set of provisions found for the case and must answer in
blocks — which provision, what it establishes, how it ties to the facts — rather
than in prose. That shape is what makes validation possible at all: a block
names an ``article_id``, and Python can check whether that id exists in the
corpus and whether it was among the provisions actually offered.

A block failing either check does not reach the document. It is replaced by a
visible marker, because a claim that silently loses its legal ground reads as
finished when it is not.

Structured output is not a guarantee either — the model can satisfy the schema
and still write «согласно статье 715 ГК РК» inside a thesis. The final text is
therefore scanned for article references and compared against what was
validated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from korgan.legal.corpus import LegalCorpus, Provision

LAWYER_REVIEW_MARKER = "[ТРЕБУЕТ ПРОВЕРКИ ЮРИСТОМ]"

# JSON Schema for the Responses API: legal basis as blocks, never as free prose.
LEGAL_BASIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "legal_basis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "string"},
                    "thesis": {"type": "string"},
                    "link_to_facts": {"type": "string"},
                },
                "required": ["article_id", "thesis", "link_to_facts"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["legal_basis"],
    "additionalProperties": False,
}

REASON_UNKNOWN_ID = "article_id отсутствует в корпусе норм"
REASON_NOT_OFFERED = "article_id не входит в набор норм, переданный модели"
REASON_EMPTY_THESIS = "блок без тезиса"
REASON_MALFORMED = "блок не содержит article_id"

# «статья 353», «ст. 715», «статьями 715 и 722», «п. 2 ст. 621».
_CITATION = re.compile(
    r"(?:стат(?:ья|ьи|ье|ьей|ьям|ьями|ей)|ст\.)\s*(\d+(?:-\d+)?)"
    r"((?:\s*(?:,|и)\s*\d+(?:-\d+)?)*)",
    re.IGNORECASE,
)
_EXTRA_NUMBER = re.compile(r"\d+(?:-\d+)?")


@dataclass(frozen=True, slots=True)
class ValidatedBlock:
    article_id: str
    thesis: str
    link_to_facts: str
    provision: Provision

    def render(self) -> str:
        """Court-ready sentence: what the provision says, then why it applies."""
        # «со ст.», не «с ст.» — стечение согласных.
        parts = [f"В соответствии со {self.provision.label()} {self.thesis.strip().rstrip('.')}."]
        link = self.link_to_facts.strip()
        if link:
            parts.append(link if link.endswith(".") else f"{link}.")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class RejectedBlock:
    article_id: str
    reason: str

    def render(self) -> str:
        return f"{LAWYER_REVIEW_MARKER} правовое основание не подтверждено корпусом норм: {self.reason}."


@dataclass(slots=True)
class ValidationResult:
    accepted: list[ValidatedBlock] = field(default_factory=list)
    rejected: list[RejectedBlock] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.rejected

    def validated_articles(self) -> set[str]:
        """Article numbers the document is allowed to name."""
        return {block.provision.article_no for block in self.accepted}

    def legal_basis_lines(self) -> list[str]:
        """Lines for the document: accepted blocks, plus a marker for each rejection."""
        lines = [block.render() for block in self.accepted]
        lines.extend(block.render() for block in self.rejected)
        return lines

    def rejection_notes(self) -> list[str]:
        return [
            f"Правовое основание {block.article_id} отклонено: {block.reason}."
            for block in self.rejected
        ]


def validate_blocks(
    blocks: list[dict[str, Any]],
    offered_ids: set[str] | list[str],
    corpus: LegalCorpus,
) -> ValidationResult:
    """Keep only blocks whose provision exists and was offered for this case."""
    offered = set(offered_ids)
    result = ValidationResult()

    for block in blocks:
        article_id = str(block.get("article_id", "")).strip()
        thesis = str(block.get("thesis", "")).strip()

        if not article_id:
            result.rejected.append(RejectedBlock(article_id="(пусто)", reason=REASON_MALFORMED))
            continue
        if article_id not in offered:
            result.rejected.append(RejectedBlock(article_id=article_id, reason=REASON_NOT_OFFERED))
            continue

        provision = corpus.get(article_id)
        if provision is None:
            result.rejected.append(RejectedBlock(article_id=article_id, reason=REASON_UNKNOWN_ID))
            continue
        if not thesis:
            result.rejected.append(RejectedBlock(article_id=article_id, reason=REASON_EMPTY_THESIS))
            continue

        result.accepted.append(
            ValidatedBlock(
                article_id=article_id,
                thesis=thesis,
                link_to_facts=str(block.get("link_to_facts", "")).strip(),
                provision=provision,
            )
        )

    return result


def scan_text_citations(text: str) -> list[str]:
    """Article numbers mentioned anywhere in the finished text."""
    found: list[str] = []
    for match in _CITATION.finditer(text or ""):
        numbers = [match.group(1)]
        numbers.extend(_EXTRA_NUMBER.findall(match.group(2) or ""))
        for number in numbers:
            if number not in found:
                found.append(number)
    return found


def find_unvalidated_citations(text: str, result: ValidationResult) -> list[str]:
    """Articles the text names that validation never approved.

    A block can satisfy the schema and still smuggle an article number into its
    thesis, so the finished text is checked against the validated set.
    """
    allowed = result.validated_articles()
    return [number for number in scan_text_citations(text) if number not in allowed]


def build_offer(provisions: list[Provision]) -> tuple[set[str], str]:
    """Provisions offered to the model: the id set to validate against, and the prompt block."""
    offered_ids = {provision.article_id for provision in provisions}
    lines = [
        f"- article_id: {provision.article_id} | {provision.label()} — {provision.heading}\n"
        f"  Текст: {provision.body}"
        for provision in provisions
    ]
    return offered_ids, "\n".join(lines)
