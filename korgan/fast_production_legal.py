from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.repaired_production_legal import (
    ProductionOpenAILegalService as _BaseProductionOpenAILegalService,
    _CONSULT_RESEARCH_SCHEMA,
    _is_adilet_url,
)
from korgan.pro_document_quality import output_limit_for, reasoning_for
from korgan.verified_openai import (
    _VERIFIED_RESEARCH_SCHEMA,
    _actual_response_urls,
    _canonical_url,
)

LOGGER = logging.getLogger(__name__)

_CLAIM_RESEARCH_CACHE_TTL_SECONDS = 15 * 60


def _today_kz() -> str:
    return datetime.now(ZoneInfo("Asia/Almaty")).date().isoformat()


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_court_source(url: str) -> bool:
    host = _host(url)
    return host in {"gov.kz", "sud.gov.kz"} or host.endswith(".gov.kz") or host.endswith(".sud.gov.kz")


class ProductionOpenAILegalService(_BaseProductionOpenAILegalService):
    """Latency-optimized production runtime without weakening source binding or final QA."""

    def __init__(self, settings):
        super().__init__(settings)
        self._claim_research_cache: dict[str, tuple[float, LegalResearch]] = {}

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
        """Keep structured calls compact and cache-friendly.

        GPT-5.1 already defaults to no extra reasoning. Explicitly retaining that
        mode prevents accidental latency growth if account/model defaults change.
        Output caps are used only for compact research/validation JSON, never for
        the actual claim draft or document extraction.
        """
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": content,
            "text": self._json_schema(schema_name, schema),
            "store": False,
            "prompt_cache_key": f"korgan:{schema_name}:v2",
        }

        reasoning = reasoning_for(schema_name, model)
        if reasoning is not None:
            kwargs["reasoning"] = reasoning

        output_limits = {
            "korgan_consult_research": 1600,
            "korgan_verified_legal_research": 2600,
            "korgan_court_ready_validation": 1400,
        }
        if schema_name in output_limits:
            kwargs["max_output_tokens"] = output_limit_for(schema_name, output_limits[schema_name])

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "required"
            kwargs["include"] = ["web_search_call.action.sources"]

        started = time.perf_counter()
        response = await self.client.responses.create(**kwargs)
        elapsed = time.perf_counter() - started

        payload = json.loads(response.output_text)
        LOGGER.info(
            "KORGAN OpenAI structured call: schema=%s seconds=%.2f actual_web_urls=%d",
            schema_name,
            elapsed,
            len(_actual_response_urls(response)),
        )
        return payload, response

    def _claim_cache_key(self, case_context: str, language: str) -> str:
        raw = f"{language}\0{case_context}".encode("utf-8", errors="replace")
        return hashlib.sha256(raw).hexdigest()

    async def _research_case_medium(self, case_context: str, language: str) -> LegalResearch:
        """Fast first pass for a court claim; exact source-binding is unchanged."""
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": "medium",
        }]

        prompt = (
            f"Дата проверки: {_today_kz()}. Проведи юридическое исследование только по действующему праву Республики Казахстан.\n\n"
            "КРИТИЧЕСКИЕ ПРАВИЛА:\n"
            "1. Каждый правовой вывод в verified_points должен иметь точный номер статьи и URL реально открытой официальной страницы.\n"
            "2. Материальное и процессуальное право подтверждай только по Adilet. gov.kz/sud.gov.kz разрешены только для точного наименования и юрисдикции суда; article='официальный перечень судов'.\n"
            "3. Не используй старый ГПК K990000411_, Z960000065_ и старый НК K1700000120.\n"
            "4. Для гражданского процесса используй действующий ГПК K1500000377; для займа — ГК Особенная часть K990000409_ (в т.ч. 715/722, если применимы); для общей части — K940001000_.\n"
            "5. Для госпошлины после 01.01.2026 проверяй НК K2500000214, статьи 665/668; не угадывай ставку или льготу.\n"
            "6. Для обычного иска проверяй необходимые нормы о компетенции, территориальной подсудности, форме и приложениях (в т.ч. ГПК 26/29/148/149, если применимы).\n"
            "7. Судебный приказ не предлагай без прямого действующего основания по статье 135 ГПК.\n"
            "8. Если есть полный адрес ответчика, проверь правило подсудности на Adilet и точное название суда на gov.kz/sud.gov.kz. При подтверждении добавь notes: 'VERIFIED_COURT: <точное название>'.\n"
            "9. Не раздувай свежий спор исковой давностью, если риска пропуска очевидно нет.\n"
            "10. Всё неподтверждённое — только в unverified_claims.\n\n"
            f"МАТЕРИАЛЫ ДЕЛА:\n{case_context[:self.settings.max_case_text_chars]}"
        )

        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты юридический исследователь KORGAN. Работай fail-closed. "
                "Проверяй актуальную редакцию и связывай каждый вывод с реально открытым официальным источником. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
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
            actual_url = actual_by_canonical.get(_canonical_url(claimed_url))

            if not statement or not article or not actual_url:
                if statement:
                    rejected.append(
                        f"{statement} — не принят как VERIFIED: нет подтвержденной связи с реально открытым официальным источником."
                    )
                continue

            # Court directories may verify only the court identity/structure.
            # They must never become a substitute for Adilet legal rules.
            if _is_court_source(actual_url) and article.lower() != "официальный перечень судов":
                rejected.append(
                    f"{statement} — не принят как VERIFIED: gov.kz/sud.gov.kz не подтверждают норму права."
                )
                continue

            verified_claims.append(f"{statement} [основание: {article}; источник: {actual_url}]")
            if actual_url not in used_urls:
                used_urls.append(actual_url)

        unverified = [str(x) for x in payload.get("unverified_claims", [])] + rejected
        notes = [str(x) for x in payload.get("notes", [])]

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
            unverified.append("Быстрый проход не подтвердил ни одного source-bound правового вывода.")
        if not used_urls:
            unverified.append("Быстрый проход не получил допустимого официального источника для VERIFIED-вывода.")

        status = (
            VerificationStatus.VERIFIED
            if verified_claims and used_urls and not unverified
            else VerificationStatus.NEEDS_VERIFICATION
        )
        return LegalResearch(
            status=status,
            applicable_law=[str(x) for x in payload.get("applicable_law", [])],
            procedural_requirements=[str(x) for x in payload.get("procedural_requirements", [])],
            verified_claims=verified_claims,
            unverified_claims=unverified,
            source_urls=used_urls,
            notes=notes,
        )

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        cache_key = self._claim_cache_key(case_context, language)
        cached = self._claim_research_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] <= _CLAIM_RESEARCH_CACHE_TTL_SECONDS:
            LOGGER.info("KORGAN claim research cache HIT")
            return cached[1]

        started = time.perf_counter()
        research = await self._research_case_medium(case_context, language)

        # Preserve the old deep-search behavior as a fail-closed fallback.
        # Common cases stop after the medium pass; difficult cases still get high context.
        if not research.verified_claims or not research.source_urls:
            LOGGER.info("KORGAN claim research: medium pass insufficient, falling back to high context")
            research = await super().research_case(case_context, language=language)

        self._claim_research_cache[cache_key] = (time.monotonic(), research)
        LOGGER.info("KORGAN claim research total seconds=%.2f", time.perf_counter() - started)
        return research

    async def consult(
        self,
        question: str,
        case_context: str = "",
        language: str = "ru",
    ) -> tuple[str, list[str]]:
        """Low-context search first for responsive consultations, still source-bound."""
        started_total = time.perf_counter()
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": ["adilet.zan.kz"]},
            "search_context_size": "low",
        }]
        research_prompt = (
            f"Дата проверки: {_today_kz()}. Исследуй только правовой вопрос пользователя по действующему праву Республики Казахстан.\n\n"
            "ПРАВИЛА:\n"
            "1. verified_points — только выводы, для которых реально открыта страница Adilet; укажи статью/пункт и URL.\n"
            "2. Если ответ зависит от договора, акта, переписки, вида документов или иных фактов — unresolved_facts.\n"
            "3. clarifying_questions — только вопросы, которые реально меняют вывод.\n"
            "4. Не выдумывай условия договора. Не ищи госпошлину, подсудность и процессуальные вопросы, если они не нужны для ответа.\n\n"
            f"ВОПРОС:\n{question}\n\n"
            f"КОНТЕКСТ:\n{case_context[:30000] if case_context else 'нет'}"
        )

        payload, research_response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты быстрый юридический исследователь KORGAN для консультаций. "
                "Fail-closed относится к нормам права, а не к способности дать практический анализ по фактам."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": research_prompt}]}],
            schema_name="korgan_consult_research",
            schema=_CONSULT_RESEARCH_SCHEMA,
            tools=tools,
        )

        actual_urls = [
            url for url in _actual_response_urls(research_response)
            if _is_adilet_url(url) and self._is_current_official_source(url)
        ]
        actual_by_canonical = {
            _canonical_url(url): url
            for url in actual_urls
            if _canonical_url(url)
        }

        verified_points: list[str] = []
        used_urls: list[str] = []
        for point in payload.get("verified_points", []):
            statement = str(point.get("statement", "")).strip()
            article = str(point.get("article", "")).strip()
            claimed_url = str(point.get("source_url", "")).strip()
            actual_url = actual_by_canonical.get(_canonical_url(claimed_url))
            if not statement or not article or not actual_url:
                continue
            verified_points.append(f"{statement} [статья/пункт: {article}; источник: {actual_url}]")
            if actual_url not in used_urls:
                used_urls.append(actual_url)

        unresolved = [str(x).strip() for x in payload.get("unresolved_facts", []) if str(x).strip()]
        clarifying = [str(x).strip() for x in payload.get("clarifying_questions", []) if str(x).strip()]

        answer_prompt = (
            f"ВОПРОС:\n{question}\n\n"
            f"КОНТЕКСТ:\n{case_context[:30000] if case_context else 'нет'}\n\n"
            f"ПОДТВЕРЖДЕННЫЕ НОРМЫ:\n{json.dumps(verified_points, ensure_ascii=False)}\n\n"
            f"НЕУСТАНОВЛЕННЫЕ ФАКТЫ:\n{json.dumps(unresolved, ensure_ascii=False)}\n\n"
            f"УТОЧНЯЮЩИЕ ВОПРОСЫ:\n{json.dumps(clarifying, ensure_ascii=False)}\n\n"
            "Ответь практично и без длинного вступления. Сначала дай вывод по сути, затем 2-5 конкретных следующих действий. "
            "Конкретное содержание закона, номера статей, сроки, обязанности и запреты утверждай только из ПОДТВЕРЖДЕННЫХ НОРМ. "
            "Если подтверждённых норм нет, не отказывайся: дай предварительный анализ по фактам и точно назови, какой документ/пункт нужен для окончательного вывода."
        )

        answer_kwargs: dict[str, Any] = {
            "model": self.settings.openai_model,
            "instructions": (
                "Ты KORGAN Legal AI, практикующий юридический ассистент по праву Казахстана. "
                "Отделяй подтвержденное право от предварительного анализа фактов. "
                f"Отвечай на {'казахском' if language == 'kk' else 'русском'}."
            ),
            "input": answer_prompt,
            "store": False,
            "max_output_tokens": 900,
            "prompt_cache_key": "korgan:consult-answer:v2",
        }
        if self.settings.openai_model == "gpt-5.1" or self.settings.openai_model.startswith("gpt-5.1-"):
            answer_kwargs["reasoning"] = {"effort": "none"}

        started_answer = time.perf_counter()
        response = await self.client.responses.create(**answer_kwargs)
        LOGGER.info("KORGAN consultation answer seconds=%.2f", time.perf_counter() - started_answer)

        fully_verified = bool(verified_points) and not unresolved
        marker = "✅ VERIFIED" if fully_verified else "⚠️ NEEDS_VERIFICATION"
        LOGGER.info(
            "KORGAN consultation total seconds=%.2f verified_points=%d urls=%d",
            time.perf_counter() - started_total,
            len(verified_points),
            len(used_urls),
        )
        return f"{marker}\n\n{response.output_text.strip()}", used_urls
