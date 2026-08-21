from __future__ import annotations

import base64
import json
import logging
from datetime import date
from typing import Any

from korgan.legal_types import ExtractedDocument, LegalResearch, VerificationStatus
from korgan.openai_legal import OpenAILegalService, _RESEARCH_SCHEMA

LOGGER = logging.getLogger(__name__)

# These Adilet document ids are obsolete for the legal questions KORGAN handles here.
# They may still be indexed by search engines, so domain allowlisting alone is not enough.
_DEPRECATED_SOURCE_MARKERS = (
    "K990000411_",  # old Civil Procedure Code (1999)
    "Z960000065_",  # old Law on State Duty
    "K1700000120",  # Tax Code 2017, superseded from 01.01.2026
)

_CURRENT_CORE_ACTS = (
    "Действующий ГПК РК: https://adilet.zan.kz/rus/docs/K1500000377",
    "ГК РК (Общая часть): https://adilet.zan.kz/rus/docs/K940001000_",
    "ГК РК (Особенная часть): https://adilet.zan.kz/rus/docs/K990000409_",
    "Налоговый кодекс РК 2025, действующий с 01.01.2026: https://adilet.zan.kz/rus/docs/K2500000214",
)

_STRICT_EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string"},
        "text_summary": {"type": "string"},
        "parties": {"type": "array", "items": {"type": "string"}},
        "identifiers": {"type": "array", "items": {"type": "string"}},
        "addresses": {"type": "array", "items": {"type": "string"}},
        "contacts": {"type": "array", "items": {"type": "string"}},
        "dates": {"type": "array", "items": {"type": "string"}},
        "amounts": {"type": "array", "items": {"type": "string"}},
        "obligations": {"type": "array", "items": {"type": "string"}},
        "violations": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "important_facts": {"type": "array", "items": {"type": "string"}},
        "missing_or_unclear": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "document_type", "text_summary", "parties", "identifiers", "addresses", "contacts",
        "dates", "amounts", "obligations", "violations", "evidence", "important_facts",
        "missing_or_unclear"
    ],
    "additionalProperties": False,
}


