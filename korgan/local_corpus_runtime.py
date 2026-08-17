"""Production adapter for the feature-flagged local Kazakhstan legal corpus.

The SQLite corpus is an optimisation and a quality layer, never a source of
authority by itself.  A local result is used only when every legal block names
an article_id that was actually offered from the corpus, exists in the database,
and survives the same paraphrase-drift guard used by source-bound web research.

Any ambiguity returns ``None``.  Callers then keep the existing OpenAI web
research path, preserving KORGAN's fail-closed behaviour.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from korgan.legal.corpus import ACT_GPK
from korgan.legal.pipeline import open_corpus, research_from_corpus
from korgan.legal.validator import (
    LEGAL_BASIS_SCHEMA,
    find_unvalidated_citations,
    validate_blocks,
)
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.provision_check import paraphrase_defects, verified_claim_line

LOGGER = logging.getLogger(__name__)


async def research_case_from_local_corpus(
    service: Any,
    case_context: str,
    language: str = "ru",
    *,
    query: str | None = None,
    required_article_ids: tuple[str, ...] = (),
) -> LegalResearch | None:
    """Return fully source-bound local research, or ``None`` for web fallback."""
    offered = research_from_corpus(
        query or case_context,
        required_article_ids=required_article_ids,
    )
    if offered is None:
        return None

    prompt = (
        "Выбери применимые правовые основания ТОЛЬКО из переданного локального "
        "корпуса действующих норм Республики Казахстан.\n\n"
        "ЖЁСТКИЕ ПРАВИЛА:\n"
        "1. article_id можно брать только буквально из блока КОРПУС.\n"
        "2. thesis должен точно и узко передавать правило из текста этой нормы; "
        "не добавляй условий, обязанностей, исключений, штрафов или сроков, которых "
        "нет в тексте нормы.\n"
        "3. link_to_facts связывает норму только с фактами из МАТЕРИАЛОВ; не выдумывай "
        "доказательства, даты, платежи, переписку или признание.\n"
        "4. Не вставляй номера иных статей внутрь thesis или link_to_facts.\n"
        "5. Если предложенные нормы не дают надёжного основания, верни пустой legal_basis.\n\n"
        f"МАТЕРИАЛЫ:\n{case_context[:service.settings.max_case_text_chars]}\n\n"
        f"КОРПУС:\n{offered.prompt_block}"
    )
    try:
        payload, _ = await service._structured_response(
            model=service.settings.openai_model,
            instructions=(
                "Ты юридический исследователь KORGAN. Работай только по переданным "
                "дословным нормам локального корпуса; память модели не является источником. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_local_corpus_legal_basis",
            schema=LEGAL_BASIS_SCHEMA,
        )
    except Exception:
        LOGGER.exception("KORGAN local corpus model pass failed — using web search")
        return None

    blocks = list(payload.get("legal_basis", []))
    if not blocks:
        LOGGER.info("KORGAN local corpus model selected no provisions — using web search")
        return None

    corpus = open_corpus()
    if corpus is None:
        return None

    try:
        validation = validate_blocks(blocks, set(offered.offered_ids), corpus)
    finally:
        corpus.close()

    if validation.rejected or not validation.accepted:
        LOGGER.warning(
            "KORGAN local corpus rejected blocks=%d accepted=%d — using web search",
            len(validation.rejected),
            len(validation.accepted),
        )
        return None

    rendered_model_text = "\n".join(
        f"{block.get('thesis', '')}\n{block.get('link_to_facts', '')}" for block in blocks
    )
    leaked = find_unvalidated_citations(rendered_model_text, validation)
    if leaked:
        LOGGER.warning(
            "KORGAN local corpus unvalidated citations=%s — using web search",
            leaked,
        )
        return None

    verified_claims: list[str] = []
    source_urls: list[str] = []
    applicable_law: list[str] = []
    procedural: list[str] = []

    for block in validation.accepted:
        defects = paraphrase_defects(block.thesis, block.provision.body)
        if defects:
            LOGGER.warning(
                "KORGAN local corpus paraphrase rejected article_id=%s defects=%s — using web search",
                block.article_id,
                defects[:3],
            )
            return None

        verified_claims.append(
            verified_claim_line(
                block.thesis,
                block.provision.label(),
                block.provision.body,
                block.provision.url,
            )
        )
        if block.provision.url not in source_urls:
            source_urls.append(block.provision.url)
        if block.provision.act_title not in applicable_law:
            applicable_law.append(block.provision.act_title)
        if block.provision.act_id == ACT_GPK:
            procedural.append(block.thesis)

    if not verified_claims or not source_urls:
        return None

    LOGGER.info(
        "KORGAN local corpus research accepted provisions=%d sources=%d",
        len(verified_claims),
        len(source_urls),
    )
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=applicable_law,
        procedural_requirements=procedural,
        verified_claims=verified_claims,
        unverified_claims=[],
        source_urls=source_urls,
        notes=[],
    )
