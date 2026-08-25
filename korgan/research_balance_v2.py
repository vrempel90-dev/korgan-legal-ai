"""One bounded recovery pass for the production research balance invariant."""

from __future__ import annotations

import copy
import logging
from typing import Any

from korgan.legal_types import LegalResearch
from korgan.production_invariants_v2 import _RESEARCH_CACHE, _research_key, canonicalize_research

LOGGER = logging.getLogger(__name__)


def _rank(research: LegalResearch) -> tuple[int, int, int, int]:
    verified = len(research.verified_claims)
    unverified = len(research.unverified_claims)
    return verified - unverified, verified, -unverified, len(research.source_urls)


def install_research_balance_v2(service_cls: type[Any]) -> None:
    """Retry once only when high-context research violates verified>=unverified.

    The retry is a quality recovery, not a second document generation.  It is
    bounded to one call and the best result is frozen back into the deterministic
    per-process cache, so identical subsequent input cannot oscillate between
    article sets.
    """
    if getattr(service_cls, "_korgan_research_balance_v2", False):
        return
    original = service_cls.research_case

    async def research_case(self: Any, case_context: str, language: str = "ru") -> LegalResearch:
        first = canonicalize_research(await original(self, case_context, language=language))
        first_v = len(first.verified_claims)
        first_u = len(first.unverified_claims)
        if first_v >= first_u:
            LOGGER.info(
                "RESEARCH_HIGH_CONTEXT_COMPARE retry=0 first_verified=%d first_unverified=%d chosen=first",
                first_v,
                first_u,
            )
            return first

        # The wrapped research method cached the first result. Remove exactly
        # this key so the one allowed recovery pass performs fresh source-bound
        # research instead of immediately returning the cached object.
        key = _research_key(case_context, language)
        _RESEARCH_CACHE.pop(key, None)
        second = canonicalize_research(await original(self, case_context, language=language))
        second_v = len(second.verified_claims)
        second_u = len(second.unverified_claims)

        chosen = second if _rank(second) > _rank(first) else first
        chosen_name = "second" if chosen is second else "first"
        _RESEARCH_CACHE[key] = copy.deepcopy(chosen)
        LOGGER.info(
            "RESEARCH_HIGH_CONTEXT_COMPARE retry=1 first_verified=%d first_unverified=%d "
            "second_verified=%d second_unverified=%d chosen=%s invariant_ok=%d",
            first_v,
            first_u,
            second_v,
            second_u,
            chosen_name,
            1 if len(chosen.verified_claims) >= len(chosen.unverified_claims) else 0,
        )
        return copy.deepcopy(chosen)

    service_cls.research_case = research_case
    service_cls._korgan_research_balance_v2 = True
