"""Source-bound consultation guard for the live KORGAN Telegram agent.

A consultation is not allowed to cite law from model memory. One structured
Responses API call performs official-source research and returns candidate legal
points. A point becomes client-visible only when its claimed URL was actually
opened by the web-search tool and its paraphrase is mechanically compatible with
the provision text. Precise legal assertions outside that verified block are
removed from the client-facing answer.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from korgan.provision_check import paraphrase_defects
from korgan.robust_production_legal import _is_adilet_source, _is_court_source
from korgan.verified_openai import _actual_response_urls, _canonical_url

LOGGER = logging.getLogger(__name__)

_CONSULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "analysis": {"type": "array", "items": {"type": "string"}},
        "recommended_actions": {"type": "array", "items": {"type": "string"}},
        "verified_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "article": {"type": "string"},
                    "provision_text": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["statement", "article", "provision_text", "source_url"],
                "additionalProperties": False,
            },
        },
        "unverified_claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "analysis", "recommended_actions", "verified_points", "unverified_claims"],
    "additionalProperties": False,
}

# Precise law belongs only to the source-bound verified block below. These
# patterns deliberately catch article numbers, legal rates/MRP and exact legal
# periods that a free-form model sentence could otherwise smuggle into the
# answer without a verified source binding.
_PRECISE_LAW_RE = re.compile(
    r"(?i)(?:"
    r"(?:стать[ьяеию]\w*|ст\.)\s*\d+"
    r"|\b\d+(?:-\d+)?\s*[-–]?\s*бап\b"
    r"|\b\d+(?:[.,]\d+)?\s*%"
    r"|\b\d+(?:[.,]\d+)?\s*(?:мрп|аек)\b"
    r"|(?:срок\w*|мерзім\w*|госпошлин\w*|мемлекеттік\s+баж\w*|подсудност\w*|соттыл\w*)[^\n]{0,40}\b\d+\b"
    r")"
)


def _today_kz() -> str:
    return datetime.now(ZoneInfo("Asia/Almaty")).date().isoformat()


def _safe_free_text(value: str) -> str:
    """Keep practical prose only when it contains no precise unbound law."""
    text = " ".join(str(value or "").split()).strip()
    if not text or _PRECISE_LAW_RE.search(text):
        return ""
    return text


def _safe_free_lines(values: list[Any] | None) -> list[str]:
    result: list[str] = []
    for raw in values or []:
        line = _safe_free_text(str(raw))
        if line and line not in result:
            result.append(line)
    return result


def _accept_verified_points(
    service: Any,
    payload: dict[str, Any],
    response: Any,
) -> tuple[list[tuple[str, str, str]], list[str], list[str]]:
    """Return (statement, article, source) only for source-bound verified law."""
    actual_urls = [
        url
        for url in _actual_response_urls(response)
        if service._is_current_official_source(url)
    ]
    actual_by_canonical = {
        _canonical_url(url): url
        for url in actual_urls
        if _canonical_url(url)
    }

    accepted: list[tuple[str, str, str]] = []
    rejected: list[str] = []
    used_urls: list[str] = []

    for point in payload.get("verified_points", []) or []:
        statement = " ".join(str(point.get("statement", "")).split()).strip()
        article = " ".join(str(point.get("article", "")).split()).strip()
        provision_text = " ".join(str(point.get("provision_text", "")).split()).strip()
        claimed_url = str(point.get("source_url", "")).strip()
        actual_url = actual_by_canonical.get(_canonical_url(claimed_url))

        if not statement or not article or not actual_url:
            if statement:
                rejected.append(f"{statement} — нет связи с реально открытым официальным источником.")
            continue

        if _is_court_source(actual_url):
            if article.lower() != "официальный перечень судов":
                rejected.append(f"{statement} — страница суда не подтверждает норму права.")
                continue
        else:
            if not _is_adilet_source(actual_url):
                rejected.append(f"{statement} — источник нормы не является Adilet.")
                continue
            drift = paraphrase_defects(statement, provision_text)
            if drift:
                rejected.append(f"{statement} — {'; '.join(drift[:3])}")
                continue

        item = (statement, article, actual_url)
        if item not in accepted:
            accepted.append(item)
        if actual_url not in used_urls:
            used_urls.append(actual_url)

    return accepted, rejected, used_urls


def _render_consultation(
    payload: dict[str, Any],
    accepted: list[tuple[str, str, str]],
    rejected: list[str],
    *,
    language: str,
) -> str:
    kk = language == "kk"
    summary = _safe_free_text(str(payload.get("summary", "")))
    analysis = _safe_free_lines(payload.get("analysis", []))
    actions = _safe_free_lines(payload.get("recommended_actions", []))
    unverified = [
        " ".join(str(x).split()).strip()
        for x in payload.get("unverified_claims", []) or []
        if " ".join(str(x).split()).strip()
    ]
    unverified.extend(x for x in rejected if x not in unverified)

    if not accepted:
        if kk:
            base = (
                "Ресми дереккөзден құқықтық қорытындыны жеткілікті деңгейде растай алмадым. "
                "Тексерілмеген бапты немесе мерзімді заң ретінде көрсетпеймін."
            )
            if unverified:
                base += "\n\nҚосымша тексеру қажет:\n" + "\n".join(f"• {x}" for x in unverified[:5])
            return base
        base = (
            "Не удалось достаточно подтвердить правовой вывод по официальному источнику. "
            "Я не буду выдавать непроверенную статью, срок, ставку или подсудность как действующее право."
        )
        if unverified:
            base += "\n\nТребует дополнительной проверки:\n" + "\n".join(f"• {x}" for x in unverified[:5])
        return base

    parts: list[str] = []
    if summary:
        parts.append(("Қысқаша қорытынды:\n" if kk else "Краткий вывод:\n") + summary)
    if analysis:
        parts.append(("Іс бойынша бағалау:\n" if kk else "Оценка ситуации:\n") + "\n".join(f"• {x}" for x in analysis[:6]))

    law_title = "Расталған құқықтық негіз:" if kk else "Подтверждено по действующему праву РК:"
    law_lines = [f"• {statement} Основание: {article}." for statement, article, _ in accepted[:8]]
    parts.append(law_title + "\n" + "\n".join(law_lines))

    if actions:
        parts.append(("Не істеу керек:\n" if kk else "Что делать:\n") + "\n".join(f"• {x}" for x in actions[:6]))
    if unverified:
        parts.append(("Қосымша тексеру қажет:\n" if kk else "Требует дополнительной проверки:\n") + "\n".join(f"• {x}" for x in unverified[:5]))

    checked = _today_kz()
    parts.append((f"Құқықтың өзектілігі тексерілген күн: {checked}." if kk else f"Актуальность права проверена: {checked}."))
    return "\n\n".join(parts)


async def _guarded_consult(
    self: Any,
    question: str,
    case_context: str = "",
    language: str = "ru",
) -> tuple[str, list[str]]:
    """One official source-bound call; no free-form legal citation is released."""
    tools = [{
        "type": "web_search",
        "filters": {"allowed_domains": self.settings.legal_domains},
        "search_context_size": "medium",
    }]
    prompt = (
        f"Дата проверки: {_today_kz()}. Ответь на юридический вопрос только по действующему праву Республики Казахстан.\n\n"
        "КРИТИЧЕСКИЙ ФОРМАТ:\n"
        "1. summary, analysis и recommended_actions — практическая работа с фактами, БЕЗ номеров статей, точных законных сроков, ставок, МРП/АЕК и точного наименования суда.\n"
        "2. Любая точная норма, срок, ставка, подсудность или иной юридически точный вывод помещается ТОЛЬКО в verified_points.\n"
        "3. Каждый verified_point: конкретный вывод + точная статья/пункт + существенная дословная выдержка provision_text + URL официальной страницы, которую ты реально открыл.\n"
        "4. Материальное и процессуальное право подтверждай по Adilet. gov.kz/sud.gov.kz допускаются только для официального наименования/структуры суда; тогда article='официальный перечень судов'.\n"
        "5. Если официальный источник не подтверждает вывод, помещай его в unverified_claims. Не угадывай.\n"
        "6. Не обещай исход дела. Отделяй факты пользователя от правовых выводов.\n\n"
        f"ВОПРОС:\n{question}\n\n"
        f"КОНТЕКСТ ДЕЛА:\n{case_context[:self.settings.max_case_text_chars] if case_context else 'нет'}"
    )
    payload, response = await self._structured_response(
        model=self.settings.openai_model,
        instructions=(
            "Ты ведущий юрист KORGAN по праву Республики Казахстан. Работай source-bound и fail-closed. "
            "Ни одна точная норма не должна попасть клиенту из памяти модели. "
            f"Язык: {'казахский' if language == 'kk' else 'русский'}."
        ),
        content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        schema_name="korgan_consult_research",
        schema=_CONSULT_SCHEMA,
        tools=tools,
    )

    accepted, rejected, used_urls = _accept_verified_points(self, payload, response)
    answer = _render_consultation(payload, accepted, rejected, language=language)
    LOGGER.info(
        "KORGAN_CONSULTATION_GATE verified=%d rejected=%d sources=%d",
        len(accepted),
        len(rejected),
        len(used_urls),
    )
    return answer, used_urls


def install_professional_consultation_guard() -> None:
    """Bind guarded consultations to the stable service used by strict_bot."""
    from korgan.stable_legal_release import StableLegalProductionService

    if getattr(StableLegalProductionService, "_korgan_professional_consultation_guard", False):
        return
    StableLegalProductionService.consult = _guarded_consult  # type: ignore[method-assign]
    StableLegalProductionService._korgan_professional_consultation_guard = True
    LOGGER.info("Installed KORGAN professional consultation citation gate")
