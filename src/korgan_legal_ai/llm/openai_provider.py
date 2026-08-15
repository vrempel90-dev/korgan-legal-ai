from __future__ import annotations

from typing import TypeVar, cast

from openai import OpenAI
from pydantic import BaseModel

from .base import LLMProvider

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str | None = None) -> None:
        self.client = OpenAI(api_key=api_key)

    def parse(self, *, model: str, system: str, user: str, schema: type[T]) -> T:
        response = self.client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=schema,
        )
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
        raise RuntimeError("OpenAI returned no parsed structured output")
