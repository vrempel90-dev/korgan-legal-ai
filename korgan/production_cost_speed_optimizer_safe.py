"""Production-safe activation of KORGAN cost/latency optimizations.

This installer keeps the production model, legal quality thresholds and release
checks unchanged.  It enables only deterministic/source-preserving savings plus
one narrowly-scoped repair optimization: an LLM repair is skipped only when
EVERY remaining defect requires external user/source data that the model is not
allowed to invent.  Substantive legal, monetary, citation and evidence defects
continue through the existing repair path unchanged.
"""

from __future__ import annotations

import logging

from korgan import production_cost_speed_optimizer as optimizer

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def install_production_cost_speed_optimizer_safe() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan.legal import corpus_refresh

    current_refresh = corpus_refresh.refresh_corpus_once
    if not getattr(current_refresh, "_korgan_progressive_bootstrap", False):
        progressive = optimizer._progressive_refresh_factory(
            current_refresh,
            corpus_refresh._load_from_official_sources,
        )
        progressive._korgan_progressive_bootstrap = True  # type: ignore[attr-defined]
        corpus_refresh.refresh_corpus_once = progressive

    # Safe savings only: narrower research scope, low web context when strong
    # local official-law RAG already exists, deterministic verified court
    # registry resolution, and no paid repair call for defects that the model is
    # explicitly forbidden to solve by invention (missing court/address/BIN/IIN
    # or equivalent external-only data).  Mixed/substantive issue sets are never
    # skipped and retain the exact existing repair semantics and quality gates.
    optimizer._install_research_scope_optimizer()
    optimizer._install_rag_search_context_optimizer()
    optimizer._install_futile_repair_skip()
    optimizer._install_economic_court_registry()

    _INSTALLED = True
    LOGGER.info(
        "Installed KORGAN production cost/speed optimizer SAFE: progressive verified corpus + RAG-aware web context + external-only futile-repair skip + economic court registry; models/quality gates unchanged"
    )
