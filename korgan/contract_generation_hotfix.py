from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from korgan.contract_repair_state import (
    contract_repair_attempted,
    mark_contract_repair_attempted,
    mark_contract_repair_completed,
    reset_contract_repair_attempted,
)
from korgan.late_interest_hotfix import ProductionOpenAILegalService as _BaseProductionOpenAILegalService
from korgan.legal_routing import detect_contract_profile
from korgan.legal_types import ContractClause, ContractDraft, ContractSection, LegalResearch, VerificationStatus
from korgan.verified_openai import _actual_response_urls

LOGGER = logging.getLogger(__name__)

_CONTRACT_OUTPUT_LIMITS: dict[str, tuple[int, int]] = {
    "korgan_contract_research": (6000, 10000),
    "korgan_contract_draft": (14000, 24000),
    "korgan_contract_validation": (2400, 4000),
    "korgan_contract_repair": (14000, 24000),
}
_VERIFIED_LINE_RE = re.compile(
    r"^(?P<statement>.*?)\s*\[основание:\s*(?P<article>.*?);\s*текст\s+нормы:.*?;\s*источник:\s*(?P<url>https?://[^\]]+)\]$",
    re.IGNORECASE | re.DOTALL,
)
_SPECIAL_PART_SOURCE_TOKEN = "K990000409"
_SPECIAL_PART_PROFILES = frozenset({"services", "supply", "work_contract", "lease", "sale", "loan"})
_SPECIAL_PART_NOTE = "Не подтверждены профильные нормы Особенной части ГК РК для этого вида договора."
_LEGAL_SECTION_RE = re.compile(r"(?i)(?:применим\w*\s+прав|правов\w*\s+регулирован|законодательств|құқықтық\s+реттеу|қолданылатын\s+құқық)")


def _contract_output_instruction(schema_name: str) -> str:
    if schema_name == "korgan_contract_research":
        return (
            "\n\nТЕХНИЧЕСКОЕ ТРЕБОВАНИЕ: ответ должен быть компактным и полностью завершённым JSON. "
            "Не повторяй один и тот же правовой вывод разными словами. Для каждого реально важного вопроса достаточно одного точного verified_point. "
            "Если договор гражданско-правовой и его вид урегулирован профильной главой Особенной части ГК РК, обязательно открой на Adilet именно эту главу и подтверди профильные статьи; общие нормы об обязательствах не заменяют специальное регулирование."
        )
    if schema_name in {"korgan_contract_draft", "korgan_contract_repair"}:
        return (
            "\n\nТЕХНИЧЕСКОЕ ТРЕБОВАНИЕ: сформируй ПОЛНЫЙ договор, но без повторов и юридической воды. "
            "Обычно достаточно 8–12 содержательных разделов; объединяй близкие условия, не дублируй одну обязанность в разных разделах. "
            "Каждый пункт формулируй законченным и практичным предложением. Обязательно заверши весь JSON, включая реквизиты и verification_notes. "
            "Специальные нормы ГК используй только из VERIFIED; не придумывай номер статьи и не копируй сноски/историю изменений Adilet."
        )
    return "\n\nТЕХНИЧЕСКОЕ ТРЕБОВАНИЕ: верни краткий и полностью завершённый JSON без повторов."


