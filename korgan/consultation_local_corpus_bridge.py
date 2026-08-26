"""Local-corpus-first consultation path with unchanged source-bound web fallback."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from korgan.legal_types import LegalResearch, VerificationStatus

LOGGER = logging.getLogger(__name__)


def _render_local_consultation(research: LegalResearch, language: str) -> str:
    from korgan.professional_consultation_guard import _safe_free_text, _today_kz

    kk = language == "kk"
    title = "Расталған құқықтық негіз:" if kk else "Подтверждено по действующему праву РК:"
    parts = [title + "\n" + "\n".join(f"• {item}" for item in research.verified_claims[:8])]

    actions: list[str] = []
    for note in research.notes:
        raw = str(note or "")
        if raw.startswith("REMEDY:"):
            candidate = raw.split(":", 1)[1].strip()
        elif raw.startswith("EVIDENCE_MAP:"):
            candidate = raw.split(":", 1)[1].strip()
        else:
            continue
        safe = _safe_free_text(candidate)
        if safe and safe not in actions:
            actions.append(safe)
    if actions:
        parts.append(
            ("Практикалық қадамдар:\n" if kk else "Практические шаги:\n")
            + "\n".join(f"• {item}" for item in actions[:6])
        )

    checked = _today_kz()
    parts.append(
        f"Құқықтың өзектілігі тексерілген күн: {checked}."
        if kk
        else f"Актуальность права проверена: {checked}."
    )
    return "\n\n".join(parts)


async def _consult_local_first(
    service: Any,
    fallback: Callable[..., Awaitable[tuple[str, list[str]]]],
    question: str,
    case_context: str = "",
    language: str = "ru",
) -> tuple[str, list[str]]:
    from korgan.local_corpus_runtime import research_case_from_local_corpus

    combined = question if not case_context else f"{question}\n\n{case_context}"
    try:
        local = await research_case_from_local_corpus(
            service,
            combined,
            language,
            query=combined,
            require_complete_coverage=True,
        )
    except Exception:
        LOGGER.exception("Consultation local-first pass failed — preserving web fallback")
        local = None

    if (
        local is not None
        and local.status == VerificationStatus.VERIFIED
        and local.verified_claims
        and local.source_urls
        and not local.unverified_claims
    ):
        LOGGER.info(
            "KORGAN_CONSULT_LOCAL_FAST_HIT verified=%d sources=%d web_search=skipped",
            len(local.verified_claims),
            len(local.source_urls),
        )
        return _render_local_consultation(local, language), list(local.source_urls)

    LOGGER.info("KORGAN_CONSULT_LOCAL_FALLBACK web_search=required")
    return await fallback(service, question, case_context=case_context, language=language)


def install_local_first_consultation() -> None:
    """Layer local verified law ahead of the existing guarded consultation call."""
    from korgan.finalized_litigation import FinalizedProductionClaimService
    from korgan.stable_legal_release import StableLegalProductionService

    for target in (StableLegalProductionService, FinalizedProductionClaimService):
        if target.__dict__.get("_korgan_local_first_consultation", False):
            continue
        current = target.consult

        async def local_first(
            self: Any,
            question: str,
            case_context: str = "",
            language: str = "ru",
            _fallback: Callable[..., Awaitable[tuple[str, list[str]]]] = current,
        ) -> tuple[str, list[str]]:
            return await _consult_local_first(
                self,
                _fallback,
                question,
                case_context=case_context,
                language=language,
            )

        target.consult = local_first  # type: ignore[method-assign]
        target._korgan_local_first_consultation = True

    LOGGER.info("Installed KORGAN local-corpus-first consultation with guarded web fallback")
