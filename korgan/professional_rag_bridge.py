from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from korgan.legal.pipeline import research_from_corpus
from korgan.legal_types import LegalResearch, VerificationStatus

LOGGER = logging.getLogger(__name__)


async def _research_local_first(
    service: Any,
    original_research: Callable[..., Awaitable[LegalResearch]],
    case_context: str,
    language: str = "ru",
) -> LegalResearch:
    """Use a complete validated local-corpus result, else preserve web research exactly."""
    from korgan.local_corpus_runtime import research_case_from_local_corpus

    try:
        local = await research_case_from_local_corpus(
            service,
            case_context,
            language,
            require_complete_coverage=True,
        )
    except Exception:
        LOGGER.exception("Professional local-first research failed — preserving web fallback")
        local = None

    if (
        local is not None
        and local.status == VerificationStatus.VERIFIED
        and local.verified_claims
        and local.source_urls
        and not local.unverified_claims
    ):
        LOGGER.info(
            "PROFESSIONAL_LOCAL_CORPUS_FAST_HIT verified=%d sources=%d strategy=%d web_search=skipped",
            len(local.verified_claims),
            len(local.source_urls),
            len(local.notes),
        )
        return local

    LOGGER.info("PROFESSIONAL_LOCAL_CORPUS_FALLBACK web_search=required")
    return await original_research(service, case_context, language=language)


def install_professional_rag_bridge() -> None:
    """Make the verified local Adilet corpus the first production research path.

    Two layers are installed:
    1. local-first: a complete, mechanically validated corpus result returns
       immediately and therefore avoids the live web-search round trip;
    2. unchanged fallback: if local coverage is absent/incomplete/ambiguous, the
       existing professional source-bound web research runs exactly as before,
       with local corpus candidates appended only as search hints.

    No legal rule becomes VERIFIED from model memory. The local fast path accepts
    only article_ids actually offered from the current corpus and validated back
    against that corpus. Any uncertainty falls back to the existing web path.
    """
    from korgan import fast_professional_litigation as litigation

    if getattr(litigation, "_korgan_local_rag_bridge_installed", False):
        return

    original_prompt = litigation._professional_research_prompt

    def bridged_prompt(
        case_context: str,
        *,
        max_chars: int,
        checked_on: str,
        **kwargs: Any,
    ) -> str:
        prompt = original_prompt(
            case_context,
            max_chars=max_chars,
            checked_on=checked_on,
            **kwargs,
        )
        try:
            offered = research_from_corpus(case_context, limit=12)
        except Exception:
            LOGGER.exception("Professional RAG candidate lookup failed; keeping web research")
            return prompt
        if offered is None:
            return prompt

        LOGGER.info(
            "PROFESSIONAL_RAG_HINTS candidates=%d sources=%d",
            len(offered.provisions),
            len(offered.source_urls),
        )
        return (
            prompt
            + "\n\nЛОКАЛЬНЫЕ RAG-КАНДИДАТЫ ИЗ КОРПУСА ADILET (НЕ ФАКТЫ ДЕЛА):\n"
            + offered.prompt_block
            + "\n\nПРАВИЛА ДЛЯ ЭТОГО БЛОКА:\n"
            "- используй его только как список кандидатов для проверки;\n"
            "- не считай норму VERIFIED только потому, что она есть в локальном корпусе;\n"
            "- итоговый правовой вывод и точную редакцию всё равно свяжи с реально открытым "
            "официальным источником в текущем source-bound поиске;\n"
            "- если локальный кандидат не подходит фактам или актуальной редакции, отбрось его;\n"
            "- не переносить текст этого служебного блока в фактические обстоятельства иска."
        )

    litigation._professional_research_prompt = bridged_prompt

    cls = litigation.FastProfessionalLitigationService
    original_research = cls.research_case

    async def local_first_research(
        self: Any,
        case_context: str,
        language: str = "ru",
    ) -> LegalResearch:
        return await _research_local_first(
            self,
            original_research,
            case_context,
            language,
        )

    local_first_research._korgan_local_first_research = True  # type: ignore[attr-defined]
    cls.research_case = local_first_research

    litigation._korgan_local_rag_bridge_installed = True
    LOGGER.info("Installed KORGAN professional local-first corpus + web fallback bridge")
