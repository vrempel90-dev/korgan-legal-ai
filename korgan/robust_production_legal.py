from __future__ import annotations

import json
import logging
import time
from typing import Any

from korgan.fast_v2_production_legal import ProductionOpenAILegalService as _FastV2
from korgan.verified_openai import _actual_response_urls

LOGGER = logging.getLogger(__name__)


class ProductionOpenAILegalService(_FastV2):
    """Fast-v2 runtime with a narrow retry for truncated structured JSON only."""

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
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": content,
            "text": self._json_schema(schema_name, schema),
            "store": False,
            "prompt_cache_key": f"korgan:{schema_name}:v3",
        }

        if model == "gpt-5.1" or model.startswith("gpt-5.1-"):
            kwargs["reasoning"] = {"effort": "none"}

        # Keep common structured calls compact, but leave enough room for a
        # validator to describe several defects without cutting JSON mid-string.
        output_limits = {
            "korgan_consult_research": 1800,
            "korgan_verified_legal_research": 3000,
            "korgan_court_ready_validation": 2400,
        }
        if schema_name in output_limits:
            kwargs["max_output_tokens"] = output_limits[schema_name]

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "required"
            kwargs["include"] = ["web_search_call.action.sources"]

        started = time.perf_counter()
        response = await self.client.responses.create(**kwargs)
        first_elapsed = time.perf_counter() - started

        try:
            payload = json.loads(response.output_text)
        except json.JSONDecodeError as exc:
            # The API succeeded but the JSON was cut by our latency-oriented
            # output cap. Retry ONLY this structured step with a generous cap;
            # do not restart research/drafting that already succeeded.
            if schema_name not in output_limits:
                raise
            LOGGER.warning(
                "KORGAN structured JSON truncated: schema=%s chars=%d error=%s; retrying this step only",
                schema_name,
                len(response.output_text or ""),
                exc,
            )
            retry_kwargs = dict(kwargs)
            retry_kwargs["max_output_tokens"] = 5200
            retry_started = time.perf_counter()
            response = await self.client.responses.create(**retry_kwargs)
            retry_elapsed = time.perf_counter() - retry_started
            payload = json.loads(response.output_text)
            LOGGER.info(
                "KORGAN structured retry: schema=%s seconds=%.2f chars=%d",
                schema_name,
                retry_elapsed,
                len(response.output_text or ""),
            )

        LOGGER.info(
            "KORGAN OpenAI structured call: schema=%s seconds=%.2f actual_web_urls=%d",
            schema_name,
            first_elapsed,
            len(_actual_response_urls(response)),
        )
        return payload, response
