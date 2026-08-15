from __future__ import annotations

import json
from datetime import date
from typing import Any
from urllib.parse import urlparse

from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.strict_openai import StrictOpenAILegalService

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


class VerifiedOpenAILegalService(StrictOpenAILegalService):
    """Strict service where every VERIFIED statement must map to an actual web-search source."""

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
            url for url in self._annotation_urls(response)
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
