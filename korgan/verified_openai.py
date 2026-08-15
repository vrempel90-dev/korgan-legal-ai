from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any
from urllib.parse import urlparse

from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.strict_openai import StrictOpenAILegalService

LOGGER = logging.getLogger(__name__)

_VERIFIED_RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "applicable_law": {"type": "array", "items": {"type": "string"}},
        "procedural_requirements": {"type": "array", "items": {"type": "string"}},
        "verified_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "article": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["statement", "article", "source_url"],
                "additionalProperties": False,
            },
        },
        "unverified_claims": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "applicable_law",
        "procedural_requirements",
        "verified_points",
        "unverified_claims",
        "notes",
    ],
    "additionalProperties": False,
}


def _canonical_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{parsed.path.rstrip('/')}"


def _append_url(urls: list[str], value: Any) -> None:
    if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in urls:
        urls.append(value)


def _actual_response_urls(response: Any) -> list[str]:
    """Return URLs that came from actual Responses API search/citation objects.

    We deliberately do not trust URLs merely printed by the model in output_text.
    """
    urls: list[str] = []

    try:
        data = response.model_dump(exclude_none=True)
    except Exception:
        data = None

    if isinstance(data, dict):
        for item in data.get("output", []) or []:
            if not isinstance(item, dict):
                continue

            # Full source list for a web search call. This is populated when
            # include=["web_search_call.action.sources"] is requested.
            if item.get("type") == "web_search_call":
                action = item.get("action") or {}
                if isinstance(action, dict):
                    _append_url(urls, action.get("url"))
                    for source in action.get("sources", []) or []:
                        if isinstance(source, dict):
                            _append_url(urls, source.get("url"))

            # URL citations attached to final output text are also actual
            # response metadata and therefore safe to treat as searched URLs.
            if item.get("type") == "message":
                for content in item.get("content", []) or []:
                    if not isinstance(content, dict):
                        continue
                    for annotation in content.get("annotations", []) or []:
                        if isinstance(annotation, dict) and annotation.get("type") == "url_citation":
                            _append_url(urls, annotation.get("url"))

    # Backward-compatible object traversal for SDK response classes.
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) == "web_search_call":
            action = getattr(item, "action", None)
            _append_url(urls, getattr(action, "url", None))
            for source in getattr(action, "sources", []) or []:
                _append_url(urls, getattr(source, "url", None))
        if getattr(item, "type", None) == "message":
            for content in getattr(item, "content", []) or []:
                for annotation in getattr(content, "annotations", []) or []:
                    if getattr(annotation, "type", None) == "url_citation":
                        _append_url(urls, getattr(annotation, "url", None))

    return urls


class VerifiedOpenAILegalService(StrictOpenAILegalService):
    """Strict service where every VERIFIED statement maps to an actual web-search source."""

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
            # Responses API only returns the complete list of web-search
            # sources when this include field is requested.
            kwargs["include"] = ["web_search_call.action.sources"]

        response = await self.client.responses.create(**kwargs)
        payload = json.loads(response.output_text)
        source_urls = _actual_response_urls(response)
        output_types = [getattr(item, "type", type(item).__name__) for item in getattr(response, "output", []) or []]
        LOGGER.info(
            "KORGAN Responses metadata: output_types=%s actual_web_urls=%d",
            output_types,
            len(source_urls),
        )
        return payload, response

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": "high",
        }]

        today = date.today().isoformat()
        prompt = (
            f"Дата проверки: {today}. Проведи юридическое исследование только по действующему праву Республики Казахстан.\n\n"
            "КРИТИЧЕСКИЕ ПРАВИЛА:\n"
            "1. Каждый вывод в verified_points ОБЯЗАН иметь точный номер статьи и URL официальной страницы Adilet, "
            "которую ты реально открыл через web search. Один общий список ссылок недостаточен.\n"
            "2. Не используй старый ГПК K990000411_, старый Закон о госпошлине Z960000065_ и старый Налоговый кодекс K1700000120.\n"
            "3. Для гражданского процесса проверяй действующий ГПК K1500000377.\n"
            "4. Для договора займа проверяй действующий ГК (Особенная часть) K990000409_, особенно статьи 715 и 722, если они применимы к фактам.\n"
            "5. Для исковой давности проверяй ГК (Общая часть) K940001000_, особенно статьи 178 и 180.\n"
            "6. Для обычного гражданского иска проверяй ГПК, в частности статьи 26, 29, 148 и 149, если они применимы.\n"
            "7. При обсуждении судебного приказа сначала полностью проверь действующую статью 135 ГПК. "
            "Не считай обычный письменный договор займа основанием для приказа, если такого действующего подпункта в статье 135 нет.\n"
            "8. Для госпошлины на дату после 01.01.2026 используй Налоговый кодекс 2025 года K2500000214, "
            "проверь статью 665 и возможные льготы по статье 668. Если ставка для данного истца и требования подтверждена, "
            "рассчитай конкретную сумму от цены иска. Если нет — оставь NEEDS_VERIFICATION.\n"
            "9. Не делай вывод об обязательном или необязательном претензионном порядке только из отсутствия результата поиска. "
            "Такой вывод можно поместить в verified_points лишь при наличии конкретной действующей нормы, которая его подтверждает; иначе unverified_claims.\n"
            "10. Если точная норма не подтверждена — она запрещена в verified_points.\n\n"
            f"МАТЕРИАЛЫ ДЕЛА:\n{case_context[:self.settings.max_case_text_chars]}"
        )

        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты юридический исследователь KORGAN. Работай fail-closed и проверяй актуальную редакцию каждого акта. "
                f"Язык результата: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_verified_legal_research",
            schema=_VERIFIED_RESEARCH_SCHEMA,
            tools=tools,
        )

        actual_urls = [
            url for url in _actual_response_urls(response)
            if self._is_current_official_source(url)
        ]
        actual_by_canonical = {
            _canonical_url(url): url
            for url in actual_urls
            if _canonical_url(url)
        }

        verified_claims: list[str] = []
        rejected: list[str] = []
        used_urls: list[str] = []

        for point in payload.get("verified_points", []):
            statement = str(point.get("statement", "")).strip()
            article = str(point.get("article", "")).strip()
            claimed_url = str(point.get("source_url", "")).strip()
            canonical = _canonical_url(claimed_url)
            actual_url = actual_by_canonical.get(canonical)

            if not statement or not article or not actual_url:
                if statement:
                    rejected.append(
                        f"{statement} — не принят как VERIFIED: нет подтвержденной связи с фактически открытой официальной страницей."
                    )
                continue

            verified_claims.append(f"{statement} [статья {article}; источник: {actual_url}]")
            if actual_url not in used_urls:
                used_urls.append(actual_url)

        unverified = list(payload.get("unverified_claims", [])) + rejected
        notes = list(payload.get("notes", []))

        if not verified_claims:
            unverified.append("Не удалось подтвердить ни одного правового вывода с привязкой к конкретной статье и фактически открытому источнику Adilet.")
        if not used_urls:
            unverified.append("Нет допустимых актуальных официальных источников, непосредственно связанных с VERIFIED-выводами.")

        status = (
            VerificationStatus.VERIFIED
            if verified_claims and used_urls and not unverified
            else VerificationStatus.NEEDS_VERIFICATION
        )

        return LegalResearch(
            status=status,
            applicable_law=list(payload.get("applicable_law", [])),
            procedural_requirements=list(payload.get("procedural_requirements", [])),
            verified_claims=verified_claims,
            unverified_claims=unverified,
            source_urls=used_urls,
            notes=notes,
        )
