"""Feature-flagged entry into the local-corpus path.

Default behaviour is unchanged: without the flag — or with an empty/absent
corpus database — this returns nothing and the caller keeps using the existing
OpenAI web-search research. The flag is read from the environment rather than
added to Pydantic Settings, so the existing config stays untouched.

Falling back on an empty corpus is deliberate. The database is built by
`scripts/load_corpus.py` against adilet, which is a separate operational step;
until it has run, the local path has no provisions to offer and pretending
otherwise would produce claims with no legal basis at all.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from korgan.legal.corpus import DEFAULT_DB_PATH, LegalCorpus, Provision
from korgan.legal.validator import build_offer

LOGGER = logging.getLogger(__name__)

FLAG_ENV = "KORGAN_LOCAL_CORPUS"
_TRUTHY = {"1", "true", "yes", "on"}

DEFAULT_LIMIT = 12


def local_corpus_enabled() -> bool:
    return os.getenv(FLAG_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True, slots=True)
class CorpusResearch:
    provisions: tuple[Provision, ...]
    offered_ids: frozenset[str]
    prompt_block: str

    @property
    def source_urls(self) -> list[str]:
        urls: list[str] = []
        for provision in self.provisions:
            if provision.url not in urls:
                urls.append(provision.url)
        return urls


def open_corpus(path: Path | str | None = None) -> LegalCorpus | None:
    """Open the corpus, or return None when it has not been built yet."""
    db_path = Path(path or DEFAULT_DB_PATH)
    if not db_path.exists():
        LOGGER.info("KORGAN local corpus not found at %s — using web search", db_path)
        return None

    corpus = LegalCorpus(db_path)
    try:
        if corpus.count() == 0:
            LOGGER.info("KORGAN local corpus is empty — using web search")
            corpus.close()
            return None
    except Exception:
        LOGGER.exception("KORGAN local corpus unreadable — using web search")
        corpus.close()
        return None
    return corpus


def research_from_corpus(
    query: str,
    *,
    corpus: LegalCorpus | None = None,
    act_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> CorpusResearch | None:
    """Provisions for this case, or None when the local path is unavailable.

    None means «use the existing path», not «no law applies» — the distinction
    matters, because the fallback is a working research pass, not a failure.
    """
    if not local_corpus_enabled():
        return None

    owned = corpus is None
    active = corpus or open_corpus()
    if active is None:
        return None

    try:
        provisions = active.search(query, act_id=act_id, limit=limit)
    finally:
        if owned:
            active.close()

    if not provisions:
        LOGGER.info("KORGAN local corpus returned nothing for %r — using web search", query[:80])
        return None

    offered_ids, prompt_block = build_offer(provisions)
    return CorpusResearch(
        provisions=tuple(provisions),
        offered_ids=frozenset(offered_ids),
        prompt_block=prompt_block,
    )
