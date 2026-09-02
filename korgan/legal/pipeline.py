"""Feature-flagged entry into KORGAN's local legal retrieval path.

Two corpora may contribute *candidates*:

1. the current official Adilet/ZAN snapshot maintained by KORGAN; and
2. a broader Kazakhstan article corpus seeded from the pinned legal-rag-kz-uz
   release.

The second corpus is retrieval-only. It is deliberately stored separately and
never makes a provision VERIFIED by itself. Final legal conclusions still pass
through KORGAN's source-bound official-source verification and citation gates.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from korgan.legal.corpus import DEFAULT_DB_PATH, LegalCorpus, Provision
from korgan.legal.upstream_rag import open_upstream_corpus
from korgan.legal.validator import build_offer

LOGGER = logging.getLogger(__name__)

FLAG_ENV = "KORGAN_LOCAL_CORPUS"
_TRUTHY = {"1", "true", "yes", "on"}
_FALSEY = {"0", "false", "no", "off"}

DEFAULT_LIMIT = 12


def local_corpus_enabled() -> bool:
    """Local retrieval is on by default; explicit non-truthy values disable it."""
    if FLAG_ENV not in os.environ:
        return True
    raw = os.getenv(FLAG_ENV, "").strip().lower()
    if raw in _FALSEY:
        return False
    return raw in _TRUTHY


@dataclass(frozen=True, slots=True)
class CorpusResearch:
    provisions: tuple[Provision, ...]
    offered_ids: frozenset[str]
    prompt_block: str

    @property
    def source_urls(self) -> list[str]:
        urls: list[str] = []
        for provision in self.provisions:
            if provision.url and provision.url not in urls:
                urls.append(provision.url)
        return urls


def open_corpus(path: Path | str | None = None) -> LegalCorpus | None:
    """Open KORGAN's official-current corpus, or None when unavailable."""
    db_path = Path(path or DEFAULT_DB_PATH)
    if not db_path.exists():
        LOGGER.info("KORGAN official local corpus not found at %s", db_path)
        return None

    corpus = LegalCorpus(db_path)
    try:
        if corpus.count() == 0:
            LOGGER.info("KORGAN official local corpus is empty")
            corpus.close()
            return None
    except Exception:
        LOGGER.exception("KORGAN official local corpus unreadable")
        corpus.close()
        return None
    return corpus


def _dedupe_key(provision: Provision) -> tuple[str, str, str]:
    """Collapse the same article when official and retrieval-only corpora overlap."""
    url = (provision.url or "").strip().lower().rstrip("/")
    if url:
        return (url, provision.article_no, provision.item_no or "")
    title = " ".join((provision.act_title or "").lower().split())
    return (title, provision.article_no, provision.item_no or "")


def _merge_ranked(
    official: list[Provision],
    upstream: list[Provision],
    *,
    limit: int,
) -> list[Provision]:
    """Interleave two independently-ranked FTS lists without comparing BM25 scales."""
    if limit <= 0:
        return []
    result: list[Provision] = []
    seen: set[tuple[str, str, str]] = set()
    width = max(len(official), len(upstream))
    for idx in range(width):
        for source in (official, upstream):
            if idx >= len(source):
                continue
            provision = source[idx]
            key = _dedupe_key(provision)
            if key in seen:
                continue
            seen.add(key)
            result.append(provision)
            if len(result) >= limit:
                return result
    return result


def _required_official_provisions(
    official: LegalCorpus | None,
    official_hits: list[Provision],
    required_article_ids: Iterable[str] | None,
    *,
    act_id: str | None,
) -> list[Provision]:
    """Resolve deterministic required article ids from the authoritative corpus.

    Required rows are kept separately from ranked retrieval so fusion with the
    broader upstream corpus can never truncate procedural must-haves such as
    GPK articles 148/149.
    """
    if official is None:
        return []

    by_id = {provision.article_id: provision for provision in official_hits}
    required: list[Provision] = []
    seen_ids: set[str] = set()
    for article_id in required_article_ids or ():
        if article_id in seen_ids:
            continue
        provision = by_id.get(article_id) or official.get(article_id)
        if provision is None:
            continue
        if act_id is not None and provision.act_id != act_id:
            continue
        required.append(provision)
        seen_ids.add(article_id)
    return required


def research_from_corpus(
    query: str,
    *,
    corpus: LegalCorpus | None = None,
    act_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
    required_article_ids: Iterable[str] | None = None,
) -> CorpusResearch | None:
    """Return legal candidates while preserving the official verification boundary.

    An explicitly supplied ``corpus`` keeps the historical single-corpus
    behaviour used by deterministic callers/tests. Normal production calls open
    both KORGAN's official-current snapshot and the broader upstream KZ corpus.
    The latter is skipped for act-bound queries because its act ids are
    intentionally isolated from KORGAN's official act ids.
    """
    if not local_corpus_enabled():
        return None

    owned_official = corpus is None
    official = corpus or open_corpus()
    upstream = None if corpus is not None or act_id is not None else open_upstream_corpus()

    if official is None and upstream is None:
        LOGGER.info("KORGAN local retrieval has no ready corpus — using source-bound web research")
        return None

    official_hits: list[Provision] = []
    upstream_hits: list[Provision] = []
    try:
        requested_limit = max(1, limit)
        fetch_limit = max(requested_limit * 2, requested_limit, 12)
        official_hits = official.search(query, act_id=act_id, limit=fetch_limit) if official is not None else []
        upstream_hits = upstream.search(query, limit=fetch_limit) if upstream is not None else []

        required = _required_official_provisions(
            official,
            official_hits,
            required_article_ids,
            act_id=act_id,
        )
        required_keys = {_dedupe_key(provision) for provision in required}
        optional_official = [
            provision for provision in official_hits if _dedupe_key(provision) not in required_keys
        ]
        optional_upstream = [
            provision for provision in upstream_hits if _dedupe_key(provision) not in required_keys
        ]

        # Required official provisions have contractual priority. Normally they
        # fit inside ``limit`` and the remaining slots are filled by fused
        # ranking. If a caller explicitly requires more provisions than the
        # nominal limit, preserving all required legal rules is safer than
        # silently dropping one.
        optional_slots = max(0, requested_limit - len(required))
        provisions = required + _merge_ranked(
            optional_official,
            optional_upstream,
            limit=optional_slots,
        )
    finally:
        if owned_official and official is not None:
            official.close()
        if upstream is not None:
            upstream.close()

    if not provisions:
        LOGGER.info("KORGAN local retrieval returned nothing for %r", query[:80])
        return None

    offered_ids, prompt_block = build_offer(provisions)
    LOGGER.info(
        "KORGAN_LOCAL_RAG candidates=%d official=%d upstream=%d required=%d",
        len(provisions),
        len(official_hits),
        len(upstream_hits),
        len(required),
    )
    return CorpusResearch(
        provisions=tuple(provisions),
        offered_ids=frozenset(offered_ids),
        prompt_block=prompt_block,
    )
