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

            if item.get("type") == "web_search_call":
                action = item.get("action") or {}
                if isinstance(action, dict):
                    _append_url(urls, action.get("url"))
                    for source in action.get("sources", []) or []:
                        if isinstance(source, dict):
                            _append_url(urls, source.get("url"))

            if item.get("type") == "message":
                for content in item.get("content", []) or []:
                    if not isinstance(content, dict):
                        continue
                    for annotation in content.get("annotations", []) or []:
                        if isinstance(annotation, dict) and annotation.get("type") == "url_citation":
                            _append_url(urls, annotation.get("url"))

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
    """Strict service where every VERIFIED statement maps to an actual official web-search source."""

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
            "1. Каждый правовой вывод в verified_points ОБЯЗАН иметь точный номер статьи и URL официальной страницы Adilet, "
            "которую ты реально открыл через web search. Исключение только для проверки официального наименования/юрисдикции конкретного суда: "
            "для этого разрешены официальные страницы gov.kz и sud.gov.kz, а в поле article укажи 'официальный перечень судов'.\n"
            "2. gov.kz и sud.gov.kz НЕЛЬЗЯ использовать вместо Adilet для подтверждения материального или процессуального права; "
            "они разрешены только для структуры, наименования и юрисдикции суда.\n"
            "3. Не используй старый ГПК K990000411_, старый Закон о госпошлине Z960000065_ и старый Налоговый кодекс K1700000120.\n"
            "4. Для гражданского процесса проверяй действующий ГПК K1500000377.\n"
            "5. Для договора займа проверяй действующий ГК (Особенная часть) K990000409_, особенно статьи 715 и 722, если они применимы к фактам.\n"
            "6. Для исковой давности проверяй ГК (Общая часть) K940001000_, особенно статьи 178 и 180, но не раздувай итоговый иск вопросом давности, "
            "если из дат очевидно, что риска пропуска нет и стороны этот вопрос не ставят.\n"
            "7. Для обычного гражданского иска проверяй ГПК, в частности статьи 26, 29, 148 и 149, если они применимы.\n"
            "8. При обсуждении судебного приказа сначала полностью проверь действующую статью 135 ГПК. "
            "Не считай обычный письменный договор займа основанием для приказа, если такого действующего подпункта в статье 135 нет.\n"
            "9. Для госпошлины на дату после 01.01.2026 используй Налоговый кодекс 2025 года K2500000214, "
            "проверь статью 665 и возможные льготы по статье 668. Если ставка для данного истца и требования подтверждена, "
            "рассчитай конкретную сумму от цены иска. Если нет — оставь NEEDS_VERIFICATION.\n"
            "10. Не делай вывод об обязательном или необязательном претензионном порядке только из отсутствия результата поиска. "
            "Такой вывод можно поместить в verified_points лишь при наличии конкретной действующей нормы, которая его подтверждает; иначе unverified_claims.\n"
            "11. Если в материалах есть полный адрес ответчика с городом и районом, отдельно проверь: (а) правило территориальной подсудности по действующему ГПК на Adilet; "
            "(б) точное действующее наименование суда гражданской юрисдикции для этого района по официальной странице gov.kz или sud.gov.kz. "
            "Не угадывай название суда. Если оба элемента подтверждены, добавь verified_point с точным названием суда и в notes добавь РОВНО одну строку "
            "формата 'VERIFIED_COURT: <точное официальное наименование суда>'. Если точный суд не подтвержден — такой строки быть не должно.\n"
            "12. Не включай в итоговый иск неизвестные телефон/e-mail ответчика как обязательные placeholders: такие сведения указываются только если известны истцу.\n"
            "13. Если точная норма не подтверждена — она запрещена в verified_points.\n\n"
            f"МАТЕРИАЛЫ ДЕЛА:\n{case_context[:self.settings.max_case_text_chars]}"
        )

        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты юридический исследователь KORGAN. Работай fail-closed и проверяй актуальную редакцию каждого акта. "
                "Нормы права подтверждай по Adilet; gov.kz/sud.gov.kz используй только для официальной проверки суда. "
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

            verified_claims.append(f"{statement} [основание: {article}; источник: {actual_url}]")
            if actual_url not in used_urls:
                used_urls.append(actual_url)

        unverified = list(payload.get("unverified_claims", [])) + rejected
        notes = list(payload.get("notes", []))

        # A VERIFIED_COURT marker is trusted only if the same court name also
        # survived source-binding inside verified_claims.
        clean_notes: list[str] = []
        for note in notes:
            if note.startswith("VERIFIED_COURT:"):
                court = note.split(":", 1)[1].strip()
                normalized = "".join(ch.lower() for ch in court if ch.isalnum())
                if normalized and any(
                    normalized in "".join(ch.lower() for ch in claim if ch.isalnum())
                    for claim in verified_claims
                ):
                    clean_notes.append(note)
                continue
            clean_notes.append(note)
        notes = clean_notes

        if not verified_claims:
            unverified.append("Не удалось подтвердить ни одного правового вывода с привязкой к конкретному основанию и фактически открытому официальному источнику.")
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