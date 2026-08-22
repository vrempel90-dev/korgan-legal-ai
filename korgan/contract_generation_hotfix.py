from __future__ import annotations

import json
import logging
import time
from typing import Any

from korgan.contract_repair_state import mark_contract_repair_completed
from korgan.late_interest_hotfix import ProductionOpenAILegalService as _BaseProductionOpenAILegalService
from korgan.verified_openai import _actual_response_urls

LOGGER = logging.getLogger(__name__)

_CONTRACT_OUTPUT_LIMITS: dict[str, tuple[int, int]] = {
    "korgan_contract_research": (6000, 10000),
    "korgan_contract_draft": (14000, 24000),
    "korgan_contract_validation": (2400, 4000),
    "korgan_contract_repair": (14000, 24000),
}


def _contract_output_instruction(schema_name: str) -> str:
    if schema_name == "korgan_contract_research":
        return (
            "\n\nТЕХНИЧЕСКОЕ ТРЕБОВАНИЕ: ответ должен быть компактным и полностью завершённым JSON. "
            "Не повторяй один и тот же правовой вывод разными словами. Для каждого реально важного вопроса достаточно одного точного verified_point."
        )
    if schema_name in {"korgan_contract_draft", "korgan_contract_repair"}:
        return (
            "\n\nТЕХНИЧЕСКОЕ ТРЕБОВАНИЕ: сформируй ПОЛНЫЙ договор, но без повторов и юридической воды. "
            "Обычно достаточно 8–12 содержательных разделов; объединяй близкие условия, не дублируй одну обязанность в разных разделах. "
            "Каждый пункт формулируй законченным и практичным предложением. Обязательно заверши весь JSON, включая реквизиты и verification_notes."
        )
    return "\n\nТЕХНИЧЕСКОЕ ТРЕБОВАНИЕ: верни краткий и полностью завершённый JSON без повторов."


class ProductionOpenAILegalService(_BaseProductionOpenAILegalService):
    """Article-353-safe runtime plus truncation-safe contract generation."""

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
                # Request-local ContextVar: concurrent Telegram generations cannot
                # suppress each other's quality repair pass.
                mark_contract_repair_completed()

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
