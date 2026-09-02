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
        fetch_limit = max(limit * 2, limit, 12)
        official_hits = official.search(query, act_id=act_id, limit=fetch_limit) if official is not None else []
        upstream_hits = upstream.search(query, limit=fetch_limit) if upstream is not None else []

        # Deterministic routers may require exact ids from the official corpus.
        if official is not None:
            seen_ids = {provision.article_id for provision in official_hits}
            for article_id in required_article_ids or ():
                if article_id in seen_ids:
                    continue
                provision = official.get(article_id)
                if provision is None:
                    continue
                if act_id is not None and provision.act_id != act_id:
                    continue
                official_hits.append(provision)
                seen_ids.add(article_id)

        provisions = _merge_ranked(official_hits, upstream_hits, limit=max(1, limit))
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
        "KORGAN_LOCAL_RAG candidates=%d official=%d upstream=%d",
        len(provisions),
        len(official_hits),
        len(upstream_hits),
    )
    return CorpusResearch(
        provisions=tuple(provisions),
        offered_ids=frozenset(offered_ids),
        prompt_block=prompt_block,
    )