class StrictOpenAILegalService(OpenAILegalService):
    """KORGAN legal service with mandatory current-law research and fail-closed output."""

    def _is_current_official_source(self, url: str) -> bool:
        return self._allowed_source(url) and not any(marker in url for marker in _DEPRECATED_SOURCE_MARKERS)

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
            kwargs["tool_choice"] = "required"

        response = await self.client.responses.create(**kwargs)
        payload = json.loads(response.output_text)
        urls = [url for url in self._annotation_urls(response) if self._is_current_official_source(url)]
        LOGGER.info("KORGAN structured research: current_official_sources=%d", len(urls))
        return payload, response

    async def extract_document(
        self,
        data: bytes,
        filename: str,
        mime_type: str | None = None,
    ) -> ExtractedDocument:
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        prompt = (
            "Извлеки ТОЛЬКО факты, которые реально присутствуют в документе. "
            "Особенно важно сохранить данные, необходимые для судебного иска: роли и полные ФИО сторон, "
            "ИИН/БИН/номера документов, каждый адрес вместе с указанием кому он принадлежит, телефоны/e-mail, "
            "даты, суммы, предмет обязательства, срок исполнения, факт оплаты/передачи денег, факт нарушения, "
            "доказательства и приложения. Ничего не достраивай по догадке. Нечитаемое вынеси в missing_or_unclear."
        )

        if suffix in {"jpg", "jpeg", "png", "webp"} or (mime_type or "").startswith("image/"):
            media = mime_type or ("image/png" if suffix == "png" else "image/jpeg")
            encoded = base64.b64encode(data).decode("ascii")
            content: list[dict[str, Any]] = [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:{media};base64,{encoded}", "detail": "high"},
                ],
            }]
        elif suffix == "docx":
            text = self._docx_text(data)
            content = [{"role": "user", "content": [{
                "type": "input_text",
                "text": f"{prompt}\n\nТекст DOCX:\n{text[:self.settings.max_case_text_chars]}",
            }]}]
        elif suffix == "txt":
            text = data.decode("utf-8", errors="replace")
            content = [{"role": "user", "content": [{
                "type": "input_text",
                "text": f"{prompt}\n\nТекст файла:\n{text[:self.settings.max_case_text_chars]}",
            }]}]
        elif suffix == "pdf" or (mime_type or "") == "application/pdf":
            encoded = base64.b64encode(data).decode("ascii")
            content = [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_file", "filename": filename, "file_data": encoded},
                ],
            }]
        else:
            raise ValueError("Поддерживаются PDF, DOCX, TXT, JPG, JPEG, PNG и WEBP.")

        payload, _ = await self._structured_response(
            model=self.settings.openai_vision_model,
            instructions=(
                "Ты модуль судебного извлечения фактов KORGAN Legal AI. "
                "Не придумывай отсутствующие сведения и не делай правовых выводов."
            ),
            content=content,
            schema_name="korgan_strict_document_extract",
            schema=_STRICT_EXTRACT_SCHEMA,
        )
        return ExtractedDocument(filename=filename, **payload)

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": "high",
        }]
        today = date.today().isoformat()
        current_acts = "\n".join(f"- {item}" for item in _CURRENT_CORE_ACTS)
        prompt = (
            f"Дата юридической проверки: {today}. Исследуй правовую основу по действующему праву Республики Казахстан.\n\n"
            "ВАЖНО О ВЕРСИЯХ АКТОВ:\n"
            "- Для гражданского процесса используй действующий ГПК 2015 года K1500000377. "
            "НЕ используй старый ГПК K990000411_.\n"
            "- Для госпошлины на даты с 01.01.2026 используй новый Налоговый кодекс 2025 года K2500000214, "
            "в частности действующую статью о ставках госпошлины в судах. НЕ используй K1700000120 и Z960000065_.\n"
            "- Проверяй статус и редакцию каждого акта на дату проверки. Утративший силу акт не может подтверждать текущий вывод.\n\n"
            f"Ориентиры на актуальные основные акты:\n{current_acts}\n\n"
            "Проверь отдельно: материальное право, обязанность должника, вид производства, подсудность, "
            "досудебный порядок, исковую давность и начало ее течения, форму/содержание иска, приложения, "
            "госпошлину и судебные расходы. Не предлагай судебный приказ или другой специальный порядок, "
            "если действующая норма прямо не охватывает факты дела. "
            "В verified_claims помещай только выводы, подтвержденные ТЕКУЩЕЙ официальной нормой. "
            "Если что-либо не подтверждено — только в unverified_claims.\n\n"
            f"МАТЕРИАЛЫ ДЕЛА:\n{case_context[:self.settings.max_case_text_chars]}"
        )

        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты юридический исследователь KORGAN по действующему праву Республики Казахстан. "
                "Fail-closed: устаревший или непроверенный источник не подтверждает правовой вывод. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_current_legal_research",
            schema=_RESEARCH_SCHEMA,
            tools=tools,
        )

        raw_urls = self._annotation_urls(response) + list(payload.get("source_urls", []))
        stale_urls = list(dict.fromkeys(
            url for url in raw_urls
            if self._allowed_source(url) and not self._is_current_official_source(url)
        ))
        source_urls = list(dict.fromkeys(
            url for url in raw_urls if self._is_current_official_source(url)
        ))

        unverified = list(payload.get("unverified_claims", []))
        notes = list(payload.get("notes", []))
        if stale_urls:
            notes.append("Поиском были возвращены устаревшие акты; KORGAN исключил их из подтверждающих источников.")
            unverified.append("Часть результатов поиска ссылалась на утратившие силу акты и была исключена; соответствующие выводы требуют подтверждения текущим актом.")
        if not source_urls:
            unverified.append("Не найден ни один допустимый актуальный официальный источник для подтверждения правового вывода.")

        status = (
            VerificationStatus.VERIFIED
            if source_urls and not unverified
            else VerificationStatus.NEEDS_VERIFICATION
        )
        return LegalResearch(
            status=status,
            applicable_law=list(payload.get("applicable_law", [])),
            procedural_requirements=list(payload.get("procedural_requirements", [])),
            verified_claims=list(payload.get("verified_claims", [])),
            unverified_claims=unverified,
            source_urls=source_urls,
            notes=notes,
        )

    async def consult(
        self,
        question: str,
        case_context: str = "",
        language: str = "ru",
    ) -> tuple[str, list[str]]:
        research_input = (
            f"ВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{question}\n\n"
            f"КОНТЕКСТ ДОКУМЕНТОВ:\n{case_context[:30000] if case_context else 'нет'}"
        )
        research = await self.research_case(research_input, language=language)

        if not research.source_urls:
            return (
                "⚠️ NEEDS_VERIFICATION\n\n"
                "Не удалось подтвердить правовую позицию актуальным официальным источником. "
                "KORGAN не будет отвечать по памяти модели.",
                [],
            )

        prompt = (
            f"Вопрос:\n{question}\n\n"
            f"Фактический контекст:\n{case_context[:30000] if case_context else 'нет'}\n\n"
            f"VERIFIED CLAIMS:\n{json.dumps(research.verified_claims, ensure_ascii=False)}\n\n"
            f"UNVERIFIED CLAIMS:\n{json.dumps(research.unverified_claims, ensure_ascii=False)}\n\n"
            f"PROCEDURAL REQUIREMENTS:\n{json.dumps(research.procedural_requirements, ensure_ascii=False)}\n\n"
            f"CURRENT OFFICIAL SOURCES:\n{json.dumps(research.source_urls, ensure_ascii=False)}\n\n"
            "Сформируй практичный юридический ответ. Все конкретные статьи, сроки, ставки, подсудность и вид производства "
            "можно утверждать только если они уже находятся в VERIFIED CLAIMS. Не добавляй право из памяти. "
            "Если есть UNVERIFIED CLAIMS, перечисли их кратко как NEEDS_VERIFICATION. Не предлагай пользователю самому "
            "искать норму, если она уже подтверждена исследованием."
        )
        response = await self.client.responses.create(
            model=self.settings.openai_model,
            instructions=(
                "Ты KORGAN Legal AI. Пиши как практикующий юрист Казахстана, но используй только предоставленный "
                "verified research. Не добавляй новые нормы. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            input=prompt,
            store=False,
        )

        marker = "✅ VERIFIED" if research.status == VerificationStatus.VERIFIED else "⚠️ NEEDS_VERIFICATION"
        return f"{marker}\n\n{response.output_text.strip()}", research.source_urls
