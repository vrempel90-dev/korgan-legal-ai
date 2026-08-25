"""Structured log events required for production invariant auditing."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from korgan.production_invariants_v2 import _RUN_ID, _research_key

LOGGER = logging.getLogger(__name__)
_ARTICLE_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*(\d+(?:-\d+)?)")
_ACT_RE = re.compile(r"(?i)\b(ГК\s*РК|ГПК\s*РК|ТК\s*РК|НК\s*РК|АППК\s*РК)\b")


def _norm_set(research: Any) -> tuple[str, ...]:
    values: set[str] = set()
    for raw in getattr(research, "verified_claims", []) or []:
        text = " ".join(str(raw).split())
        articles = _ARTICLE_RE.findall(text)
        act_match = _ACT_RE.search(text)
        act = re.sub(r"\s+", " ", act_match.group(1).upper()) if act_match else "UNKNOWN_ACT"
        for article in articles:
            values.add(f"{act}:{article}")
    return tuple(sorted(values))


def install_invariant_observability_v2(service_cls: type[Any]) -> None:
    from korgan import production_invariants_v2 as prod
    from korgan import universal_document_invariants_v2 as universal_docs

    if getattr(service_cls, "_korgan_observability_v2", False):
        return

    # Research selection determinism: same input hash must resolve to the same
    # exact normalized provision-set hash.
    original_research = service_cls.research_case

    async def research_case(self: Any, case_context: str, language: str = "ru"):
        research = await original_research(self, case_context, language=language)
        norms = _norm_set(research)
        norm_hash = hashlib.sha256("\n".join(norms).encode("utf-8")).hexdigest()
        input_hash = _research_key(case_context, language)
        LOGGER.info(
            "RESEARCH_NORM_SET run=%s input_hash=%s norm_hash=%s norms=%s verified=%d unverified=%d",
            _RUN_ID.get(),
            input_hash[:16],
            norm_hash[:16],
            list(norms),
            len(getattr(research, "verified_claims", []) or []),
            len(getattr(research, "unverified_claims", []) or []),
        )
        return research

    service_cls.research_case = research_case

    # A user block must preserve exact diagnosis plus an actionable instruction.
    original_user_message = prod._user_data_message

    def user_data_message(kind: str, issues: list[Any]) -> str:
        reasons = [getattr(item, "text", str(item)) for item in issues[:6]]
        actions = [getattr(item, "action", "") for item in issues[:6]]
        LOGGER.warning(
            "USER_BLOCK_REASON run=%s kind=%s blocker_class=NEEDS_USER_DATA reasons=%s actions=%s",
            _RUN_ID.get(),
            kind,
            reasons,
            actions,
        )
        return original_user_message(kind, issues)

    prod._user_data_message = user_data_message
    universal_docs._user_data_message = user_data_message

    # Final export/delivery may happen once for a run+kind.  Duplicates are
    # explicitly machine-readable instead of being inferred from timestamps.
    original_mark = prod._mark_delivery_once

    def mark_delivery_once(kind: str) -> bool:
        accepted = original_mark(kind)
        LOGGER.info(
            "FINALIZATION_ONCE run=%s kind=%s accepted=%d",
            _RUN_ID.get(),
            kind,
            1 if accepted else 0,
        )
        return accepted

    prod._mark_delivery_once = mark_delivery_once
    universal_docs._mark_delivery_once = mark_delivery_once

    service_cls._korgan_observability_v2 = True
    LOGGER.info("Installed structured KORGAN invariant observability v2")
