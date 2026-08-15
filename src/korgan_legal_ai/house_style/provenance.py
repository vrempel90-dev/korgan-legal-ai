from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROVENANCE_DIR = Path(__file__).parent
DEFAULT_VERSION = 1


@dataclass(frozen=True)
class CorpusDocument:
    """A reference document, identified without revealing anything about its parties.

    ``document_id`` and ``sha256`` are the only handles that cross into this repository. The
    mapping from a document_id to the actual filed claim lives in the private corpus store, so
    provenance stays auditable here while personal data does not.
    """

    document_id: str
    dispute_type: str
    sha256: str
    corpus_version: int


@dataclass(frozen=True)
class RuleProvenance:
    rule_id: str
    derived_from: tuple[str, ...]

    @property
    def source_count(self) -> int:
        return len(self.derived_from)


@dataclass(frozen=True)
class CorpusProvenance:
    corpus_version: int
    documents: tuple[CorpusDocument, ...]
    provenance: tuple[RuleProvenance, ...]

    def for_rule(self, rule_id: str) -> RuleProvenance | None:
        return next((item for item in self.provenance if item.rule_id == rule_id), None)

    def document(self, document_id: str) -> CorpusDocument | None:
        return next((doc for doc in self.documents if doc.document_id == document_id), None)

    def without_document(self, document_id: str) -> "CorpusProvenance":
        """Rebuild provenance as if one document had been withdrawn from the corpus.

        Supports the retention requirement: a client can have a single filed claim removed, and
        every rule that rested only on that document disappears with it rather than lingering as
        an unattributable rule.
        """
        remaining_docs = tuple(
            doc for doc in self.documents if doc.document_id != document_id
        )
        rebuilt: list[RuleProvenance] = []
        for item in self.provenance:
            sources = tuple(doc for doc in item.derived_from if doc != document_id)
            if sources:
                rebuilt.append(RuleProvenance(rule_id=item.rule_id, derived_from=sources))
        return CorpusProvenance(
            corpus_version=self.corpus_version,
            documents=remaining_docs,
            provenance=tuple(rebuilt),
        )

    def orphaned_rules(self, other: "CorpusProvenance") -> tuple[str, ...]:
        """Rule ids present here but no longer supported after a withdrawal."""
        kept = {item.rule_id for item in other.provenance}
        return tuple(item.rule_id for item in self.provenance if item.rule_id not in kept)


@lru_cache(maxsize=8)
def load_provenance(version: int = DEFAULT_VERSION) -> CorpusProvenance:
    path = PROVENANCE_DIR / f"provenance.v{version}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Corpus provenance v{version} is not bundled")
    payload = json.loads(path.read_text(encoding="utf-8"))
    documents = tuple(
        CorpusDocument(
            document_id=item["document_id"],
            dispute_type=item["dispute_type"],
            sha256=item["sha256"],
            corpus_version=int(item["corpus_version"]),
        )
        for item in payload["documents"]
    )
    provenance = tuple(
        RuleProvenance(rule_id=item["rule_id"], derived_from=tuple(item["derived_from"]))
        for item in payload["provenance"]
    )
    return CorpusProvenance(
        corpus_version=int(payload["corpus_version"]),
        documents=documents,
        provenance=provenance,
    )
