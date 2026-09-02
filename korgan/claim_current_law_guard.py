from __future__ import annotations

import logging
import re
from datetime import date

from korgan.claim_corpus_health import _snapshot_issue
from korgan.legal.corpus import (
    ACT_CONSUMER,
    ACT_GK_GENERAL,
    ACT_GK_SPECIAL,
    ACT_GPK,
    ACT_LABOR,
    ACT_TAX_DUTY,
)
from korgan.legal.pipeline import local_corpus_enabled, open_corpus
from korgan.legal_types import LegalResearch, VerificationStatus

LOGGER = logging.getLogger(__name__)

_ARTICLE_RE = re.compile(r"(?:статья|статьи|ст\.)\s*(\d+(?:-\d+)?)", re.IGNORECASE)
_SOURCE_RE = re.compile(r"источник:\s*(https?://[^\]\s]+)", re.IGNORECASE)
_SOURCE_ACT_IDS: tuple[tuple[str, str], ...] = (
    ("K940001000_", ACT_GK_GENERAL),
    ("K990000409_", ACT_GK_SPECIAL),
    ("K1500000377", ACT_GPK),
    ("K2500000214", ACT_TAX_DUTY),
    ("Z100000274_", ACT_CONSUMER),
    ("K1500000414", ACT_LABOR),
)
_RECHECK_SENTINEL = (
    "CURRENT_LAW_RECHECK_REQUIRED: an article citation was removed because it is absent "
    "from the fresh official corpus"
)


def _source_act_id(source_url: str) -> str | None:
    lowered = str(source_url or "").lower()
    for token, act_id in _SOURCE_ACT_IDS:
        if token.lower() in lowered:
            return act_id
    return None


def prune_noncurrent_verified_claims(research: LegalResearch) -> None:
    """Remove citations to articles absent from a fresh official KORGAN snapshot.

    Web verification establishes source provenance; the refreshed local corpus
    additionally establishes that the cited article still exists in the current
    official act. When the local snapshot is missing/stale we leave the claim in
    place so the existing corpus-health fail-closed gate can report that outage.

    When a fresh snapshot positively says that an article no longer exists, the
    stale proposition is removed from VERIFIED and a non-citation sentinel is
    kept in the verification stream. The filing-accuracy gate deliberately
    rejects that sentinel, so removing a stale article can never accidentally
    make a partially-supported filing look VERIFIED. A later deterministic
    rescue/current-law correction may add the proper current provision, but the
    stale proposition itself is never emitted into filing-facing legal basis.
    """
    if not local_corpus_enabled():
        return
    corpus = open_corpus()
    if corpus is None:
        return

    keep: list[str] = []
    pruned: list[str] = []
    fresh_cache: dict[str, bool] = {}
    try:
        for raw in research.verified_claims or []:
            line = str(raw or "")
            source = _SOURCE_RE.search(line)
            article = _ARTICLE_RE.search(line)
            if source is None or article is None:
                keep.append(line)
                continue
            act_id = _source_act_id(source.group(1))
            if act_id is None:
                keep.append(line)
                continue
            if act_id not in fresh_cache:
                fresh_cache[act_id] = _snapshot_issue(corpus, act_id, today=date.today()) is None
            if not fresh_cache[act_id]:
                keep.append(line)
                continue
            found = corpus.connection.execute(
                "SELECT 1 FROM provisions WHERE act_id = ? AND article_no = ? LIMIT 1",
                (act_id, article.group(1)),
            ).fetchone()
            if found is not None:
                keep.append(line)
                continue
            pruned.append(f"{act_id}:{article.group(1)}")
    except Exception:
        LOGGER.exception("CLAIM_CURRENT_LAW_GUARD failed; keeping source-bound research for fail-closed health gate")
        return
    finally:
        corpus.close()

    if not pruned:
        return

    # The sentinel is intentionally not a legal citation. claim_filing_accuracy
    # rejects malformed VERIFIED lines and adds a filing-facing LEGAL_GROUNDING
    # blocker. This preserves fail-closed semantics even when other valid
    # VERIFIED provisions remain in the same research result.
    if _RECHECK_SENTINEL not in keep:
        keep.append(_RECHECK_SENTINEL)
    research.verified_claims = keep
    research.status = VerificationStatus.NEEDS_VERIFICATION
    for item in pruned:
        note = f"CURRENT_LAW_PRUNED: {item} absent from fresh official corpus"
        if note not in research.notes:
            research.notes.append(note)
    LOGGER.warning("CLAIM_CURRENT_LAW_GUARD pruned=%s", pruned)
