from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from korgan.contract_generation_hotfix import ProductionOpenAILegalService as _ContractSafeService
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.response_types import ResponseToClaimDraft
from korgan.verified_openai import _VERIFIED_RESEARCH_SCHEMA, _actual_response_urls, _canonical_url

LOGGER = logging.getLogger(__name__)

_RESPONSE_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "court": {"type": "string"},
        "case_number": {"type": "string"},
        "claimant": {"type": "array", "items": {"type": "string"}},
        "defendant": {"type": "array", "items": {"type": "string"}},
        "claim_summary": {"type": "array", "items": {"type": "string"}},
        "position": {"type": "array", "items": {"type": "string"}},
        "objections": {"type": "array", "items": {"type": "string"}},
        "legal_basis": {"type": "array", "items": {"type": "string"}},
        "requests": {"type": "array", "items": {"type": "string"}},
        "attachments": {"type": "array", "items": {"type": "string"}},
        "verification_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title", "court", "case_number", "claimant", "defendant", "claim_summary",
        "position", "objections", "legal_basis", "requests", "attachments", "verification_notes"
    ],
    "additionalProperties": False,
}

_FORBIDDEN_BODY_MARKERS = (
    "http://",
    "https://",
    "официальные источники",
    "могу доработать",
    "если нужно",
    "###",
    "**",
)


def _today_kz() -> str:
    return datetime.now(ZoneInfo("Asia/Almaty")).date().isoformat()


