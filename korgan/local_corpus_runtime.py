"""Production adapter for the feature-flagged local Kazakhstan legal corpus.

The SQLite corpus is an optimisation and a quality layer, never model memory.
A local result is used only when every legal block names an article_id that was
actually offered from the corpus, exists in the database, and survives the same
paraphrase-drift guard used by source-bound web research.

For the production fast path the model must also explicitly say that the offered
corpus is sufficient for the legal theory/remedies it selected. Any gap,
ambiguity or validation failure returns ``None`` and callers keep the existing
official web-search path. This makes the latency optimization fail closed.
"""

from __future__ import annotations

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

_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}
_LOCAL_PROFESSIONAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "legal_basis": LEGAL_BASIS_SCHEMA["properties"]["legal_basis"],
        "coverage_complete": {"type": "boolean"},
        "coverage_gaps": _STRING_ARRAY,
        "case_theory": _STRING_ARRAY,
        "remedies": _STRING_ARRAY,
        "evidence_map": _STRING_ARRAY,
        "risks": _STRING_ARRAY,
    },
    "required": [
        "legal_basis",
        "coverage_complete",
        "coverage_gaps",
        "case_theory",
        "remedies",
        "evidence_map",
        "risks",
    ],
    "additionalProperties": False,
}


def _strategy_notes(payload: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for key, prefix in (
        ("case_theory", "CASE_THEORY"),
        ("remedies", "REMEDY"),
        ("evidence_map", "EVIDENCE_MAP"),
        ("risks", "RISK"),
    ):
        for value in payload.get(key, []) or []:
            text = " ".join(str(value or "").split()).strip()
            if text:
                notes.append(f"{prefix}: {text}")
    return list(dict.fromkeys(notes))


def _looks_like_litigation(case_context: str) -> bool:
    low = case_context.casefold()
    return any(
        marker in low
        for marker in (
            "исков",
            "истец",
            "ответчик",
            "в суд",
            "судебн",
            "талап қою",
            "талапкер",
            "жауапкер",
            "сотқа",
        )
    )


async def research_case_from_local_corpus(
    service: Any,
    case_context: str,
    language: str = "ru",
    *,
    query: str | None = None,
    required_article_ids: tuple[str, ...] = (),
    require_complete_coverage: bool = False,
) -> LegalResearch | None:
    """Return source-bound local research, or ``None`` for unchanged web fallback.

    ``require_complete_coverage`` is used by the production latency fast path.
    It is intentionally stricter than ordinary corpus assistance: the model must
    declare no legal coverage gap, provide a usable theory/remedy, and a
    litigation-looking case must contain at least one accepted GPK provision.
    """
    offered = research_from_corpus(
        query or case_context,
        required_article_ids=required_article_ids,
    )
    if offered is None:
        return None

    prompt = (
        "Проведи профессиональное юридическое исследование ТОЛЬКО по переданному "
        "локальному корпусу действующих норм Республики Казахстан.\n\n"
        "ЖЁСТКИЕ ПРАВИЛА:\n"
        "1. article_id можно брать только буквально из блока КОРПУС.\n"
        "2. thesis должен точно и узко передавать правило из текста этой нормы; "
        "не добавляй условий, обязанностей, исключений, штрафов или сроков, которых "
        "нет в тексте нормы.\n"
        "3. link_to_facts связывает норму только с фактами из МАТЕРИАЛОВ; не выдумывай "
        "доказательства, даты, платежи, переписку или признание.\n"
        "4. Не вставляй номера иных статей внутрь thesis, link_to_facts или стратегические поля.\n"
        "5. case_theory, remedies, evidence_map и risks строй только из фактов пользователя "
        "и норм, выбранных в legal_basis. Нельзя добавлять точную норму из памяти модели.\n"
        "6. coverage_complete=true ставь ТОЛЬКО если предложенных норм достаточно для "
        "основной материально-правовой квалификации и выбранных способов защиты. Если для "
        "существенного правового вывода нужна норма вне переданного набора — false и явно "
        "опиши пробел в coverage_gaps.\n"
        "7. Точное наименование конкретного суда и арифметика госпошлины проверяются "
        "отдельными детерминированными модулями KORGAN и сами по себе не делают coverage_complete=false.\n"
        "8. Если предложенные нормы не дают надёжного основания, верни пустой legal_basis, "
        "coverage_complete=false и объясни пробел.\n\n"
        f"МАТЕРИАЛЫ:\n{case_context[:service.settings.max_case_text_chars]}\n\n"
        f"КОРПУС:\n{offered.prompt_block}"
    )
    try:
        payload, _ = await service._structured_response(
            model=service.settings.openai_model,
            instructions=(
                "Ты ведущий legal researcher KORGAN по праву Республики Казахстан. "
                "Работай только по переданным дословным нормам локального корпуса; память "
                "модели не является источником. Любой пробел в покрытии отмечай fail-closed. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_local_corpus_professional_research",
            schema=_LOCAL_PROFESSIONAL_SCHEMA,
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

    coverage_gaps = [
        " ".join(str(item or "").split()).strip()
        for item in payload.get("coverage_gaps", []) or []
        if " ".join(str(item or "").split()).strip()
    ]
    coverage_complete_raw = payload.get("coverage_complete")
    coverage_complete = bool(coverage_complete_raw) if coverage_complete_raw is not None else not coverage_gaps
    strategy_notes = _strategy_notes(payload)

    if require_complete_coverage:
        if not coverage_complete or coverage_gaps:
            LOGGER.info(
                "KORGAN local corpus coverage incomplete gaps=%s — using web search",
                coverage_gaps[:4],
            )
            return None
        if not any(note.startswith("CASE_THEORY:") for note in strategy_notes):
            LOGGER.info("KORGAN local corpus has no case theory — using web search")
            return None
        if not any(note.startswith("REMEDY:") for note in strategy_notes):
            LOGGER.info("KORGAN local corpus has no remedy analysis — using web search")
            return None
        accepted_act_ids = {block.provision.act_id for block in validation.accepted}
        if _looks_like_litigation(case_context) and ACT_GPK not in accepted_act_ids:
            LOGGER.info("KORGAN local corpus litigation result lacks GPK — using web search")
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

    unverified = list(dict.fromkeys(coverage_gaps))
    if coverage_complete_raw is False and not unverified:
        unverified.append("Локальный корпус не подтвердил полноту правового покрытия дела.")

    research = LegalResearch(
        status=(
            VerificationStatus.VERIFIED
            if not unverified
            else VerificationStatus.NEEDS_VERIFICATION
        ),
        applicable_law=applicable_law,
        procedural_requirements=procedural,
        verified_claims=verified_claims,
        unverified_claims=unverified,
        source_urls=source_urls,
        notes=strategy_notes,
    )
    LOGGER.info(
        "KORGAN local corpus research accepted provisions=%d sources=%d strategy=%d complete=%s",
        len(verified_claims),
        len(source_urls),
        len(strategy_notes),
        coverage_complete,
    )
    return research
