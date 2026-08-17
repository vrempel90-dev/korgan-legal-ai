from __future__ import annotations

import logging
from typing import Any

from korgan.legal.pipeline import research_from_corpus

LOGGER = logging.getLogger(__name__)


def install_professional_rag_bridge() -> None:
    """Feed local Adilet corpus candidates into the existing professional research pass.

    The local corpus is a retrieval accelerator, not an authority shortcut. The
    professional service still performs its source-bound official web pass and
    only accepts law after the existing VERIFIED checks. No extra model call is
    added: the corpus contributes only deterministic candidate text to the one
    research prompt that already existed in the stable production path.
    """
    from korgan import fast_professional_litigation as litigation

    if getattr(litigation, "_korgan_local_rag_bridge_installed", False):
        return

    original = litigation._professional_research_prompt

    def bridged_prompt(
        case_context: str,
        *,
        max_chars: int,
        checked_on: str,
        **kwargs: Any,
    ) -> str:
        prompt = original(
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
    litigation._korgan_local_rag_bridge_installed = True
    LOGGER.info("Installed KORGAN professional local-RAG bridge")
