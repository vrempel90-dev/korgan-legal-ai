"""Production-safe activation of KORGAN cost/latency optimizations.

This installer intentionally does NOT patch the shared quality-repair method.
The contract/claim repair budget and every existing quality gate remain exactly
as before.  We only enable optimizations that are deterministic or preserve the
same official-source verification path.
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
    # local official-law RAG already exists, and deterministic verified court
    # registry resolution.  The shared LLM repair method is deliberately left
    # untouched so contracts and claims keep their existing repair semantics.
    optimizer._install_research_scope_optimizer()
    optimizer._install_rag_search_context_optimizer()
    optimizer._install_economic_court_registry()

    _INSTALLED = True
    LOGGER.info(
        "Installed KORGAN production cost/speed optimizer SAFE: progressive verified corpus + RAG-aware web context + economic court registry; models/repair/quality gates unchanged"
    )
