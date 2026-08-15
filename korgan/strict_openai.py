from __future__ import annotations

import json
import logging
from typing import Any

from korgan.legal_types import VerificationStatus
from korgan.openai_legal import OpenAILegalService

LOGGER = logging.getLogger(__name__)


class StrictOpenAILegalService(OpenAILegalService):
    """KORGAN legal service that requires official web research for legal conclusions."""

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
        }
        if tools:
            kwargs["tools"] = tools
            # A legal research pass is not allowed to answer from model memory.
            kwargs["tool_choice"] = "required"

        response = await self.client.responses.create(**kwargs)
        payload = json.loads(response.output_text)
        urls = [url for url in self._annotation_urls(response) if self._allowed_source(url)]
        LOGGER.info("KORGAN structured research: official_sources=%d", len(urls))
        return payload, response

    async def consult(
        self,
        question: str,
        case_context: str = "",
        language: str = "ru",
    ) -> tuple[str, list[str]]:
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": "high",
        }]

        prompt = (
            f"Вопрос пользователя:\n{question}\n\n"
            f"Контекст загруженных документов:\n{case_context[:30000] if case_context else 'нет'}\n\n"
            "Сначала ОБЯЗАТЕЛЬНО выполни поиск по разрешенным официальным источникам. "
            "Отвечай только на основании найденных официальных страниц. "
            "Для каждой применимой нормы указывай точный номер статьи только если он найден в источнике. "
            "Никогда не пиши номер статьи из памяти и не используй формулировки вроде "
            "'традиционно статья X', 'обычно статья X' или 'как правило статья X'. "
            "Если конкретную норму не удалось подтвердить, не называй предполагаемый номер: "
            "напиши NEEDS_VERIFICATION и укажи, что именно не подтверждено. "
            "Проверь отдельно: материальное право, подходящий вид производства, подсудность, "
            "досудебный порядок, срок исковой давности, требования к иску, приложения и госпошлину. "
            "Не предлагай судебный приказ, упрощенное или иное специальное производство, пока "
            "не подтвердил, что факты пользователя входят в действующий перечень оснований. "
            "Если правило было исключено или изменено, применяй только текущую редакцию."
        )

        response = await self.client.responses.create(
            model=self.settings.openai_model,
            instructions=(
                "Ты KORGAN Legal AI, юридический ассистент только по действующему праву Республики Казахстан. "
                "Юридические выводы без официального источника запрещены. "
                f"Отвечай на {'казахском' if language == 'kk' else 'русском'}."
            ),
            input=prompt,
            tools=tools,
            tool_choice="required",
            store=False,
        )

        urls = [url for url in self._annotation_urls(response) if self._allowed_source(url)]
        LOGGER.info("KORGAN consultation: official_sources=%d", len(urls))

        if not urls:
            return (
                "⚠️ NEEDS_VERIFICATION\n\n"
                "Не удалось получить подтверждение из разрешенного официального источника. "
                "Я не буду давать конкретные статьи, сроки, госпошлину, подсудность или вид производства из памяти. "
                "Повторите запрос позже или уточните факты дела.",
                [],
            )

        answer = response.output_text.strip()
        if "NEEDS_VERIFICATION" not in answer and urls:
            answer = "✅ VERIFIED SOURCES USED\n\n" + answer
        return answer, urls