def _is_adilet(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "adilet.zan.kz" or host.endswith(".adilet.zan.kz")


def _has_article_166(claims: list[str]) -> bool:
    text = "\n".join(claims)
    return bool(re.search(r"(?i)(?:статья|статьи|ст\.)\s*166\b|\b166\b.{0,40}\bотзыв", text))


def _allowed_article_numbers(claims: list[str]) -> set[str]:
    allowed: set[str] = set()
    for claim in claims:
        match = re.search(r"\[основание:\s*(.*?);\s*источник:", claim, flags=re.IGNORECASE)
        basis = match.group(1) if match else claim
        found = re.findall(r"(?i)(?:статья|статьи|ст\.)\s*(\d+(?:-\d+)?)", basis)
        allowed.update(found)
        if not found:
            standalone = re.fullmatch(r"\s*(\d+(?:-\d+)?)\s*", basis)
            if standalone:
                allowed.add(standalone.group(1))
    return allowed


def _article_numbers_in_text(text: str) -> set[str]:
    return set(re.findall(r"(?i)(?:статья|статьи|ст\.)\s*(\d+(?:-\d+)?)", text or ""))


def _placeholder_present(draft: ResponseToClaimDraft) -> bool:
    return any("[ТРЕБУЕТ УТОЧНЕНИЯ" in line.upper() for line in draft.body_lines())


class ProductionOpenAILegalService(_ContractSafeService):
    """Production runtime with a dedicated source-bound response-to-claim flow."""

    async def _response_structured(
        self,
        *,
        instructions: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], Any]:
        last_error: Exception | None = None
        for attempt, limit in enumerate((max_tokens, max_tokens + 3000), start=1):
            kwargs: dict[str, Any] = {
                "model": self.settings.openai_model,
                "instructions": instructions,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                "text": self._json_schema(schema_name, schema),
                "store": False,
                "max_output_tokens": limit,
                "prompt_cache_key": f"korgan:{schema_name}:response-v1",
            }
            model = self.settings.openai_model
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
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                last_error = exc
                LOGGER.warning(
                    "KORGAN response JSON incomplete schema=%s attempt=%d chars=%d error=%s",
                    schema_name, attempt, len(text), exc,
                )
                if attempt == 1:
                    continue
                raise
            LOGGER.info(
                "KORGAN response structured schema=%s attempt=%d seconds=%.2f chars=%d urls=%d",
                schema_name, attempt, elapsed, len(text), len(_actual_response_urls(response)),
            )
            return payload, response
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Response structured call failed: {schema_name}")

    async def _research_response_once(
        self,
        case_context: str,
        language: str,
        *,
        search_context_size: str,
    ) -> LegalResearch:
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": ["adilet.zan.kz"]},
            "search_context_size": search_context_size,
        }]
        prompt = (
            f"Дата проверки: {_today_kz()}. Подготовь source-bound правовое исследование для ОТЗЫВА НА ИСК по действующему праву Республики Казахстан.\n\n"
            "ОБЯЗАТЕЛЬНО:\n"
            "1. Открой действующий ГПК РК и проверь статью 166 «Отзыв на иск»: срок, содержание, доказательства, приложения и подписание.\n"
            "2. Из материалов выдели каждое требование истца и его предполагаемое материально-правовое основание.\n"
            "3. Для возражений ответчика найди только те профильные нормы материального права, которые реально относятся к заявленным требованиям и имеющимся фактам.\n"
            "4. Не придумывай обстоятельства, доказательства, признание долга, оплату, переписку, сроки или возражения, которых нет в материалах.\n"
            "5. Каждый verified_point должен содержать конкретный применимый вывод, точную статью/пункт и URL реально открытой страницы Adilet.\n"
            "6. Если довод нельзя подтвердить действующей нормой или фактами, помести его только в unverified_claims.\n"
            "7. Не превращай отзыв во встречный иск и не добавляй самостоятельные требования ответчика без прямого запроса пользователя.\n\n"
            f"МАТЕРИАЛЫ ДЕЛА:\n{case_context[:self.settings.max_case_text_chars]}"
        )
        payload, response = await self._response_structured(
            instructions=(
                "Ты судебный юрист KORGAN, защищающий позицию ответчика в гражданском процессе Республики Казахстан. "
                "Работай строго source-bound по Adilet. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            prompt=prompt,
            schema_name="korgan_response_research",
            schema=_VERIFIED_RESEARCH_SCHEMA,
            max_tokens=3600,
            tools=tools,
        )

        actual_urls = [url for url in _actual_response_urls(response) if _is_adilet(url) and self._is_current_official_source(url)]
        actual_by_canonical = {_canonical_url(url): url for url in actual_urls if _canonical_url(url)}
        verified: list[str] = []
        rejected: list[str] = []
        used: list[str] = []
        for point in payload.get("verified_points", []):
            statement = str(point.get("statement", "")).strip()
            article = str(point.get("article", "")).strip()
            claimed_url = str(point.get("source_url", "")).strip()
            actual_url = actual_by_canonical.get(_canonical_url(claimed_url))
            if not statement or not article or not actual_url:
                if statement:
                    rejected.append(f"{statement} — не принят как VERIFIED: нет source-bound Adilet источника.")
                continue
            verified.append(f"{statement} [основание: {article}; источник: {actual_url}]")
            if actual_url not in used:
                used.append(actual_url)

        unverified = [str(x) for x in payload.get("unverified_claims", [])] + rejected
        if not _has_article_166(verified):
            unverified.append("Не подтверждена действующая статья 166 ГПК РК об отзыве на иск.")

        return LegalResearch(
            status=VerificationStatus.VERIFIED if verified and used and not unverified else VerificationStatus.NEEDS_VERIFICATION,
            applicable_law=[str(x) for x in payload.get("applicable_law", [])],
            procedural_requirements=[str(x) for x in payload.get("procedural_requirements", [])],
            verified_claims=verified,
            unverified_claims=unverified,
            source_urls=used,
            notes=[str(x) for x in payload.get("notes", [])],
        )

    async def research_response_to_claim(self, case_context: str, language: str = "ru") -> LegalResearch:
        research = await self._research_response_once(case_context, language, search_context_size="medium")
        if not research.source_urls or not _has_article_166(research.verified_claims):
            LOGGER.info("KORGAN response research targeted fallback article_166=%s", _has_article_166(research.verified_claims))
            research = await self._research_response_once(case_context, language, search_context_size="high")
        return research

    async def draft_response_to_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ResponseToClaimDraft:
        prompt = (
            "Составь профессиональный ОТЗЫВ НА ИСК для суда Республики Казахстан от имени ответчика.\n\n"
            "ПРАВИЛА:\n"
            "1. Факты, суммы, даты, стороны и доказательства бери ТОЛЬКО из материалов пользователя. Не заполняй пробелы догадками.\n"
            "2. Разбери требования истца по существу: для каждого существенного требования сформулируй отдельное возражение, если материалы дают для этого основание.\n"
            "3. Не пиши, что ответчик признаёт или не признаёт иск полностью, если позиция пользователя из материалов этого не следует. В таком случае сформулируй позицию осторожно и отметь пробел в verification_notes.\n"
            "4. Точные статьи и юридические выводы разрешены ТОЛЬКО из блока VERIFIED. Никаких статей по памяти.\n"
            "5. Не добавляй встречный иск, новые денежные требования, компенсации, штрафы или ходатайства, если пользователь этого не просил.\n"
            "6. Просительная часть должна соответствовать позиции и материалам: например, отказать полностью/частично только когда это действительно следует из позиции ответчика.\n"
            "7. Приложения перечисляй только из реально имеющихся/упомянутых материалов и процессуально обязательных копий, подтверждённых VERIFIED.\n"
            "8. Не вставляй URL, служебные комментарии, Markdown или фразы ассистента в текст судебного документа.\n"
            "9. Неизвестный суд, номер дела или реквизит оставляй как [ТРЕБУЕТ УТОЧНЕНИЯ: ...], а не выдумывай.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"VERIFIED:\n{json.dumps(research.verified_claims, ensure_ascii=False)}\n\n"
            f"UNVERIFIED/ПРОБЕЛЫ:\n{json.dumps(research.unverified_claims, ensure_ascii=False)}"
        )
        payload, _ = await self._response_structured(
            instructions=(
                "Ты опытный процессуальный юрист KORGAN по гражданским делам Республики Казахстан. "
                "Текст должен быть пригодным для Word и суда, без выдуманных фактов и неподтверждённых норм. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            prompt=prompt,
            schema_name="korgan_response_draft",
            schema=_RESPONSE_DRAFT_SCHEMA,
            max_tokens=7000,
        )

        notes = [str(x).strip() for x in payload.get("verification_notes", []) if str(x).strip()]
        notes.extend(str(x) for x in research.unverified_claims if str(x).strip())
        allowed_articles = _allowed_article_numbers(research.verified_claims)
        legal_basis: list[str] = []
        for raw in payload.get("legal_basis", []):
            item = str(raw).strip()
            if not item:
                continue
            mentioned = _article_numbers_in_text(item)
            if mentioned and not mentioned.issubset(allowed_articles):
                notes.append("Исключено из правового обоснования как неподтверждённая точная норма: " + item)
                continue
            if any(marker in item.lower() for marker in _FORBIDDEN_BODY_MARKERS):
                notes.append("Исключён служебный/ссылочный текст из правового обоснования.")
                continue
            legal_basis.append(item)

        draft = ResponseToClaimDraft(
            status=research.status,
            title=str(payload.get("title", "ОТЗЫВ НА ИСК")).strip() or "ОТЗЫВ НА ИСК",
            court=str(payload.get("court", "")).strip(),
            case_number=str(payload.get("case_number", "")).strip(),
            claimant=[str(x).strip() for x in payload.get("claimant", []) if str(x).strip()],
            defendant=[str(x).strip() for x in payload.get("defendant", []) if str(x).strip()],
            claim_summary=[str(x).strip() for x in payload.get("claim_summary", []) if str(x).strip()],
            position=[str(x).strip() for x in payload.get("position", []) if str(x).strip()],
            objections=[str(x).strip() for x in payload.get("objections", []) if str(x).strip()],
            legal_basis=legal_basis,
            requests=[str(x).strip() for x in payload.get("requests", []) if str(x).strip()],
            attachments=[str(x).strip() for x in payload.get("attachments", []) if str(x).strip()],
            verification_notes=list(dict.fromkeys(notes)),
            source_urls=list(research.source_urls),
        )

        body = "\n".join(draft.body_lines()).lower()
        for marker in _FORBIDDEN_BODY_MARKERS:
            if marker in body:
                draft.verification_notes.append(f"Обнаружен и требует удаления служебный текст: {marker}")
                draft.status = VerificationStatus.NEEDS_VERIFICATION

        if _placeholder_present(draft) or draft.verification_notes:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
        return draft