def _special_part_points(research: LegalResearch, language: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in research.verified_claims or []:
        line = str(raw or "").strip()
        match = _VERIFIED_LINE_RE.match(line)
        if not match:
            continue
        url = match.group("url").strip()
        if _SPECIAL_PART_SOURCE_TOKEN.casefold() not in url.casefold():
            continue
        statement = " ".join(match.group("statement").split()).strip(" .")
        article = " ".join(match.group("article").split()).strip(" .")
        if not statement or not article:
            continue
        key = re.sub(r"\W+", "", article.casefold())
        if not key or key in seen:
            continue
        seen.add(key)
        if language == "kk":
            rendered = f"{statement}. Құқықтық негіз: {article}."
        else:
            rendered = f"{statement}. Правовое основание: {article}."
        result.append(rendered)
    return result[:6]


def _inject_verified_special_part(
    case_context: str,
    research: LegalResearch,
    draft: ContractDraft,
    *,
    language: str,
) -> None:
    """Expose verified special-part law in the client contract without LLM memory."""
    profile = detect_contract_profile(case_context)
    if profile.code not in _SPECIAL_PART_PROFILES:
        return

    points = _special_part_points(research, language)
    if not points:
        if _SPECIAL_PART_NOTE not in draft.verification_notes:
            draft.verification_notes.append(_SPECIAL_PART_NOTE)
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        LOGGER.warning("CONTRACT_SPECIAL_PART missing profile=%s", profile.code)
        return

    draft.verification_notes = [note for note in draft.verification_notes if note != _SPECIAL_PART_NOTE]
    existing_text = "\n".join(draft.body_lines()).casefold()
    missing = [point for point in points if re.sub(r"\W+", "", point.casefold()) not in re.sub(r"\W+", "", existing_text)]
    if not missing:
        return

    target = next((section for section in draft.sections if _LEGAL_SECTION_RE.search(section.heading)), None)
    if target is None:
        target = ContractSection(
            heading="Қолданылатын құқық" if language == "kk" else "Применимое законодательство",
            clauses=[],
        )
        draft.sections.append(target)

    target_text = "\n".join(target.text_lines()).casefold()
    for point in missing:
        article_match = re.search(r"(?i)(?:стать\w*|ст\.|бап)\s*\d+(?:-\d+)?|\d+(?:-\d+)?-бап", point)
        marker = article_match.group(0).casefold() if article_match else point.casefold()
        if marker in target_text:
            continue
        target.clauses.append(ContractClause(text=point))
        target_text += "\n" + point.casefold()

    LOGGER.info("CONTRACT_SPECIAL_PART injected profile=%s provisions=%d", profile.code, len(missing))


class ProductionOpenAILegalService(_BaseProductionOpenAILegalService):
    """Article-353-safe runtime plus truncation-safe contract generation."""

    async def draft_contract(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ContractDraft:
        """Mark a lower repair completed only after reconstruction and revalidation return."""
        reset_contract_repair_attempted()
        draft = await super().draft_contract(case_context, research, language=language)
        _inject_verified_special_part(case_context, research, draft, language=language)
        if contract_repair_attempted():
            mark_contract_repair_completed()
        return draft

    async def _structured_response(
        self,
        *,
        model: str,
        instructions: str,
        content: list[dict[str, Any]] | str,
        schema_name: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], Any]:
        limits = _CONTRACT_OUTPUT_LIMITS.get(schema_name)
        if limits is None:
            return await super()._structured_response(
                model=model,
                instructions=instructions,
                content=content,
                schema_name=schema_name,
                schema=schema,
                tools=tools,
            )

        base_instructions = instructions + _contract_output_instruction(schema_name)
        last_error: Exception | None = None

        for attempt, max_tokens in enumerate(limits, start=1):
            kwargs: dict[str, Any] = {
                "model": model,
                "instructions": base_instructions,
                "input": content,
                "text": self._json_schema(schema_name, schema),
                "store": False,
                "prompt_cache_key": f"korgan:{schema_name}:contract-complete-v1",
                "max_output_tokens": max_tokens,
            }
            if model == "gpt-5.1" or model.startswith("gpt-5.1-"):
                kwargs["reasoning"] = {"effort": "none"}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "required"
                kwargs["include"] = ["web_search_call.action.sources"]

            started = time.perf_counter()
            response = await self.client.responses.create(**kwargs)
            elapsed = time.perf_counter() - started
            text = response.output_text or ""
            status = str(getattr(response, "status", "") or "")
            incomplete = getattr(response, "incomplete_details", None)
            reason = str(getattr(incomplete, "reason", "") or "") if incomplete is not None else ""

            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                last_error = exc
                LOGGER.warning(
                    "KORGAN contract JSON incomplete: schema=%s attempt=%d max_tokens=%d status=%s reason=%s chars=%d error=%s",
                    schema_name,
                    attempt,
                    max_tokens,
                    status,
                    reason,
                    len(text),
                    exc,
                )
                if attempt < len(limits):
                    continue
                raise

            if schema_name == "korgan_contract_repair":
                mark_contract_repair_attempted()

            LOGGER.info(
                "KORGAN contract structured call: schema=%s attempt=%d max_tokens=%d status=%s reason=%s seconds=%.2f chars=%d actual_web_urls=%d",
                schema_name,
                attempt,
                max_tokens,
                status,
                reason,
                elapsed,
                len(text),
                len(_actual_response_urls(response)),
            )
            return payload, response

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Contract structured response failed: {schema_name}")
