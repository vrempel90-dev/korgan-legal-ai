from __future__ import annotations

import logging
from typing import TypeVar, cast

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from .base import LLMProvider

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str | None = None) -> None:
        self.client = OpenAI(api_key=api_key)

    @staticmethod
    def _validation_signature(exc: ValidationError) -> str:
        """Return field/type diagnostics without values, messages or user content."""
        signature: list[str] = []
        for error in exc.errors(include_url=False, include_context=False, include_input=False)[:8]:
            location = ".".join(str(part) for part in error.get("loc", ())) or "root"
            error_type = str(error.get("type", "unknown"))
            signature.append(f"{location}:{error_type}")
        return ",".join(signature) or "unknown"

    @staticmethod
    def _extract_parsed(response, schema: type[T]) -> T:
        parsed = getattr(response, "output_parsed", None)
        if parsed is not None:
            return cast(T, parsed)

        for item in response.output:
            if getattr(item, "type", None) != "message":
                continue
            for content in getattr(item, "content", []):
                parsed = getattr(content, "parsed", None)
                if parsed is not None:
                    return cast(T, parsed)
        raise RuntimeError(f"OpenAI returned no parsed structured output for {schema.__name__}")

    def parse(self, *, model: str, system: str, user: str, schema: type[T]) -> T:
        current_system = system
        for attempt in range(2):
            try:
                response = self.client.responses.parse(
                    model=model,
                    input=[
                        {"role": "system", "content": current_system},
                        {"role": "user", "content": user},
                    ],
                    text_format=schema,
                )
                return self._extract_parsed(response, schema)
            except ValidationError as exc:
                logger.error(
                    "openai_structured_output_validation_failed schema=%s attempt=%d errors=%s",
                    schema.__name__,
                    attempt + 1,
                    self._validation_signature(exc),
                )
                if attempt == 0:
                    current_system = (
                        system
                        + "\n\nSTRUCTURED OUTPUT CORRECTION: Return only data that conforms exactly to "
                        "the supplied schema. Respect every field type and enum. Numeric/Decimal "
                        "fields must contain plain numeric values without currency symbols, percent "
                        "signs or explanatory text. Every typed date field must be an ISO calendar "
                        "date in YYYY-MM-DD format only; do not use DD.MM.YYYY, month names or "
                        "timestamps. Use null for unknown optional values. Do not replace the "
                        "structured response with prose or a refusal for this extraction task."
                    )
                    continue
                raise

        raise RuntimeError("Unreachable structured-output retry state")
